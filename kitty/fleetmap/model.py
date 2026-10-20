from __future__ import annotations

"""Assemble host-qualified fleet nodes and traffic from local and Orca facts."""
from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import threading
import time

import fleet_tmux
from .clusters import CONFIG_PATH, cluster_for, load, short_name, stage_for
from .edges import Edge, Resolver, build_edges
from .ladder import Ladder, never_prompted
from .matrix import build_matrix, derive_stage
from .orca import OrcaClient, OrcaError
from .providers import load_from_providers, providers_from_config
from .registry import list_local_sessions
from .signals import MemoryProbe, StaleChecker, decision_strip, is_stalled, running_workers
from .transcript import TranscriptFacts, read_transcript


SUBAGENT_WINDOW_S = 3600


def _match_terminals(sessions, terminals):
    """Only a unique process pane establishes actionable terminal ownership."""
    matched = {}
    for session in sessions:
        pane = session.orca_pane
        if pane is None or sum(s.orca_pane == pane for s in sessions) != 1:
            continue
        candidates = [terminal for terminal in terminals
                      if pane == (terminal.get('tabId'), terminal.get('leafId'))]
        if len(candidates) == 1:
            matched[session.session_id] = candidates[0]
    return matched


RETIRED_STATES = ('released', 'abandoned', 'failed', 'succeeded')


def _retired_workers(data, live_handles):
    """Map (host, terminal handle) to the worker record of each retired worker terminal.

    A worker is retired when its dispatch is over and Orca still retains the terminal.
    A terminal that hosts a live agent process is never retired."""
    records = {}
    for entry in data.values():
        for worker in entry['workers']:
            handle = worker.get('agentTerminalHandle')
            if (handle and worker.get('workerState') in RETIRED_STATES
                    and worker.get('terminalState') == 'retained'):
                records[handle] = worker
    return {(host, terminal['handle']): records[terminal['handle']]
            for host, entry in data.items() for terminal in entry['terminals']
            if terminal['handle'] in records and terminal['handle'] not in live_handles}


def _git_metadata(cwd):
    """Read local git facts only; remote paths must never be probed locally."""
    if not cwd:
        return '', ''
    try:
        root = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                              capture_output=True, text=True, timeout=5)
        if root.returncode:
            return '', ''
        branch = subprocess.run(['git', '-C', cwd, 'symbolic-ref', '--quiet', '--short', 'HEAD'],
                                capture_output=True, text=True, timeout=5)
        return root.stdout.strip(), branch.stdout.strip() if branch.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return '', ''


def repository_name(worktree_root):
    """Name of the repository owning a worktree: the directory holding its common git directory."""
    if not worktree_root:
        return None
    try:
        out = subprocess.run(['git', '-C', worktree_root, 'rev-parse', '--path-format=absolute',
                              '--git-common-dir'], capture_output=True, text=True, timeout=5)
        if out.returncode or not out.stdout.strip():
            return None
        common = Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        return None
    return common.parent.name or None


def _node(node_id, host, kind, facts=None):
    facts = facts or TranscriptFacts.empty()
    return dict(
        id=node_id, host=host, kind=kind, parent=None, title=facts.title or '',
        purpose=facts.purpose or '', doing=facts.doing or '', last_said=facts.last_said or '',
        state='idle', you_at=facts.you_at, it_at=facts.it_at,
        never_addressed=facts.you_at is None, cluster='Unsorted', repo='', repository='', worktree='',
        branch='', hosting='unknown', model=None, ctx_pct=None, cost=None,
        stalled=False, ladder=None, stage=None, cluster_source='unsorted',
        activity_changed_at=None, transcript_offset=facts.offset, last_output_at=None,
        run=None, pin_overridden=None,
        moves=[list(move) for move in facts.moves], terminal=None, tmux=None, kitty_window=None, kitty_pid=None)


def _run_objectives(data):
    """Join worker bindings across runtimes, ignoring the worker's host field."""
    runs = {run['id']: run for records in data.values() for run in records['runs']}
    objectives = {run['coordinator_handle']: run.get('objective') for run in runs.values()
                  if run.get('coordinator_handle')}
    for records in data.values():
        for worker in records['workers']:
            handle = worker.get('agentTerminalHandle')
            run = runs.get(worker.get('runId'))
            if handle and run:
                objectives[handle] = run.get('objective')
    return objectives


class Collector:
    def __init__(self, orca: OrcaClient | None = None, config_path=CONFIG_PATH,
                 sessions=list_local_sessions, tmux_sessions=fleet_tmux.sessions,
                 providers=None):
        self.orca = orca if orca is not None else OrcaClient()
        self.config_path = config_path
        self.sessions = sessions
        self.tmux_sessions = tmux_sessions
        self.facts = {}
        self.first_seen = {}
        self._sources = {}
        self.providers = providers if providers is not None else providers_from_config(load(config_path))
        self.ladder = Ladder()
        self.stale = StaleChecker()
        self.memory = MemoryProbe()
        self._activity = {}
        self._slow_lock = threading.Lock()
        self._slow_input = None
        self._slow = {'ladders': {}, 'memory': {}, 'stale': {}, 'hosts': {},
                      'environments': [], 'environment_error': None, 'git': {}, 'tmux': {},
                      'repository': {}}
        self._local_input = ([], set(), [])
        self._host_threads = {}
        self._screens = {}
        self._screen_attempts = {}

    @staticmethod
    def _gates(projection):
        """Yield effective row gates, keeping run and slice head targets distinct."""
        inherited = {gate['id']: (gate, None) for gate in projection.gates}
        rows = projection.slices or [{'id': projection.run, 'gates': []}]
        for row in rows:
            gates = dict(inherited)
            gates.update({gate['id']: (gate, row.get('branch')) for gate in row['gates']})
            for gate_id, (gate, branch) in gates.items():
                key = (projection.run, projection.mtime, row['id'], gate_id)
                yield key, gate, branch

    def _refresh_host(self, host, sessions):
        """One bounded probe pass per host; publish independently of other hosts."""
        with self._slow_lock:
            cached = dict(self._slow['hosts'])
        run_ids = {run['id'] for entry in cached.values()
                   for run in entry.get('data', {}).get('runs', [])}
        try:
            with self.orca.poll_budget(5):
                records = self._poll_host(host, sessions)
                env = None if host == 'local' else host
                if host == 'local':
                    try:
                        self.orca.remaining_timeout()
                        environments = self.orca.environments()
                        error = None
                    except OrcaError as exc:
                        environments, error = None, f'environments: {exc}'
                    with self._slow_lock:
                        if environments is not None:
                            self._slow['environments'] = environments
                        self._slow['environment_error'] = error
                run_ids.update(run['id'] for run in records['runs'])
                for run_id in sorted(run_ids):
                    try:
                        self.orca.remaining_timeout()
                        records['workers'].extend(self.orca.workers(env=env, run_id=run_id))
                    except OrcaError as error:
                        records['degraded'].append(f'workers: {error}')
                data = {name: entry['data'] for name, entry in cached.items() if 'data' in entry}
                data[host] = records
                workers = {w.get('agentTerminalHandle') for r in data.values() for w in r['workers']}
                self._poll_screens(host, records, workers)
            entry = dict(reachable=True, data=records)
        except Exception as error:
            entry = dict(reachable=False, error=str(error), degraded=[f'terminals: {error}'])
        with self._slow_lock:
            self._slow['hosts'] = dict(self._slow['hosts'], **{host: entry})

    def _start_hosts(self, names, sessions):
        started = []
        for name in dict.fromkeys(names):
            previous = self._host_threads.get(name)
            if previous is not None and previous.is_alive():
                continue
            thread = threading.Thread(target=self._refresh_host, args=(name, sessions),
                                      name='fleetmap-host-' + name, daemon=True)
            self._host_threads[name] = thread
            thread.start()
            started.append(thread)
        return started

    def refresh_sources(self):
        """Refresh host and checkout caches on the slow thread."""
        with self._slow_lock:
            sessions, paths, configured = self._local_input
            environments = list(self._slow['environments'])
            git = dict(self._slow['git'])
            repositories = dict(self._slow['repository'])
        names = list(dict.fromkeys(['local'] + environments + configured))
        deadline = time.monotonic() + 5
        threads = self._start_hosts(names, sessions)
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        # Newly discovered saved environments get their own budget on this pass.
        with self._slow_lock:
            discovered = [name for name in self._slow['environments'] if name not in names]
        deadline = time.monotonic() + 5
        for thread in self._start_hosts(discovered, sessions):
            thread.join(max(0, deadline - time.monotonic()))
        # Oldest entries first prevents large fleets from starving later checkouts.
        deadline = time.monotonic() + 5
        for path in sorted(paths, key=lambda path: git.get(path, (0,))[0]):
            now = time.monotonic()
            if now >= deadline:
                break
            if path not in git or now - git[path][0] >= 60:
                git[path] = (now, _git_metadata(path))
        for root in sorted({value[0] for _, value in git.values() if value[0]}):
            now = time.monotonic()
            if root not in repositories or now - repositories[root][0] >= 60:
                repositories[root] = (now, repository_name(root))
        tmux = self.tmux_sessions() if sessions else {}
        with self._slow_lock:
            self._slow.update(git=git, tmux=tmux, repository=repositories)

    def refresh_slow(self):
        """All Orca, screen, tmux and git probes live outside snapshot publication."""
        self.refresh_sources()
        with self._slow_lock:
            inputs = self._slow_input
        if inputs is None:
            return
        ladders, projections, hosts = inputs
        result = {
            'ladders': {key: self.ladder.rung(*key) for key in ladders},
            'memory': {key: self.memory.probe(*key) for key in hosts},
            'stale': {},
        }
        for projection in projections:
            for key, gate, branch in self._gates(projection):
                result['stale'][key] = self.stale.check(projection, gate, branch)
        with self._slow_lock:
            self._slow.update(result)

    def _read(self, node_id, path, *, dispatched=False):
        source = (path, dispatched)
        prev = self.facts.get(node_id) if self._sources.get(node_id) == source else None
        try:
            if path is None:
                facts = TranscriptFacts.empty()
            else:
                if prev is not None and os.path.getsize(path) < prev.offset:
                    prev = None
                facts = read_transcript(path, prev=prev,
                                        treat_dispatch_prompt_as_hassan=not dispatched)
        except OSError:
            # Discovery and reading are separate; a session can disappear between them.
            facts = TranscriptFacts.empty()
        self.facts[node_id] = facts
        self._sources[node_id] = source
        return facts

    def _enrich(self, nodes, hosts, data, resolver, config, now, retired=()):
        """Join projections and cheap overlays using the last completed probe pass."""
        roots = sorted({Path(node['worktree']) for node in nodes
                        if node['host'] == 'local' and node['worktree']})
        projections, rejected = load_from_providers(self.providers, roots)
        rejected.update({f'config:providers:{index}': note
                         for index, note in enumerate(config.notes)})
        orca_runs = {run['id']: run for records in data.values() for run in records['runs']}
        projections = [p for p in projections if p.run in orca_runs]
        by_run = {p.run: p for p in projections}
        matrices, bindings, clusters = {}, {}, {}
        initiative_names = ({name for name, _ in config.initiatives}
                            | set(config.assign.values())
                            | {project['name'] for project in config.projects}
                            | {p.title for p in projections})
        with self._slow_lock:
            slow = self._slow

        def cluster_record(name, full_name=None):
            # Keep the legacy grouping key separate from the untruncated display source.
            full_name = name if full_name is None else full_name
            return clusters.setdefault(name, dict(name=name, full_name=full_name,
                                                  short_name=(name if name in initiative_names
                                                              else short_name(full_name)),
                                                  run=None, matrix_host=None,
                                                  waiting=0, stalled=0, notes=[], fallbacks=[],
                                                  retired_workers=[]))

        for p in projections:
            matrix = build_matrix(p, resolver)
            matrix.update(run_plan=dict(p.runPlan), packages=p.packages,
                          status_card=dict(p.statusCard))
            matrices[p.run] = matrix
            stages = {row['id']: row['stage'] for row in matrix['rows']}
            for package in p.packages:
                if package['dispatchId']:
                    node_id = resolver.node_for_handle('dispatch:' + package['dispatchId'],
                                                       package['machine'] or 'local')
                    if node_id:
                        bindings[node_id] = (p, stages.get(package['slice'], derive_stage(p)))
            for row in matrix['rows']:
                for node_id in row['live']:
                    bindings[node_id] = (p, row['stage'])
                for gate_id in ('goal', 'design', 'plan', 'delivery'):
                    row['cells'][gate_id]['stale'] = slow['stale'].get(
                        (p.run, p.mtime, row['id'], gate_id))
                for chip in row['cells']['review']['chips']:
                    chip['stale'] = slow['stale'].get((p.run, p.mtime, row['id'], chip['id']))
            if matrix['chief_node']:
                bindings[matrix['chief_node']] = (p, derive_stage(p))
            matrix_host = next((host for host, records in data.items()
                                if any(t['handle'] == p.chiefTerminal
                                       for t in records['terminals'])), 'local')
            cluster_record(p.title).update(run=p.run, matrix_host=matrix_host,
                                           waiting=matrix['waiting'])

        objectives = _run_objectives(data)
        run_by_terminal = {run['coordinator_handle']: run['id'] for run in orca_runs.values()
                           if run.get('coordinator_handle')}
        run_by_terminal.update({w.get('agentTerminalHandle'): w.get('runId')
                                for records in data.values() for w in records['workers']
                                if w.get('agentTerminalHandle') and w.get('runId') in orca_runs})
        for run_id, run in orca_runs.items():
            if run_id not in by_run and run.get('objective'):
                name = cluster_for('', run_objective=run['objective'], title='', purpose=None,
                                   worktree='', branch='', config=config)
                reason = rejected.get(run_id + '.json', 'projection v1, Chief must re-render')
                record = cluster_record(name, full_name=run['objective'])
                record['notes'].append(reason)
                record['fallbacks'].append(dict(run=run_id, now=run['objective'], note=reason))
                if record['run'] not in matrices:
                    record.update(run=run_id, matrix_host=next(
                        (host for host, records in data.items() if run in records['runs']), 'local'))
        for worker in sorted(retired, key=lambda w: (w['host'], w['title'], w['dispatchId'])):
            binding = bindings.get(worker['id'])
            name = cluster_for(
                worker['id'], run_objective=objectives.get(worker['handle']),
                repository=slow['repository'].get(worker['worktree'], (0, None))[1],
                projection_cluster=binding[0].title if binding else None,
                title=worker['title'], purpose='', worktree=worker['worktree'],
                branch=worker['branch'], config=config)
            cluster_record(name)['retired_workers'].append(
                {key: worker[key] for key in ('title', 'dispatchId', 'state', 'retainedFor', 'host')})
        ladders = set()
        by_node = {node['id']: node for node in nodes}
        activity = {}
        for node in nodes:
            node_id = node['id']
            binding = bindings.get(node_id)
            promoted = stage_for(node_id, config)
            pinned = node_id in config.assign or promoted is not None
            objective = objectives.get(node['terminal'])
            projection_cluster = binding[0].title if binding else None
            if node['kind'] == 'subagent':
                parent = by_node[node['parent']]
                for key in ('cluster', 'cluster_source', 'run', 'stage'):
                    node[key] = parent[key]
            elif node['you_at'] is None and node['kind'] == 'claude' and not (
                    binding or pinned or objective):
                node['cluster'] = 'Unsorted'
            else:
                node['repository'] = slow['repository'].get(node['worktree'], (0, None))[1] or ''
                node['cluster'] = cluster_for(
                    node_id, run_objective=objective, repository=node['repository'] or None, projection_cluster=projection_cluster,
                    title=node['title'], purpose=(node['purpose'] if node['kind'] == 'terminal'
                                                 or node['you_at'] is not None else None),
                    worktree=node['worktree'], branch=node['branch'], config=config)
                fields = [str(node[key] or '').casefold()
                          for key in ('title', 'purpose', 'worktree', 'branch')]
                matched = any(pattern.casefold() in value for _, patterns in config.initiatives
                              for pattern in patterns for value in fields)
                node['cluster_source'] = ('run' if binding else 'pin' if pinned else
                                          'run' if objective else 'match' if matched else
                                          'worktree' if node['cluster'] != 'Unsorted' else 'unsorted')
                node['stage'] = binding[1] if binding else promoted
                node['run'] = binding[0].run if binding else run_by_terminal.get(node['terminal'])
                if binding and pinned:
                    node['pin_overridden'] = config.assign.get(node_id)
            node['never_prompted'] = never_prompted(node)
            signature = (node['it_at'], node['transcript_offset'], node['last_output_at'])
            previous = self._activity.get(node_id)
            stamp = previous[1] if previous and previous[0] == signature else now
            activity[node_id] = (signature, stamp)
            node['activity_changed_at'] = stamp
            node['stalled'] = node['kind'] in ('claude', 'terminal') and is_stalled(node, None, now)
            if node['kind'] == 'claude' and node['run'] is None and promoted is None:
                key = (node['worktree'], node['branch'])
                ladders.add(key)
                node['ladder'] = slow['ladders'].get(key)
            record = cluster_record(node['cluster'])
            record['stalled'] += int(node['stalled'])
            run_id = node['run']
            if run_id and run_id not in by_run:
                reason = rejected.get(run_id + '.json', 'projection v1, Chief must re-render')
                if reason not in record['notes']:
                    record['notes'].append(reason)
        self._activity = activity
        for p in projections:
            matrices[p.run]['stalled'] = clusters[p.title]['stalled']

        retired_handles = {w['handle'] for w in retired}
        counts = running_workers({h: [w for w in r['workers']
                                      if w.get('agentTerminalHandle') not in retired_handles]
                                  for h, r in data.items()},
                                 {h: r['terminals'] for h, r in data.items()})
        caps = dict(config.caps)
        # Sorted projection-file order makes overlapping host caps deterministic.
        for p in projections:
            caps.update(p.caps)
        probes = []
        for host in hosts:
            name = host['name']
            key = (name, config.hosts.get(name, {}).get('ssh'))
            if host['reachable']:
                probes.append(key)
            memory = slow['memory'].get(key) if host['reachable'] else None
            memory = memory or {'free_pct': None, 'swap_gb': None}
            count, cap = counts.get(name, 0), caps.get(name)
            amber = ((cap is not None and count > cap) or
                     (memory['free_pct'] is not None and memory['free_pct'] < 40))
            host.update(memory=memory, workers=count, cap=cap, amber=amber)
        with self._slow_lock:
            self._slow_input = (ladders, projections, probes)
        return dict(runs=matrices, clusters=clusters, decisions=decision_strip(projections),
                    rejected_projections=rejected)

    def _poll_host(self, host, sessions):
        env = None if host == 'local' else host
        # Only terminal discovery determines whether this host is reachable.
        records = dict(terminals=self.orca.terminals(env), degraded=[])

        def optional(source, call, fallback, **kwargs):
            try:
                self.orca.remaining_timeout()
                return call(env=env, **kwargs)
            except OrcaError as error:
                records['degraded'].append(f'{source}: {error}')
                return fallback

        for source in ('runs', 'workers', 'inbox'):
            records[source] = list(optional(source, getattr(self.orca, source), []))
        records['tasks'] = []
        for run in records['runs']:
            records['tasks'].extend(optional('tasks', self.orca.tasks, [], run_id=run['id']))
        matches = _match_terminals(sessions, records['terminals']) if host == 'local' else {}
        used = {terminal['handle'] for terminal in matches.values()}
        records['matches'] = matches
        records['screens'] = {}
        return records

    def _poll_screens(self, host, records, workers):
        used = {t['handle'] for t in records['matches'].values()}
        retired = _retired_workers({host: records}, used)
        candidates = [t for t in records['terminals'] if t['handle'] not in used
                      and (host, t['handle']) not in retired
                      and (t.get('agentIdentity') or t['handle'] in workers)]
        candidates.sort(key=lambda t: self._screens.get((host, t['handle']), (0, ''))[0])
        for terminal in candidates:
            handle = terminal['handle']
            key = (host, handle)
            stamp, screen = self._screens.get(key, (0, ''))
            attempted_at, backoff, failure = self._screen_attempts.get(key, (0, 0, None))
            now = time.monotonic()
            if (key not in self._screens or now - stamp >= 30) and now - attempted_at >= backoff:
                try:
                    self.orca.remaining_timeout()
                except OrcaError as error:
                    records['degraded'].append(f'screen: {error}')
                else:
                    # Budget exhaustion before a read is not a terminal failure.
                    # Keep retry timing separate from the last successful data.
                    try:
                        screen = self.orca.screen(handle, env=None if host == 'local' else host)
                    except OrcaError as error:
                        failure = str(error)
                        self._screen_attempts[key] = (now, min(120, max(10, backoff * 2)), failure)
                    else:
                        failure = None
                        self._screen_attempts[key] = (now, 0, None)
                        self._screens[key] = (now, screen)
            if failure is not None:
                records['degraded'].append(f'screen: {failure}')
            records['screens'][handle] = screen

    def snapshot(self) -> dict:
        now = time.time()
        config = load(self.config_path)
        sessions = self.sessions()
        with self._slow_lock:
            slow = dict(self._slow)
        names = list(dict.fromkeys(['local'] + slow['environments'] + list(config.hosts)))
        hosts, data = [], {}
        for name in names:
            entry = slow['hosts'].get(name, {})
            host = dict(name=name, label='This Mac' if name == 'local' else name,
                        reachable=entry.get('reachable', False))
            if 'data' in entry:
                data[name] = entry['data']
                if entry['data']['degraded']:
                    host['degraded'] = list(entry['data']['degraded'])
            else:
                host['degraded'] = entry.get('degraded', ['Orca poll pending'])
                if 'error' in entry:
                    host['error'] = entry['error']
            if name == 'local' and slow['environment_error']:
                host.setdefault('degraded', []).append(slow['environment_error'])
            hosts.append(host)
        tmux = slow['tmux']
        workers = {worker.get('agentTerminalHandle') for records in data.values()
                   for worker in records['workers'] if worker.get('agentTerminalHandle')}
        nodes, subagent_edges, facts_by_node = [], [], {}
        local_matches = _match_terminals(sessions, data.get('local', {}).get('terminals', []))
        git_by_path = slow['git']
        retired = _retired_workers(data, {t['handle'] for t in local_matches.values()})

        def local_git(path):
            return git_by_path.get(path, (0, ('', '')))[1]

        for session in sessions:
            terminal = local_matches.get(session.session_id, {})
            handle = terminal.get('handle')
            node_id = f'local:sid:{session.session_id}'
            facts = self._read(node_id, session.transcript, dispatched=handle in workers)
            facts_by_node[node_id] = facts
            node = _node(node_id, 'local', 'claude', facts)
            worktree = terminal.get('worktreePath') or session.cwd
            root, branch = local_git(worktree)
            tmux_name = next((name for name, record in tmux.items()
                              if name.startswith('neko-') and session.pid in record['panes']), None)
            pane_matched = bool(terminal and session.orca_pane is not None and
                                session.orca_pane == (terminal.get('tabId'), terminal.get('leafId')))
            hosting = ('orca' if pane_matched else 'tmux' if tmux_name else
                       'kitty' if session.kitty_key else 'unknown')
            node.update(title=facts.title or session.name, worktree=root or worktree,
                        branch=terminal.get('branch') or branch,
                        repo=Path(root or session.cwd).name, hosting=hosting,
                        terminal=handle, tmux=tmux_name,
                        last_output_at=terminal.get('lastOutputAt'),
                        kitty_pid=int(session.kitty_key.split('-', 1)[0]) if session.kitty_key else None,
                        kitty_window=int(session.kitty_key.rsplit('-', 1)[1]) if session.kitty_key else None,
                        ctx_pct=session.ctx_pct, cost=session.cost,
                        state=session.hook_state if session.hook_state in ('attention', 'done')
                        else 'working' if session.status == 'busy' else 'idle')
            node.update(subagents_total=len(session.subagents), subagents_shown=0)
            nodes.append(node)
            for agent in session.subagents:
                if now - agent.mtime > SUBAGENT_WINDOW_S:
                    continue
                node['subagents_shown'] += 1
                child_id = f'local:agent:{agent.agent_id}'
                child_facts = self._read(child_id, agent.transcript, dispatched=True)
                facts_by_node[child_id] = child_facts
                child = _node(child_id, 'local', 'subagent', child_facts)
                child.update(parent=node_id, title=child_facts.title or agent.agent_id,
                             state='working' if now - agent.mtime < 120 else 'done')
                for key in ('cluster', 'repo', 'repository', 'worktree', 'branch', 'hosting'):
                    child[key] = node[key]
                nodes.append(child)
                subagent_edges.append(Edge(node_id, child_id, 1, agent.mtime, 'subagent'))

        retired_nodes = []
        for host, records in data.items():
            for terminal in records['terminals']:
                handle = terminal['handle']
                worker = retired.get((host, handle))
                if worker is not None:
                    prefix = 'local' if host == 'local' else f'env:{host}'
                    worktree = terminal.get('worktreePath') or ''
                    root, branch = local_git(worktree) if host == 'local' else ('', '')
                    stamp = terminal.get('lastOutputAt')
                    retired_nodes.append(dict(
                        id=f'{prefix}:term:{handle}', host=host, handle=handle,
                        title=terminal.get('title') or '', worktree=root or worktree,
                        branch=terminal.get('branch') or branch,
                        dispatchId=worker.get('dispatchId') or worker.get('id') or '',
                        state=worker['workerState'],
                        retainedFor=max(0, int(now - stamp)) if stamp and stamp > 0 else None))
                    continue
                if (handle not in records['screens'] or (host == 'local' and
                        any(t['handle'] == handle for t in local_matches.values()))):
                    continue
                prefix = 'local' if host == 'local' else f'env:{host}'
                node = _node(f'{prefix}:term:{handle}', host, 'terminal')
                screen = records['screens'][handle]
                worktree = terminal.get('worktreePath') or ''
                root, branch = local_git(worktree) if host == 'local' else ('', '')
                identity = terminal.get('agentIdentity')
                node.update(title=terminal.get('title') or '', last_said=screen,
                            doing=screen.rstrip().split('\n')[-1][:60],
                            it_at=terminal['lastOutputAt'],
                            last_output_at=terminal['lastOutputAt'],
                            state='working' if now - terminal['lastOutputAt'] < 60 else 'idle',
                            worktree=root or worktree, branch=terminal.get('branch') or branch,
                            repo=Path(root or worktree).name, hosting='orca' if host == 'local' else host,
                            terminal=handle, model=identity.get('model') if isinstance(identity, dict) else None)
                nodes.append(node)

        resolver = Resolver(sessions, {h: r['terminals'] for h, r in data.items()},
                            {h: r['workers'] for h, r in data.items()},
                            {h: r['runs'] for h, r in data.items()})
        # Apply the same verified, unambiguous ownership to edge resolution.
        resolver.terminals['local'] = {t['handle']: f'local:term:{t["handle"]}'
                                       for t in data.get('local', {}).get('terminals', [])}
        for session_id, terminal in local_matches.items():
            resolver.terminals['local'][terminal['handle']] = f'local:sid:{session_id}'
        inbox = {}
        for host, records in data.items():
            inbox[host] = []
            for message in records['inbox']:
                # Inbox IDs are runtime-local, while this cache spans all hosts.
                key = f'{host}:{message["id"]}'
                if message.get('created_at') is None:
                    self.first_seen.setdefault(key, now)
                inbox[host].append(dict(message, id=key))
        edges = build_edges(resolver, facts_by_node, inbox, self.first_seen) + subagent_edges
        visible = {node['id'] for node in nodes}
        additions = self._enrich(nodes, hosts, data, resolver, config, now, retired_nodes)
        with self._slow_lock:
            self._local_input = (list(sessions),
                                 {n['worktree'] for n in nodes if n['host'] == 'local' and n['worktree']}
                                 | {s.cwd for s in sessions if s.cwd}, list(config.hosts))
        return dict(generated_at=now, hosts=hosts, nodes=nodes,
                    edges=[asdict(edge) for edge in edges
                           if edge.src in visible and edge.dst in visible], **additions)

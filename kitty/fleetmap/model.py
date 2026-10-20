from __future__ import annotations

"""Assemble host-qualified fleet nodes and traffic from local and Orca facts."""
from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import threading
import time

import fleet_tmux
from .clusters import CONFIG_PATH, cluster_for, load, stage_for
from .edges import Edge, Resolver, build_edges
from .ladder import Ladder, never_prompted
from .matrix import build_matrix, derive_stage
from .orca import OrcaClient, OrcaError
from .projection import PROGRESS_DIR, load_projections
from .registry import list_local_sessions
from .signals import MemoryProbe, StaleChecker, decision_strip, is_stalled, running_workers
from .transcript import TranscriptFacts, read_transcript


SUBAGENT_WINDOW_S = 3600


def _match_terminals(sessions, terminals):
    """Reserve exact panes before applying a one-to-one cwd fallback."""
    matched = {}
    used = set()
    for session in sessions:
        if session.orca_pane is None:
            continue
        for terminal in terminals:
            handle = terminal['handle']
            if (handle not in used and session.orca_pane ==
                    (terminal.get('tabId'), terminal.get('leafId'))):
                matched[session.session_id] = terminal
                used.add(handle)
                break
    for session in sessions:
        if session.session_id in matched or not session.cwd:
            continue
        for terminal in terminals:
            handle = terminal['handle']
            if handle not in used and session.cwd == terminal.get('worktreePath'):
                matched[session.session_id] = terminal
                used.add(handle)
                break
    return matched


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


def _node(node_id, host, kind, facts=None):
    facts = facts or TranscriptFacts.empty()
    return dict(
        id=node_id, host=host, kind=kind, parent=None, title=facts.title or '',
        purpose=facts.purpose or '', doing=facts.doing or '', last_said=facts.last_said or '',
        state='idle', you_at=facts.you_at, it_at=facts.it_at,
        never_addressed=facts.you_at is None, cluster='Unsorted', repo='', worktree='',
        branch='', hosting='unknown', model=None, ctx_pct=None, cost=None,
        stalled=False, ladder=None, stage=None, cluster_source='unsorted',
        activity_changed_at=None, transcript_offset=facts.offset, last_output_at=None,
        run=None, pin_overridden=None,
        moves=[list(move) for move in facts.moves], terminal=None, tmux=None, kitty_window=None)


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
                 projection_dir=PROGRESS_DIR):
        self.orca = orca if orca is not None else OrcaClient()
        self.config_path = config_path
        self.sessions = sessions
        self.tmux_sessions = tmux_sessions
        self.facts = {}
        self.first_seen = {}
        self._sources = {}
        self.projection_dir = projection_dir
        self.ladder = Ladder()
        self.stale = StaleChecker()
        self.memory = MemoryProbe()
        self._activity = {}
        self._slow_lock = threading.Lock()
        self._slow_input = None
        self._slow = {'ladders': {}, 'memory': {}, 'stale': {}}

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

    def refresh_slow(self):
        """Run only on the probe thread; publish a complete cache without I/O locks."""
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
            self._slow = result

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

    def _enrich(self, nodes, hosts, data, resolver, config, now):
        """Join projections and cheap overlays using the last completed probe pass."""
        projections, rejected = load_projections(self.projection_dir)
        orca_runs = {run['id']: run for records in data.values() for run in records['runs']}
        projections = [p for p in projections if p.run in orca_runs]
        by_run = {p.run: p for p in projections}
        matrices, bindings, clusters = {}, {}, {}
        with self._slow_lock:
            slow = self._slow

        def cluster_record(name):
            return clusters.setdefault(name, dict(name=name, run=None, matrix_host=None,
                                                  waiting=0, stalled=0, notes=[]))

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
                cluster_record(name)['notes'].append(
                    rejected.get(run_id + '.json', 'projection v1, Chief must re-render'))
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
                node['cluster'] = cluster_for(
                    node_id, run_objective=objective, projection_cluster=projection_cluster,
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

        counts = running_workers({h: r['workers'] for h, r in data.items()},
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

    def _poll_screens(self, data):
        workers = {w.get('agentTerminalHandle') for records in data.values()
                   for w in records['workers']}
        for host, records in data.items():
            used = {t['handle'] for t in records['matches'].values()}
            for terminal in records['terminals']:
                handle = terminal['handle']
                if handle in used or not (terminal.get('agentIdentity') or handle in workers):
                    continue
                try:
                    screen = self.orca.screen(handle, env=None if host == 'local' else host)
                except OrcaError as error:
                    records['degraded'].append(f'screen: {error}')
                    screen = ''
                records['screens'][handle] = screen

    def snapshot(self) -> dict:
        now = time.time()
        config = load(self.config_path)
        hosts = [dict(name='local', label='This Mac', reachable=True)]
        data = {}
        try:
            environments = self.orca.environments()
        except OrcaError as error:
            hosts[0]['degraded'] = [f'environments: {error}']
            environments = []
        for name in dict.fromkeys(environments):
            if name != 'local':
                hosts.append(dict(name=name, label=name, reachable=True))
        sessions = self.sessions()
        for host in hosts:
            try:
                data[host['name']] = self._poll_host(host['name'], sessions)
            except OrcaError as error:
                host.update(reachable=False, error=str(error))
                host.setdefault('degraded', []).append(f'terminals: {error}')
        # Unscoped worker-list inherits the launcher's run. A run and its
        # dispatch records can live on different runtimes, so query every known
        # run on each reachable host before resolving package dispatch IDs.
        run_ids = dict.fromkeys(run['id'] for records in data.values() for run in records['runs'])
        for name, records in data.items():
            for run_id in run_ids:
                try:
                    records['workers'].extend(self.orca.workers(
                        env=None if name == 'local' else name, run_id=run_id))
                except OrcaError as error:
                    records['degraded'].append(f'workers: {error}')
        self._poll_screens(data)
        for host in hosts:
            degraded = data.get(host['name'], {}).get('degraded', [])
            if degraded:
                host.setdefault('degraded', []).extend(degraded)
        tmux = self.tmux_sessions() if sessions else {}
        workers = {worker.get('agentTerminalHandle') for records in data.values()
                   for worker in records['workers'] if worker.get('agentTerminalHandle')}
        nodes, subagent_edges, facts_by_node = [], [], {}
        local_matches = data.get('local', {}).get('matches', {})
        git_by_path = {}

        def local_git(path):
            if path not in git_by_path:
                git_by_path[path] = _git_metadata(path)
            return git_by_path[path]

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
                       'kitty' if session.kitty_key else 'orca' if terminal else 'unknown')
            node.update(title=facts.title or session.name, worktree=root or worktree,
                        branch=terminal.get('branch') or branch,
                        repo=Path(root or session.cwd).name, hosting=hosting,
                        terminal=handle, tmux=tmux_name,
                        last_output_at=terminal.get('lastOutputAt'),
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
                for key in ('cluster', 'repo', 'worktree', 'branch', 'hosting'):
                    child[key] = node[key]
                nodes.append(child)
                subagent_edges.append(Edge(node_id, child_id, 1, agent.mtime, 'subagent'))

        for host, records in data.items():
            for terminal in records['terminals']:
                handle = terminal['handle']
                if handle not in records['screens']:
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
        # Resolver knows exact panes; teach it the assembler's cwd fallback too.
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
        additions = self._enrich(nodes, hosts, data, resolver, config, now)
        return dict(generated_at=now, hosts=hosts, nodes=nodes,
                    edges=[asdict(edge) for edge in edges
                           if edge.src in visible and edge.dst in visible], **additions)

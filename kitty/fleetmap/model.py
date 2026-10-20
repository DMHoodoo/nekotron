from __future__ import annotations

"""Assemble host-qualified fleet nodes and traffic from local and Orca facts."""
from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import time

import fleet_tmux
from .clusters import CONFIG_PATH, cluster_for, load
from .edges import Edge, Resolver, build_edges
from .orca import OrcaClient, OrcaError
from .registry import list_local_sessions
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
                 sessions=list_local_sessions, tmux_sessions=fleet_tmux.sessions):
        self.orca = orca if orca is not None else OrcaClient()
        self.config_path = config_path
        self.sessions = sessions
        self.tmux_sessions = tmux_sessions
        self.facts = {}
        self.first_seen = {}
        self._sources = {}

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
            records[source] = optional(source, getattr(self.orca, source), [])
        records['tasks'] = []
        for run in records['runs']:
            records['tasks'].extend(optional('tasks', self.orca.tasks, [], run_id=run['id']))
        matches = _match_terminals(sessions, records['terminals']) if host == 'local' else {}
        used = {terminal['handle'] for terminal in matches.values()}
        records['matches'] = matches
        records['screens'] = {
            terminal['handle']: optional('screen', self.orca.screen, '', handle=terminal['handle'])
            for terminal in records['terminals'] if terminal['handle'] not in used
            and (host != 'local' or terminal.get('agentIdentity'))}
        return records

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
            else:
                degraded = data[host['name']]['degraded']
                if degraded:
                    host.setdefault('degraded', []).extend(degraded)
        if 'local' not in data:
            sessions = []
        tmux = self.tmux_sessions() if sessions else {}
        workers = {worker.get('agentTerminalHandle') for records in data.values()
                   for worker in records['workers'] if worker.get('agentTerminalHandle')}
        objectives = _run_objectives(data)
        nodes, subagent_edges, facts_by_node = [], [], {}
        local_matches = data.get('local', {}).get('matches', {})
        git_by_path = {}

        def cluster(node):
            return cluster_for(node['id'], run_objective=objectives.get(node['terminal']),
                               title=node['title'], purpose=node['purpose'],
                               worktree=node['worktree'], branch=node['branch'], config=config)

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
                        kitty_window=int(session.kitty_key.rsplit('-', 1)[1]) if session.kitty_key else None,
                        ctx_pct=session.ctx_pct, cost=session.cost,
                        state=session.hook_state if session.hook_state in ('attention', 'done')
                        else 'working' if session.status == 'busy' else 'idle')
            # Dispatch prompts provide purpose, but only human messages enable
            # inferred clustering; explicit pins and run bindings still apply.
            unaddressed_unbound = (facts.you_at is None and node_id not in config.assign
                                  and not objectives.get(handle))
            node['cluster'] = 'Unsorted' if unaddressed_unbound else cluster(node)
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
                            state='working' if now - terminal['lastOutputAt'] < 60 else 'idle',
                            worktree=root or worktree, branch=terminal.get('branch') or branch,
                            repo=Path(root or worktree).name, hosting='orca' if host == 'local' else host,
                            terminal=handle, model=identity.get('model') if isinstance(identity, dict) else None)
                node['cluster'] = cluster(node)
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
        return dict(generated_at=now, hosts=hosts, nodes=nodes,
                    edges=[asdict(edge) for edge in edges
                           if edge.src in visible and edge.dst in visible])

"""Resolve traffic endpoints and combine directed fleet map edges."""
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from .registry import LocalSession
from .transcript import TranscriptFacts


@dataclass
class Edge:
    src: str
    dst: str
    count: int
    newest: float
    kind: str  # message | dispatch | subagent


class Resolver:
    def __init__(self, sessions: list[LocalSession],
                 terminals_by_host: dict[str, list[dict]],
                 workers_by_host: dict[str, list[dict]],
                 runs_by_host: dict[str, list[dict]]):
        self.names = {s.name: f'local:sid:{s.session_id}' for s in sessions if s.name}
        self.agents = {a.agent_id: f'local:agent:{a.agent_id}'
                       for s in sessions for a in s.subagents}
        self.pids = {s.pid: f'local:sid:{s.session_id}' for s in sessions}
        panes = {s.orca_pane: f'local:sid:{s.session_id}'
                 for s in sessions if s.orca_pane is not None}
        self.terminals = {}
        for host, terminals in terminals_by_host.items():
            self.terminals[host] = {}
            for terminal in terminals:
                handle = terminal.get('handle')
                if not handle:
                    continue
                pane = (terminal.get('tabId'), terminal.get('leafId'))
                node = panes.get(pane) if host == 'local' else None
                self.terminals[host][handle] = node or self._terminal_node(handle, host)
        self.workers = {host: {w['dispatchId']: w.get('agentTerminalHandle')
                               for w in workers if w.get('dispatchId')}
                        for host, workers in workers_by_host.items()}
        self.runs = {host: {r['id']: r.get('coordinator_handle')
                            for r in runs if r.get('id')}
                     for host, runs in runs_by_host.items()}

    def node_for_name(self, name: str) -> str | None:
        name = re.sub(r' \[[^\[\]]+\]$', '', name)
        return self.names.get(name) or self.agents.get(name)

    def node_for_socket(self, uri: str) -> str | None:
        match = re.fullmatch(r'uds:/tmp/cc-socks/([0-9]+)\.sock', uri)
        return self.pids.get(int(match[1])) if match else None

    @staticmethod
    def _terminal_node(handle, host):
        prefix = 'local' if host == 'local' else f'env:{host}'
        return f'{prefix}:term:{handle}'

    @staticmethod
    def _lookup(records, key, host):
        # Prefer the inbox's runtime; orchestration can reference another host.
        if key in records.get(host, {}):
            return records[host][key]
        return next((items[key] for items in records.values() if key in items), None)

    def node_for_handle(self, handle: str, host: str) -> str | None:
        if not isinstance(handle, str):
            return None
        if handle.startswith('dispatch:'):
            handle = self._lookup(self.workers, handle[len('dispatch:'):], host)
        elif handle.startswith('run:'):
            handle = self._lookup(self.runs, handle[len('run:'):], host)
        if not isinstance(handle, str) or not handle.startswith('term_'):
            return None
        return (self._lookup(self.terminals, handle, host)
                or self._terminal_node(handle, host))


def _created_at(value):
    if isinstance(value, (int, float)):
        return float(value)
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.timestamp()


def build_edges(resolver: Resolver, facts_by_node: dict[str, TranscriptFacts],
                inbox_by_host: dict[str, list[dict]],
                first_seen: dict[str, float]) -> list[Edge]:
    """Sum observations by directed pair; orchestration marks a pair dispatch.

    Parent/subagent links belong to the assembler. The caller owns first_seen
    and supplies an entry for each inbox message lacking created_at.
    """
    edges = {}

    def add(src, dst, newest, kind):
        if src is None or dst is None:
            return
        key = (src, dst)
        if key not in edges:
            edges[key] = Edge(src, dst, 1, newest, kind)
        else:
            edge = edges[key]
            edge.count += 1
            edge.newest = max(edge.newest, newest)
            if kind == 'dispatch':
                edge.kind = kind

    for node, facts in facts_by_node.items():
        for epoch, target in facts.outbound:
            add(node, resolver.node_for_name(target), epoch, 'message')
        for epoch, source in facts.inbound:
            add(resolver.node_for_socket(source), node, epoch, 'message')
    for host, messages in inbox_by_host.items():
        for message in messages:
            src = resolver.node_for_handle(message.get('from_handle'), host)
            dst = resolver.node_for_handle(message.get('to_handle'), host)
            if src is None or dst is None:
                continue
            created = message.get('created_at')
            newest = first_seen[message['id']] if created is None else _created_at(created)
            add(src, dst, newest, 'dispatch')
    return list(edges.values())

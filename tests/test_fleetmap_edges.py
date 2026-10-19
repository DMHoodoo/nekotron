from __future__ import annotations

"""Traffic resolution using real session facts and plain Orca records."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.edges import Edge, Resolver, build_edges
from fleetmap.registry import LocalSession, Subagent
from fleetmap.transcript import TranscriptFacts


def sess(sid, name, pid=1, orca_pane=None, subagents=None):
    return LocalSession(
        pid=pid, session_id=sid, name=name, cwd='/work', status='idle',
        started_at=0, status_updated_at=0, transcript=None, orca_pane=orca_pane,
        hook_state=None, kitty_key=None, ctx_pct=None, cost=None,
        subagents=subagents or [])


class TrafficEdges(unittest.TestCase):
    def resolver(self, sessions=None, terminals=None, workers=None, runs=None):
        return Resolver(sessions or [], terminals or {}, workers or {}, runs or {})

    def test_outbound_send_message_resolves_registry_name_with_ref(self):
        r = self.resolver(sessions=[sess('s1', 'Handoff Project'),
                                    sess('s2', 'PR Review', pid=2)])
        self.assertEqual(r.node_for_name('PR Review [5da3ab]'), 'local:sid:s2')

    def test_names_resolve_before_subagent_ids(self):
        r = self.resolver(sessions=[sess('s1', 'Chief', subagents=[
            Subagent('agent_a', '/unused', 0), Subagent('Review', '/unused', 0)]),
            sess('s2', 'Review', pid=2)])
        self.assertEqual(r.node_for_name('agent_a'), 'local:agent:agent_a')
        self.assertEqual(r.node_for_name('Review'), 'local:sid:s2')
        self.assertIsNone(r.node_for_name('missing'))

    def test_inbound_socket_resolves_pid(self):
        r = self.resolver(sessions=[sess('s2', 'PR Review', pid=19452)])
        self.assertEqual(r.node_for_socket('uds:/tmp/cc-socks/19452.sock'),
                         'local:sid:s2')
        for uri in ('uds:/tmp/cc-socks/999.sock', '/tmp/cc-socks/19452.sock',
                    'uds:/elsewhere/19452.sock', 'uds:/tmp/cc-socks/x.sock'):
            with self.subTest(uri=uri):
                self.assertIsNone(r.node_for_socket(uri))

    def test_dispatch_handle_resolves_through_workers_to_pane(self):
        r = self.resolver(
            sessions=[sess('s1', 'Chief', orca_pane=('tab', 'leaf'))],
            terminals={'local': [{'handle': 'term_a', 'tabId': 'tab', 'leafId': 'leaf'}]},
            workers={'local': [{'dispatchId': 'ctx_1', 'agentTerminalHandle': 'term_a'}]})
        self.assertEqual(r.node_for_handle('dispatch:ctx_1', 'local'), 'local:sid:s1')

    def test_remote_terminal_handle_becomes_env_node(self):
        r = self.resolver(
            sessions=[sess('s1', 'Chief', orca_pane=('t', 'l'))],
            terminals={'laptop2': [{'handle': 'term_z', 'tabId': 't', 'leafId': 'l'}]})
        self.assertEqual(r.node_for_handle('term_z', 'laptop2'),
                         'env:laptop2:term:term_z')

    def test_bare_terminal_without_registry_session(self):
        r = self.resolver()
        self.assertEqual(r.node_for_handle('term_a', 'local'), 'local:term:term_a')

    def test_run_handle_resolves_coordinator(self):
        r = self.resolver(runs={'local': [{'id': 'run_1', 'coordinator_handle': 'term_a'}]})
        self.assertEqual(r.node_for_handle('run:run_1', 'local'), 'local:term:term_a')

    def test_missing_dispatch_run_or_terminal_handle_is_unresolved(self):
        r = self.resolver(workers={'local': [{'dispatchId': 'ctx_1'}]},
                          runs={'local': [{'id': 'run_1'}]})
        for handle in ('dispatch:ctx_1', 'dispatch:missing', 'run:run_1',
                       'run:missing', 'unknown', '', None):
            with self.subTest(handle=handle):
                self.assertIsNone(r.node_for_handle(handle, 'local'))

    def test_edges_merge_and_keep_newest(self):
        r = self.resolver(sessions=[sess('s1', 'Chief'), sess('s2', 'PR Review', pid=2)])
        facts = {'local:sid:s1': TranscriptFacts(outbound=[
            (200.0, 'PR Review'), (100.0, 'PR Review')])}
        self.assertEqual(build_edges(r, facts, {}, {}), [
            Edge('local:sid:s1', 'local:sid:s2', 2, 200.0, 'message')])

    def test_inbound_edges_point_from_sender_to_receiver_and_merge(self):
        r = self.resolver(sessions=[sess('s1', 'Chief'), sess('s2', 'Review', pid=2)])
        facts = {
            'local:sid:s1': TranscriptFacts(outbound=[(100.0, 'Review')]),
            'local:sid:s2': TranscriptFacts(inbound=[(150.0, 'uds:/tmp/cc-socks/1.sock')],
                                            outbound=[(200.0, 'Chief')])}
        self.assertCountEqual(build_edges(r, facts, {}, {}), [
            Edge('local:sid:s1', 'local:sid:s2', 2, 150.0, 'message'),
            Edge('local:sid:s2', 'local:sid:s1', 1, 200.0, 'message')])

    def test_dispatch_to_run_resolves_worker_to_coordinator_across_hosts(self):
        r = self.resolver(
            sessions=[sess('chief', 'Chief', orca_pane=('t', 'l'))],
            terminals={'local': [{'handle': 'term_c', 'tabId': 't', 'leafId': 'l'}],
                       'laptop2': [{'handle': 'term_w', 'tabId': 'wt', 'leafId': 'wl'}]},
            workers={'local': [{'dispatchId': 'ctx_1', 'agentTerminalHandle': 'term_w',
                                'host': 'local'}]},
            runs={'local': [{'id': 'run_1', 'coordinator_handle': 'term_c'}]})
        inbox = {'local': [{'id': 'm1', 'from_handle': 'dispatch:ctx_1',
                            'to_handle': 'run:run_1', 'created_at': 300.0}]}
        self.assertEqual(build_edges(r, {}, inbox, {}), [
            Edge('env:laptop2:term:term_w', 'local:sid:chief', 1, 300.0, 'dispatch')])

    def test_inbox_without_timestamp_uses_stable_first_seen(self):
        inbox = {'laptop2': [{'id': 'm1', 'from_handle': 'term_a', 'to_handle': 'term_b'}]}
        first_seen = {'m1': 123.0}
        expected = [Edge('env:laptop2:term:term_a', 'env:laptop2:term:term_b',
                         1, 123.0, 'dispatch')]
        r = self.resolver()
        self.assertEqual(build_edges(r, {}, inbox, first_seen), expected)
        self.assertEqual(build_edges(r, {}, inbox, first_seen), expected)
        self.assertEqual(first_seen, {'m1': 123.0})

    def test_inbox_iso_timestamp_and_epoch_zero(self):
        inbox = {'local': [
            {'id': 'm1', 'from_handle': 'term_a', 'to_handle': 'term_b',
             'created_at': '1970-01-01T00:01:00Z'},
            {'id': 'm2', 'from_handle': 'term_b', 'to_handle': 'term_a', 'created_at': 0}]}
        self.assertEqual(build_edges(self.resolver(), {}, inbox, {'m2': 999}), [
            Edge('local:term:term_a', 'local:term:term_b', 1, 60.0, 'dispatch'),
            Edge('local:term:term_b', 'local:term:term_a', 1, 0.0, 'dispatch')])

    def test_unresolved_messages_are_dropped_and_subagent_links_are_not_generated(self):
        r = self.resolver(sessions=[sess('s1', 'Chief', subagents=[
            Subagent('agent_a', '/unused', 0)])])
        facts = {'local:sid:s1': TranscriptFacts(outbound=[(1.0, 'missing')],
                                                inbound=[(2.0, 'uds:/tmp/cc-socks/99.sock')])}
        inbox = {'local': [{'id': 'm1', 'from_handle': 'dispatch:missing', 'to_handle': 'term_a'},
                            {'id': 'm2', 'from_handle': 'term_a', 'to_handle': 'run:missing'}]}
        self.assertEqual(build_edges(r, facts, inbox, {}), [])

    def test_transcript_and_inbox_edges_merge_by_endpoints(self):
        r = self.resolver(
            sessions=[sess('s1', 'Chief', orca_pane=('t', 'l')),
                      sess('s2', 'Review', pid=2, orca_pane=('t', 'r'))],
            terminals={'local': [{'handle': 'term_a', 'tabId': 't', 'leafId': 'l'},
                                 {'handle': 'term_b', 'tabId': 't', 'leafId': 'r'}]})
        facts = {'local:sid:s1': TranscriptFacts(outbound=[(300.0, 'Review')])}
        inbox = {'local': [{'id': 'm1', 'from_handle': 'term_a', 'to_handle': 'term_b',
                            'created_at': 100.0}]}
        self.assertEqual(build_edges(r, facts, inbox, {}), [
            Edge('local:sid:s1', 'local:sid:s2', 2, 300.0, 'dispatch')])


if __name__ == '__main__':
    unittest.main()

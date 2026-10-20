from __future__ import annotations

"""Exercise the fleet map over loopback without live collectors or terminals."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.actions import ActionError, Actions
from fleetmap.clusters import load, stage_for
from fleetmap import clusters
from fleetmap import server


NODE = {'kind': 'claude', 'cluster': 'Review', 'id': 'local:sid:s1', 'host': 'local', 'hosting': 'orca', 'terminal': 'term_one'}


class StubCollector:
    def __init__(self, config_path):
        self.config_path = config_path
        self.value = {'nodes': [NODE], 'edges': [], 'generated_at': 123}
        self.error = None
        self.attempted = threading.Event()
        self.block = threading.Event()
        self.block.set()

    def snapshot(self):
        self.attempted.set()
        self.block.wait(2)
        if self.error:
            raise self.error
        return self.value


class StubActions:
    def __init__(self):
        self.calls = []

    def peek(self, node):
        self.calls.append(('peek', node))
        return 'screen café\n'

    def jump(self, node):
        self.calls.append(('jump', node))

    def send(self, node, text):
        self.calls.append(('send', node, text))

    def close(self, node):
        self.calls.append(('close', node))
        raise ActionError('terminal_not_found')

    def broadcast(self, nodes, text):
        return Actions.broadcast(self, nodes, text)

    def open_plan(self, path):
        self.calls.append(('open_plan', path))

    def describe_close(self, node):
        self.calls.append(('describe_close', node))
        return 'Close Orca terminal term_one on local.'


class FleetMapHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fleetmap-server-')
        self.base = Path(self.tmp.name)
        self.info = self.base / 'fleet-map.server.json'
        self.page = self.base / 'page.html'
        self.page.write_text('<!doctype html><title>Fleet café</title>', encoding='utf-8')
        self.collector = StubCollector(self.base / 'fleet-map.json')
        self.actions = StubActions()
        self.info_patch = patch.object(server, 'SERVER_INFO', self.info)
        self.info_patch.start()
        self.running = []
        self.start_server()

    def tearDown(self):
        self.collector.block.set()
        for instance, thread in self.running:
            instance.stop()
            thread.join(2)
            self.assertFalse(thread.is_alive(), 'serve_forever did not stop')
        self.info_patch.stop()
        self.tmp.cleanup()

    def start_server(self, **options):
        self.instance = server.FleetMapServer(self.collector, self.actions,
                                              page_path=self.page, **options)
        self.port, self.key = self.instance.start()
        self.url = f'http://127.0.0.1:{self.port}'
        self.thread = threading.Thread(target=self.instance.serve_forever, daemon=True)
        self.running.append((self.instance, self.thread))
        self.thread.start()

    def request(self, path, *, body=None, key=True, headers=None, method=None):
        if key:
            path += ('&' if '?' in path else '?') + urlencode({'key': self.key})
        data = json.dumps(body).encode() if body is not None else None
        req = Request(self.url + path, data=data, headers=headers or {}, method=method)
        return urlopen(req, timeout=1)

    def json_request(self, path, **options):
        with self.request(path, **options) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def wait_for_snapshot(self, generated_at=123):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            value = self.json_request('/api/state')
            if value.get('generated_at') == generated_at:
                return value
            time.sleep(0.01)
        self.fail('snapshot was not published')

    def test_requests_without_key_are_403(self):
        for path, body in [('/', None), ('/api/state', None),
                           ('/api/confirm?node=local:sid:s1', None),
                           ('/api/action', {'node': NODE['id'], 'action': 'close'}),
                           ('/api/assign', {'node': NODE['id'], 'initiative': 'Pin'}),
                           ('/api/promote', {}), ('/api/move', {}),
                           ('/api/broadcast', {}), ('/api/open-plan', {}),
                           ('/missing', None)]:
            for query in ('', '?key=wrong'):
                with self.subTest(path=path, query=query):
                    with self.assertRaises(HTTPError) as caught:
                        self.request(path + query, body=body, key=False)
                    self.assertEqual(caught.exception.code, 403)
                    caught.exception.close()
        self.assertEqual(self.actions.calls, [])
        self.assertFalse(self.collector.config_path.exists())

    def test_unsupported_method_still_requires_key(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('/', method='DELETE', key=False)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_state_serves_latest_snapshot(self):
        value = self.wait_for_snapshot()
        self.assertEqual(value['nodes'], [NODE])
        self.assertEqual(value['poll_seconds'], 3)
        self.assertNotIn('poll_seconds', self.collector.value)

    def test_page_and_header_authentication(self):
        with self.request('/', key=False, headers={'X-Fleet-Key': self.key}) as response:
            self.assertEqual(response.headers.get_content_type(), 'text/html')
            self.assertEqual(response.read(), self.page.read_bytes())
        self.assertIn('nodes', self.json_request('/api/state', key=False,
                                                headers={'X-Fleet-Key': self.key}))

    def test_action_routes_and_reports_error(self):
        self.wait_for_snapshot()
        for action, output in [('peek', 'screen café\n'), ('jump', ''), ('send', '')]:
            with self.subTest(action=action):
                self.assertEqual(self.json_request('/api/action', body={
                    'node': NODE['id'], 'action': action, 'text': 'hello café'}),
                    {'ok': True, 'output': output})
        token = self.json_request('/api/confirm?node=' + NODE['id'])['token']
        self.assertEqual(self.json_request('/api/action', body={
            'node': NODE['id'], 'action': 'close', 'token': token}),
            {'ok': False, 'error': 'terminal_not_found'})
        self.assertEqual(self.actions.calls, [
            ('peek', NODE), ('jump', NODE), ('send', NODE, 'hello café'), ('describe_close', NODE), ('close', NODE)])

    def test_invalid_actions_and_nodes_do_not_call_actions(self):
        self.wait_for_snapshot()
        for body in ({'node': 'missing', 'action': 'close'},
                     {'node': NODE['id'], 'action': 'describe_close'},
                     {'node': NODE['id'], 'action': '__init__'},
                     {'node': NODE['id'], 'action': 'send', 'text': 7}, {}, []):
            with self.subTest(body=body):
                response = self.json_request('/api/action', body=body)
                self.assertFalse(response['ok'])
                self.assertIsInstance(response['error'], str)
        self.assertEqual(self.actions.calls, [])

    def test_malformed_json_reports_failure(self):
        request = Request(self.url + '/api/action?key=' + self.key, data=b'{oops')
        with urlopen(request, timeout=1) as response:
            self.assertEqual(response.status, 200)
            self.assertFalse(json.load(response)['ok'])

    def test_confirm_uses_latest_node(self):
        self.wait_for_snapshot()
        confirmation = self.json_request('/api/confirm?' + urlencode({'node': NODE['id']}))
        self.assertEqual(confirmation['text'], 'Close Orca terminal term_one on local.')
        self.assertTrue(confirmation['token'])
        self.assertEqual(self.actions.calls, [('describe_close', NODE)])

    def test_close_rejects_changed_unknown_expired_and_cross_node_tokens(self):
        self.wait_for_snapshot()
        for change in ({'terminal': 'term_different'}, {'host': 'laptop2'}, {'hosting': 'unknown'},
                       {'hosting': 'tmux', 'tmux': 'neko-other'}):
            token = self.json_request('/api/confirm?node=' + NODE['id'])['token']
            with self.instance._lock:
                self.instance._snapshot = dict(self.instance._snapshot, nodes=[dict(NODE, **change)])
            result = self.json_request('/api/action', body={
                'node': NODE['id'], 'action': 'close', 'token': token})
            self.assertEqual(result, {'ok': False, 'error': 'destination changed, confirm again'})
            with self.instance._lock:
                self.instance._snapshot = dict(self.instance._snapshot, nodes=[NODE])
        for token in (None, 'unknown', []):
            self.assertFalse(self.json_request('/api/action', body={
                'node': NODE['id'], 'action': 'close', 'token': token})['ok'])
        token = self.json_request('/api/confirm?node=' + NODE['id'])['token']
        stamp, destination = self.instance._confirmations[token]
        self.instance._confirmations[token] = (stamp - 301, destination)
        self.assertFalse(self.json_request('/api/action', body={
            'node': NODE['id'], 'action': 'close', 'token': token})['ok'])
        other = dict(NODE, id='local:sid:other')
        token = self.json_request('/api/confirm?node=' + NODE['id'])['token']
        with self.instance._lock:
            self.instance._snapshot = dict(self.instance._snapshot, nodes=[NODE, other])
        self.assertFalse(self.json_request('/api/action', body={
            'node': other['id'], 'action': 'close', 'token': token})['ok'])
        self.assertFalse([call for call in self.actions.calls if call[0] == 'close'])

    def test_each_batch_target_requires_its_own_unchanged_confirmation(self):
        self.wait_for_snapshot()
        other = dict(NODE, id='local:sid:other', terminal='term_two')
        with self.instance._lock:
            self.instance._snapshot = dict(self.instance._snapshot, nodes=[NODE, other])
        tokens = [self.json_request('/api/confirm?node=' + n['id'])['token'] for n in (NODE, other)]
        with self.instance._lock:
            self.instance._snapshot = dict(self.instance._snapshot,
                                           nodes=[NODE, dict(other, terminal='term_changed')])
        with patch.object(self.actions, 'close', return_value=None) as close:
            results = [self.json_request('/api/action', body={
                'node': n['id'], 'action': 'close', 'token': token})
                for n, token in zip((NODE, other), tokens)]
        self.assertEqual([result['ok'] for result in results], [True, False])
        close.assert_called_once_with(NODE)
        self.assertFalse(self.json_request('/api/action', body={
            'node': NODE['id'], 'action': 'close', 'token': tokens[0]})['ok'])

    def test_promote_and_move_update_pin_and_stage(self):
        self.wait_for_snapshot()
        self.assertEqual(self.json_request('/api/promote', body={
            'node': NODE['id'], 'project': 'Core lint', 'slice': 'Cause', 'stage': 'review'}),
            {'ok': True})
        config = load(self.collector.config_path)
        self.assertEqual((config.assign[NODE['id']], stage_for(NODE['id'], config)),
                         ('Core lint', 'review'))
        self.assertEqual(self.json_request('/api/move', body={
            'node': NODE['id'], 'cluster': 'Commissions'}), {'ok': True})
        config = load(self.collector.config_path)
        self.assertEqual(config.assign[NODE['id']], 'Commissions')
        self.assertIsNone(stage_for(NODE['id'], config))

    def test_stage_edit_preserves_multi_session_slice_after_revisit(self):
        other = dict(NODE, id='local:sid:s2', title='Partner')
        self.collector.value['nodes'] = [dict(NODE, title='Audit'), other]
        self.wait_for_snapshot()
        for node in (NODE, other):
            self.assertTrue(self.json_request('/api/promote', body={
                'node': node['id'], 'project': 'Core', 'slice': 'Root cause',
                'stage': 'design'})['ok'])
        # Revisit via snapshots, then update only stage using the selected node.
        self.json_request('/api/state')
        self.json_request('/api/state')
        before = json.loads(self.collector.config_path.read_text())
        self.assertEqual(self.json_request('/api/stage', body={
            'node': NODE['id'], 'stage': 'review'}), {'ok': True})
        after = json.loads(self.collector.config_path.read_text())
        before['projects'][0]['slices'][0]['stage'] = 'review'
        self.assertEqual(after, before)
        self.assertEqual(stage_for(other['id'], load(self.collector.config_path)), 'review')

    def test_stage_edit_never_creates_missing_membership(self):
        self.wait_for_snapshot()
        self.assertFalse(self.json_request('/api/stage', body={
            'node': NODE['id'], 'stage': 'review'})['ok'])
        self.assertFalse(self.collector.config_path.exists())
        self.assertFalse(self.json_request('/api/stage', body={
            'node': NODE['id'], 'stage': 'invalid'})['ok'])

    def test_promote_move_and_assign_share_one_write_lock(self):
        other = dict(NODE, id='local:sid:s2')
        self.collector.value['nodes'] = [NODE, other]
        self.wait_for_snapshot()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original_replace = os.replace
        results = []
        def delayed_replace(source, destination):
            if not entered.is_set():
                entered.set()
                release.wait(1)
            original_replace(source, destination)
        def promote_request():
            results.append(self.json_request('/api/promote', body={
                'node': NODE['id'], 'project': 'P', 'slice': 'S', 'stage': 'review'}))
        def other_requests():
            results.append(self.json_request('/api/move', body={'node': other['id'], 'cluster': 'Moved'}))
            results.append(self.json_request('/api/assign', body={'node': 'third', 'initiative': 'Pinned'}))
            finished.set()
        with patch.object(clusters.os, 'replace', side_effect=delayed_replace):
            first = threading.Thread(target=promote_request)
            second = threading.Thread(target=other_requests)
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
            self.assertFalse(finished.wait(0.1))
            release.set()
            first.join(2)
            second.join(2)
        self.assertEqual(results, [{'ok': True}] * 3)
        self.assertEqual(load(self.collector.config_path).assign,
                         {NODE['id']: 'P', other['id']: 'Moved', 'local:sid:third': 'Pinned'})

    def test_broadcast_excludes_terminals_and_subagents_by_default(self):
        nodes = [NODE, dict(NODE, id='terminal', kind='terminal'),
                 dict(NODE, id='child', kind='subagent'), dict(NODE, id='other', cluster='Other')]
        self.collector.value['nodes'] = nodes
        self.wait_for_snapshot()
        for include, expected in [(False, nodes[:1]), (True, nodes[:2])]:
            result = self.json_request('/api/broadcast', body={
                'cluster': 'Review', 'text': 'hello', **({'include_terminals': True} if include else {})})
            self.assertEqual(result, {'ok': True, 'results': [
                {'node': n['id'], 'ok': True, 'error': None} for n in expected]})
        self.assertEqual([call[1]['id'] for call in self.actions.calls],
                         [NODE['id'], NODE['id'], 'terminal'])

    def test_open_plan_resolves_run_from_snapshot(self):
        self.collector.value['runs'] = {'r1': {'run_plan': {
            'worktree': '/work/a tree', 'path': 'docs/plan.md'}}}
        self.wait_for_snapshot()
        self.assertEqual(self.json_request('/api/open-plan', body={'run': 'r1'}), {'ok': True})
        self.assertEqual(self.actions.calls, [('open_plan', '/work/a tree/docs/plan.md')])
        self.assertFalse(self.json_request('/api/open-plan', body={'run': 'missing'})['ok'])

    def test_invalid_new_route_payloads_have_no_side_effects(self):
        self.wait_for_snapshot()
        for route, body in [('promote', {'node': NODE['id'], 'project': 'P', 'slice': 'S', 'stage': 'bad'}),
                            ('move', {'node': NODE['id'], 'cluster': []}),
                            ('broadcast', {'cluster': 'Review', 'text': 2}),
                            ('broadcast', {'cluster': 'Review', 'text': 'x', 'include_terminals': 'yes'}),
                            ('open-plan', {'run': []})]:
            self.assertFalse(self.json_request('/api/' + route, body=body)['ok'])
        self.assertFalse(self.collector.config_path.exists())
        self.assertEqual(self.actions.calls, [])

    def test_blocked_slow_probes_do_not_delay_snapshot_refresh(self):
        self.instance.stop()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def slow():
            entered.set()
            release.wait(2)
        self.collector.refresh_slow = slow
        self.start_server(poll_seconds=0.02)
        self.assertTrue(entered.wait(1))
        self.collector.value = dict(self.collector.value, generated_at=456)
        self.wait_for_snapshot(456)
        self.assertFalse(release.is_set())
        release.set()

    def test_assign_writes_config(self):
        self.collector.config_path.write_text(json.dumps({'future': 42, 'assign': {'other': 'Keep'}}))
        self.assertEqual(self.json_request('/api/assign', body={
            'node': NODE['id'], 'initiative': 'Commissions'}), {'ok': True})
        self.assertEqual(json.loads(self.collector.config_path.read_text()), {
            'future': 42, 'assign': {'other': 'Keep', 'local:sid:s1': 'Commissions'}})

    def test_assign_failure_is_json_and_preserves_config(self):
        self.collector.config_path.write_text('broken json')
        value = self.json_request('/api/assign', body={'node': NODE['id'], 'initiative': 'Pin'})
        self.assertFalse(value['ok'])
        self.assertEqual(self.collector.config_path.read_text(), 'broken json')

    def test_server_info_file_written_and_removed(self):
        self.assertEqual(json.loads(self.info.read_text()),
                         {'port': self.port, 'key': self.key, 'pid': os.getpid()})
        self.assertEqual(stat.S_IMODE(self.info.stat().st_mode), 0o600)
        self.assertRegex(self.key, r'^[0-9a-f]{64}$')
        self.instance.stop()
        self.instance.stop()
        self.assertFalse(self.info.exists())
        with self.assertRaises((URLError, OSError)):
            self.request('/api/state')

    def test_refresh_failure_and_slow_refresh_keep_previous_snapshot(self):
        self.instance.stop()
        self.start_server(poll_seconds=0.02)
        self.wait_for_snapshot()
        self.collector.error = RuntimeError('temporary failure')
        self.collector.attempted.clear()
        self.assertTrue(self.collector.attempted.wait(1))
        self.assertEqual(self.json_request('/api/state')['generated_at'], 123)
        self.collector.error = None
        self.collector.block.clear()
        self.collector.attempted.clear()
        self.assertTrue(self.collector.attempted.wait(1))
        self.assertEqual(self.json_request('/api/state')['generated_at'], 123)
        self.collector.value = {'nodes': [], 'edges': [], 'generated_at': 456}
        self.collector.block.set()
        self.assertEqual(self.wait_for_snapshot(456)['poll_seconds'], 0.02)

    def test_idle_watchdog_stops_server(self):
        self.instance.stop()
        self.start_server(idle_minutes=0.01)
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())
        self.assertFalse(self.info.exists())

    def test_requests_extend_idle_deadline(self):
        self.instance.stop()
        self.start_server(idle_minutes=0.01)
        for _ in range(5):
            time.sleep(0.2)
            self.json_request('/api/state')
        self.assertTrue(self.thread.is_alive())
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())

    def test_stop_before_serving_returns_without_deadlock(self):
        self.instance.stop()
        instance = server.FleetMapServer(self.collector, self.actions, page_path=self.page)
        instance.start()
        thread = threading.Thread(target=instance.stop, daemon=True)
        thread.start()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        instance.serve_forever()
        self.assertFalse(self.info.exists())

    def test_main_prints_one_json_line_before_serving(self):
        events = []

        class LaunchServer:
            def __init__(self, collector, actions):
                pass

            def start(self):
                return 12345, 'launch-key'

            def serve_forever(self):
                events.append(output.getvalue())

            def stop(self):
                pass

        output = io.StringIO()
        with patch.object(server, 'FleetMapServer', LaunchServer), contextlib.redirect_stdout(output):
            server.main()
        expected = {'url': 'http://127.0.0.1:12345/?key=launch-key'}
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertEqual(events, [output.getvalue()])


if __name__ == '__main__':
    unittest.main()

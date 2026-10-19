"""Snapshot integration with real transcripts and a canned Orca boundary."""
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.model import Collector
from fleetmap.orca import OrcaClient, OrcaError
from fleetmap.registry import LocalSession, Subagent
from fleetmap.transcript import read_transcript

FIX = ROOT / 'tests/fixtures/fleetmap/session.jsonl'
NOW = datetime.fromisoformat('2026-10-19T10:10:00+00:00').timestamp()


def terminal(handle='term_a', **extra):
    return dict(handle=handle, title='Agent terminal', worktreePath='/work/project',
                branch='feature/review', tabId='tab', leafId=handle,
                agentIdentity={'kind': 'codex'}, lastOutputAt=NOW - 10, **extra)


class FakeOrca(OrcaClient):
    def __init__(self):
        super().__init__()
        self.responses = {(None, ('environment', 'list')):
                          {'environments': [{'name': 'laptop2'}]}}
        self.errors = {}
        for env in (None, 'laptop2'):
            for command, key in ((('terminal', 'list'), 'terminals'),
                                 (('orchestration', 'run-list'), 'runs'),
                                 (('orchestration', 'worker-list'), 'workers'),
                                 (('orchestration', 'task-list'), 'tasks'),
                                 (('orchestration', 'inbox'), 'messages')):
                self.responses[env, command] = {key: []}
            self.responses[env, ('terminal', 'read')] = {'screen': 'Building\nChecks passed'}

    def call(self, args, env=None):
        key = env, tuple(args[:2])
        error = self.errors.get(key) or self.errors.get(env)
        if error:
            raise error
        return self.responses[key]

    def put(self, command, key, records, env=None):
        self.responses[env, tuple(command.split())] = {key: records}


class SnapshotAssembler(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fleetmap-model-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.transcript = self.base / 'session.jsonl'
        shutil.copyfile(FIX, self.transcript)
        self.config = self.base / 'config.json'
        self.orca = FakeOrca()
        self.local = [LocalSession(
            pid=123, session_id='s1', name='Chief', cwd='/work/project',
            status='busy', started_at=NOW - 600, status_updated_at=NOW - 5,
            transcript=str(self.transcript), orca_pane=('tab', 'term_a'),
            hook_state=None, kitty_key=None, ctx_pct=42, cost=1.25, subagents=[])]
        self.tmux = {}
        self.orca.put('terminal list', 'terminals', [terminal()])
        clock = patch('fleetmap.model.time.time', return_value=NOW)
        self.clock = clock.start()
        self.addCleanup(clock.stop)

    def collector(self, orca_errors=None):
        self.orca.errors.update(orca_errors or {})
        return Collector(self.orca, config_path=self.config,
                         sessions=lambda: self.local, tmux_sessions=lambda: self.tmux)

    def node(self, snapshot, node_id='local:sid:s1'):
        return next(n for n in snapshot['nodes'] if n['id'] == node_id)

    def test_claude_node_state_prefers_hook_file(self):
        for hook, status, expected in (('attention', 'busy', 'attention'),
                                       ('done', 'busy', 'done'),
                                       ('working', 'idle', 'idle'),
                                       (None, 'busy', 'working'),
                                       (None, 'idle', 'idle')):
            with self.subTest(hook=hook, status=status):
                self.local[0] = replace(self.local[0], hook_state=hook, status=status)
                self.assertEqual(self.node(self.collector().snapshot())['state'], expected)

    def test_snapshot_contract_and_transcript_fields(self):
        snap = self.collector().snapshot()
        self.assertEqual(set(snap), {'generated_at', 'hosts', 'nodes', 'edges'})
        self.assertEqual(snap['generated_at'], NOW)
        self.assertIn({'name': 'local', 'label': 'This Mac', 'reachable': True}, snap['hosts'])
        node = self.node(snap)
        self.assertEqual(set(node), {
            'id', 'host', 'kind', 'parent', 'title', 'purpose', 'doing', 'last_said',
            'state', 'you_at', 'it_at', 'never_addressed', 'cluster', 'repo',
            'worktree', 'branch', 'hosting', 'model', 'ctx_pct', 'cost', 'moves',
            'terminal', 'tmux', 'kitty_window'})
        self.assertEqual((node['title'], node['purpose'], node['doing'], node['last_said']),
                         ('Handoff scheduling run', 'Review PR 6869 under run 20261007',
                          'SendMessage: PR Review', 'Review complete. The checks passed.'))
        self.assertEqual((node['you_at'], node['it_at']), (NOW - 600, NOW - 120))
        self.assertEqual((node['ctx_pct'], node['cost'], node['repo']), (42, 1.25, 'project'))
        self.assertEqual((node['host'], node['kind'], node['hosting'], node['terminal']),
                         ('local', 'claude', 'orca', 'term_a'))
        self.assertEqual(node['moves'][0], [NOW - 120, 'said: Review complete. The checks passed.'])
        self.assertEqual(json.loads(json.dumps(snap)), snap)

    def test_dispatched_worker_ignores_first_prompt(self):
        self.orca.put('orchestration worker-list', 'workers',
                      [{'dispatchId': 'd1', 'agentTerminalHandle': 'term_a'}], 'laptop2')
        collector = self.collector()
        node = self.node(collector.snapshot())
        self.assertIsNone(node['you_at'])
        self.assertTrue(node['never_addressed'])
        self.assertEqual(node['cluster'], 'review')
        with self.transcript.open('a') as fh:
            fh.write(json.dumps({'type': 'user', 'timestamp': '2026-10-19T10:10:00Z',
                                 'message': {'content': 'Please continue'}}) + '\n')
        node = self.node(collector.snapshot())
        self.assertEqual(node['you_at'], NOW)
        self.assertFalse(node['never_addressed'])

    def test_unreachable_environment_is_listed_without_nodes(self):
        snap = self.collector(orca_errors={'laptop2': OrcaError('timeout')}).snapshot()
        host = next(h for h in snap['hosts'] if h['name'] == 'laptop2')
        self.assertEqual((host['reachable'], host['error']), (False, 'timeout'))
        self.assertFalse([n for n in snap['nodes'] if n['host'] == 'laptop2'])
        self.assertEqual(len(snap['nodes']), 1)

    def test_any_host_call_failure_discards_all_its_nodes(self):
        self.orca.put('terminal list', 'terminals', [terminal('term_remote')], 'laptop2')
        for env in (None, 'laptop2'):
            for command in ('terminal list', 'orchestration run-list',
                            'orchestration worker-list', 'orchestration task-list',
                            'orchestration inbox', 'terminal read'):
                with self.subTest(env=env, command=command):
                    self.orca.put('terminal list', 'terminals', [terminal(), terminal('term_other')])
                    self.orca.errors = {(env, tuple(command.split())): OrcaError('offline')}
                    snap = self.collector().snapshot()
                    host = 'local' if env is None else env
                    self.assertIn({'name': host, 'label': 'This Mac' if env is None else host,
                                   'reachable': False, 'error': 'offline'}, snap['hosts'])
                    self.assertFalse([n for n in snap['nodes'] if n['host'] == host])

    def test_remote_terminal_nodes_from_environment(self):
        remote = [terminal('term_r1'), terminal('term_r2')]
        remote[1].update(agentIdentity=None, lastOutputAt=NOW - 60)
        self.orca.put('terminal list', 'terminals', remote, 'laptop2')
        snap = self.collector().snapshot()
        nodes = [n for n in snap['nodes'] if n['host'] == 'laptop2']
        self.assertEqual([n['id'] for n in nodes],
                         ['env:laptop2:term:term_r1', 'env:laptop2:term:term_r2'])
        self.assertEqual([n['state'] for n in nodes], ['working', 'idle'])
        for node in nodes:
            self.assertEqual((node['hosting'], node['kind']), ('laptop2', 'terminal'))
            self.assertEqual(node['last_said'], 'Building\nChecks passed')
            self.assertTrue(node['never_addressed'])

    def test_local_agent_terminal_without_claude_is_drawn_and_shell_is_not(self):
        shell = terminal('term_shell')
        shell['agentIdentity'] = None
        self.orca.put('terminal list', 'terminals', [terminal(), terminal('term_codex'), shell])
        snap = self.collector().snapshot()
        self.assertEqual([n['id'] for n in snap['nodes']], ['local:sid:s1', 'local:term:term_codex'])

    def test_subagent_nodes_and_edges(self):
        agent_path = self.base / 'agent.jsonl'
        shutil.copyfile(FIX, agent_path)
        self.local[0].subagents = [Subagent('a1', str(agent_path), NOW - 119),
                                   Subagent('a2', str(agent_path), NOW - 120)]
        snap = self.collector().snapshot()
        for agent_id, state, mtime in (('a1', 'working', NOW - 119), ('a2', 'done', NOW - 120)):
            node = self.node(snap, 'local:agent:' + agent_id)
            self.assertEqual((node['kind'], node['parent'], node['state']),
                             ('subagent', 'local:sid:s1', state))
            self.assertEqual(node['cluster'], self.node(snap)['cluster'])
            self.assertIn({'src': 'local:sid:s1', 'dst': node['id'], 'count': 1,
                           'newest': mtime, 'kind': 'subagent'}, snap['edges'])

    def test_second_snapshot_reuses_transcript_offsets(self):
        collector = self.collector()
        with patch('fleetmap.model.read_transcript', wraps=read_transcript) as read:
            first = collector.snapshot()
            second = collector.snapshot()
        self.assertEqual(first, second)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(read.call_args.kwargs['prev'].offset, self.transcript.stat().st_size)

    def test_truncated_transcript_discards_cached_facts(self):
        collector = self.collector()
        collector.snapshot()
        self.transcript.write_text('')
        with patch('fleetmap.model.read_transcript', wraps=read_transcript) as read:
            node = self.node(collector.snapshot())
        self.assertIsNone(read.call_args.kwargs.get('prev'))
        self.assertEqual((node['title'], node['purpose'], node['moves']), ('Chief', '', []))
        self.assertEqual(node['cluster'], 'Unsorted')

    def test_new_worker_policy_invalidates_old_transcript_facts(self):
        collector = self.collector()
        self.assertFalse(self.node(collector.snapshot())['never_addressed'])
        self.orca.put('orchestration worker-list', 'workers',
                      [{'dispatchId': 'd1', 'agentTerminalHandle': 'term_a'}])
        self.assertTrue(self.node(collector.snapshot())['never_addressed'])

    def test_no_human_prompt_is_unsorted_regardless_of_worktree_or_pin(self):
        self.transcript.write_text('{"type":"ai-title","aiTitle":"Review"}\n')
        self.config.write_text(json.dumps({'assign': {'s1': 'Pinned'}}))
        node = self.node(self.collector().snapshot())
        self.assertEqual(node['cluster'], 'Unsorted')
        self.assertTrue(node['never_addressed'])

    def test_hosting_precedence_and_action_targets(self):
        self.local[0] = replace(self.local[0], kitty_key='456-7')
        self.tmux = {'neko-test': {'panes': [123]}}
        collector = self.collector()
        self.assertEqual(self.node(collector.snapshot())['hosting'], 'orca')
        self.local[0] = replace(self.local[0], orca_pane=None)
        node = self.node(collector.snapshot())
        self.assertEqual((node['hosting'], node['tmux'], node['kitty_window']), ('tmux', 'neko-test', 7))
        self.tmux.clear()
        self.assertEqual(self.node(collector.snapshot())['hosting'], 'kitty')
        self.local[0] = replace(self.local[0], kitty_key=None)
        snap = collector.snapshot()
        self.assertEqual(self.node(snap)['hosting'], 'orca')
        self.assertEqual(len(snap['nodes']), 1)
        self.orca.put('terminal list', 'terminals', [])
        self.assertEqual(self.node(collector.snapshot())['hosting'], 'unknown')

    def test_exact_pane_match_wins_over_another_sessions_cwd(self):
        self.local.insert(0, replace(self.local[0], session_id='s2', pid=456, orca_pane=None))
        snap = self.collector().snapshot()
        self.assertEqual(self.node(snap)['terminal'], 'term_a')
        self.assertIsNone(self.node(snap, 'local:sid:s2')['terminal'])

    def test_run_objective_and_cross_host_edges_with_stable_first_seen(self):
        self.orca.put('terminal list', 'terminals', [terminal('term_worker')], 'laptop2')
        self.orca.put('orchestration run-list', 'runs',
                      [{'id': 'r1', 'coordinator_handle': 'term_a', 'objective': 'Fleet map: assemble'}])
        self.orca.put('orchestration worker-list', 'workers',
                      [{'dispatchId': 'd1', 'runId': 'r1', 'agentTerminalHandle': 'term_worker'}])
        self.orca.put('orchestration inbox', 'messages',
                      [{'id': 'm1', 'from_handle': 'dispatch:d1', 'to_handle': 'run:r1'}])
        collector = self.collector()
        first = collector.snapshot()
        self.clock.return_value = NOW + 30
        second = collector.snapshot()
        self.assertEqual([n['cluster'] for n in first['nodes']], ['Fleet map', 'Fleet map'])
        expected = [{'src': 'env:laptop2:term:term_worker', 'dst': 'local:sid:s1',
                     'count': 1, 'newest': NOW, 'kind': 'dispatch'}]
        self.assertEqual(first['edges'], expected)
        self.assertEqual(second['edges'], expected)

    def test_cwd_matched_terminal_edges_target_claude_node(self):
        self.local[0] = replace(self.local[0], orca_pane=None)
        self.orca.put('terminal list', 'terminals', [terminal(), terminal('term_b')])
        self.orca.put('orchestration inbox', 'messages',
                      [{'id': 'm1', 'from_handle': 'term_b', 'to_handle': 'term_a', 'created_at': 100}])
        self.assertEqual(self.collector().snapshot()['edges'],
                         [{'src': 'local:term:term_b', 'dst': 'local:sid:s1',
                           'count': 1, 'newest': 100.0, 'kind': 'dispatch'}])

    def test_git_root_and_branch_for_session_without_orca(self):
        repo = self.base / 'project-root'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'feature/git-branch', str(repo)], check=True)
        cwd = repo / 'nested'
        cwd.mkdir()
        self.local[0] = replace(self.local[0], cwd=str(cwd), orca_pane=None)
        self.orca.put('terminal list', 'terminals', [])
        node = self.node(self.collector().snapshot())
        self.assertEqual((node['repo'], node['worktree'], node['branch'], node['cluster']),
                         ('project-root', str(repo.resolve()), 'feature/git-branch', 'git-branch'))

    def test_missing_transcript_is_an_unprompted_node(self):
        self.transcript.unlink()
        node = self.node(self.collector().snapshot())
        self.assertEqual((node['title'], node['cluster']), ('Chief', 'Unsorted'))
        self.assertTrue(node['never_addressed'])

    def test_environment_discovery_error_keeps_local_host_visible(self):
        with patch.object(self.orca, 'environments', side_effect=OrcaError('offline')):
            snap = self.collector().snapshot()
        self.assertEqual(snap['hosts'], [dict(name='local', label='This Mac',
                                             reachable=False, error='offline')])
        self.assertEqual((snap['nodes'], snap['edges']), ([], []))

    def test_first_seen_is_scoped_to_host_and_edges_require_visible_nodes(self):
        self.local.clear()
        self.orca.put('terminal list', 'terminals', [terminal(), terminal('term_b')])
        self.orca.put('terminal list', 'terminals', [terminal('term_r1'), terminal('term_r2')], 'laptop2')
        self.orca.put('orchestration inbox', 'messages',
                      [{'id': 'm1', 'from_handle': 'term_a', 'to_handle': 'term_b'},
                       {'id': 'gone', 'from_handle': 'term_a', 'to_handle': 'term_gone'}])
        collector = self.collector()
        self.assertEqual(len(collector.snapshot()['edges']), 1)
        self.clock.return_value = NOW + 30
        self.orca.put('orchestration inbox', 'messages',
                      [{'id': 'm1', 'from_handle': 'term_r1', 'to_handle': 'term_r2'}], 'laptop2')
        snap = collector.snapshot()
        self.assertEqual([e['newest'] for e in snap['edges']], [NOW, NOW + 30])
        self.orca.errors['laptop2'] = OrcaError('offline')
        snap = collector.snapshot()
        self.assertEqual(len(snap['edges']), 1)
        self.assertEqual(snap['edges'][0]['newest'], NOW)

    def test_config_is_reloaded_and_new_transcript_path_resets_facts(self):
        collector = self.collector()
        self.assertEqual(self.node(collector.snapshot())['cluster'], 'review')
        self.config.write_text(json.dumps({'assign': {'s1': 'Pinned'}}))
        self.assertEqual(self.node(collector.snapshot())['cluster'], 'Pinned')
        replacement = self.base / 'replacement.jsonl'
        replacement.write_text(json.dumps({'type': 'user', 'timestamp': '2026-10-19T10:10:00Z',
                                           'message': {'content': 'New purpose'}}) + '\n')
        self.local[0] = replace(self.local[0], transcript=str(replacement))
        node = self.node(collector.snapshot())
        self.assertEqual((node['title'], node['purpose'], node['you_at']), ('Chief', 'New purpose', NOW))


if __name__ == '__main__':
    unittest.main()

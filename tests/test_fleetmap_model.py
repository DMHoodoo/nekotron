from __future__ import annotations

"""Snapshot integration with real transcripts and a canned Orca boundary."""
from dataclasses import asdict, replace
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.providers.directory import DirectoryProvider
from fleetmap.providers.engineering_os import EngineeringOsProvider
from fleetmap.model import Collector, repository_name
from fleetmap.clusters import load
from fleetmap.orca import OrcaClient, OrcaError
from fleetmap.registry import LocalSession, Subagent
from fleetmap.transcript import read_transcript
from tests.test_fleetmap_matrix import projection, package, slice_row

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


class PrimedCollector(Collector):
    """Fixture driver explicitly refreshes slow sources before asserting joined facts."""
    def snapshot(self):
        sessions = self.sessions()
        self._local_input = (sessions, {s.cwd for s in sessions}, list(load(self.config_path).hosts))
        self.refresh_sources()
        self.refresh_sources()  # Cross-runtime run bindings can arrive on the next poll.
        return super().snapshot()


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
        return PrimedCollector(self.orca, config_path=self.config,
                         sessions=lambda: self.local, tmux_sessions=lambda: self.tmux,
                         providers=[DirectoryProvider(self.base / "progress")])

    def node(self, snapshot, node_id='local:sid:s1'):
        return next(n for n in snapshot['nodes'] if n['id'] == node_id)

    def write_projection(self, value):
        directory = self.base / 'progress'
        directory.mkdir(exist_ok=True)
        data = asdict(value)
        data.pop('path')
        data.pop('mtime')
        (directory / (value.run + '.json')).write_text(json.dumps(data))
        self.orca.put('orchestration run-list', 'runs',
                      [{'id': value.run, 'objective': 'Legacy objective',
                        'coordinator_handle': value.chiefTerminal}])

    def test_short_name_keeps_initiative_names(self):
        for name in ('Core lint speed', 'Core lint speed across every project today'):
            with self.subTest(name=name):
                self.config.write_text(json.dumps({
                    'assign': {'s1': name},
                    'projects': [{'name': name, 'slices': [{
                        'name': 'Root cause', 'stage': 'review', 'sessions': ['s1']}]}]}))
                snapshot = self.collector().snapshot()
                self.assertEqual(snapshot['clusters'][name]['short_name'], name)

    def test_every_snapshot_cluster_has_short_name(self):
        title = 'Projected initiative name with more than five words'
        self.write_projection(projection(title=title))
        objective = 'Review PR 6869 under Engineering OS run 20261007'
        self.orca.responses[None, ('orchestration', 'run-list')]['runs'].append({
            'id': 'legacy', 'objective': objective})
        snapshot = self.collector().snapshot()
        self.assertGreaterEqual(len(snapshot['clusters']), 3)
        for record in snapshot['clusters'].values():
            self.assertIsInstance(record['short_name'], str)
            self.assertEqual(record['full_name'], record['name'])
        self.assertEqual(snapshot['clusters'][title]['short_name'], title)
        self.assertEqual(snapshot['clusters'][objective]['short_name'],
                         'Review PR 6869 under Engineering…')
        self.assertEqual(snapshot['clusters'][objective]['name'], objective)

    def test_legacy_cluster_keeps_full_objective_and_identity(self):
        cases = [
            ('Review: finish the pending delivery with all evidence',
             'Review', 'Review: finish the pending delivery…'),
            ('Review; finish the pending delivery with all evidence',
             'Review', 'Review; finish the pending delivery…'),
            ('<pasted_content id="4e35">\n'
             'Continue a review of c5a5627d657b67bb95d28fdf6d794f7d4dff9131 now',
             '<pasted_content id="4e35">\nContinue a review of c5a5627d657b',
             'Continue a review of now'),
        ]
        for objective, identity, summary in cases:
            with self.subTest(objective=objective):
                self.orca.put('orchestration run-list', 'runs', [{
                    'id': 'legacy', 'objective': objective,
                    'coordinator_handle': 'term_a'}])
                snapshot = self.collector().snapshot()
                self.assertEqual(self.node(snapshot)['cluster'], identity)
                record = snapshot['clusters'][identity]
                self.assertEqual(record['name'], identity)
                self.assertEqual(record['full_name'], objective)
                self.assertEqual(record['short_name'], summary)

    def test_local_worktree_run_status_reaches_run_and_cluster_and_refreshes(self):
        root = self.base / 'checkout'
        directory = root / 'engineering-os' / 'run_a'
        directory.mkdir(parents=True)
        (directory / 'run-plan.md').write_text('# Run plan\n')
        fixture = ROOT / 'tests/fixtures/fleetmap/run_v2.json'
        path = directory / 'run-status.json'
        record = json.loads(fixture.read_text())
        record['runPlan']['worktree'] = '/nonexistent/worktree'
        path.write_text(json.dumps(record))
        self.local[0] = replace(self.local[0], cwd=str(root))
        local_terminal = dict(terminal(record['chiefTerminal']), worktreePath=str(root),
                              leafId='term_a')
        self.orca.put('terminal list', 'terminals', [local_terminal])
        self.orca.put('orchestration run-list', 'runs', [{
            'id': record['run'], 'objective': 'Legacy title',
            'coordinator_handle': record['chiefTerminal']}])
        collector = PrimedCollector(self.orca, config_path=self.config,
                                   sessions=lambda: self.local, tmux_sessions=lambda: {})
        snapshot = collector.snapshot()
        self.assertIn(record['run'], snapshot['runs'])
        self.assertEqual(snapshot['clusters'][record['title']]['run'], record['run'])
        self.assertEqual(self.node(snapshot)['cluster'], record['title'])
        record['statusCard']['running'] = 'Next checkpoint'
        path.write_text(json.dumps(record))
        self.assertEqual(collector.snapshot()['runs'][record['run']]['status_card']['running'],
                         'Next checkpoint')
        # A reachable path from a remote terminal must not become a local root.
        self.local = []
        self.orca.put('terminal list', 'terminals', [])
        self.orca.put('terminal list', 'terminals', [local_terminal], 'laptop2')
        self.assertEqual(collector.snapshot()['runs'], {})

    def test_provider_config_and_rejections_are_visible_in_snapshot(self):
        directory = self.base / 'exports'
        directory.mkdir()
        (directory / 'bad.json').write_text('{')
        self.config.write_text(json.dumps({'providers': {
            'directory': {'path': str(directory)}, 'future': {}}}))
        with self.assertLogs('fleetmap.providers', level='WARNING'):
            collector = Collector(self.orca, config_path=self.config, sessions=lambda: [])
        snapshot = collector.snapshot()
        self.assertEqual(snapshot['rejected_projections']['bad.json'], 'unreadable')
        self.assertIn('unknown provider: future', snapshot['rejected_projections'].values())

    def test_snapshot_never_calls_orca_git_or_tmux(self):
        collector = Collector(self.orca, config_path=self.config, sessions=lambda: self.local,
                              tmux_sessions=lambda: self.fail('foreground tmux probe'),
                              providers=[DirectoryProvider(self.base / 'progress')])
        with patch.object(self.orca, 'call', side_effect=AssertionError('foreground Orca')), \
                patch('fleetmap.model._git_metadata', side_effect=AssertionError('foreground git')):
            first = collector.snapshot()
            with self.transcript.open('a') as output:
                output.write(json.dumps({'type': 'assistant', 'timestamp': '2026-10-19T10:20:00Z', 'message': {'content': 'New local text'}}) + '\n')
            second = collector.snapshot()
        self.assertNotEqual(self.node(first)['last_said'], self.node(second)['last_said'])
        self.assertEqual(self.node(second)['last_said'], 'New local text')

    def make_repository(self, name='glow-core'):
        repo = self.base / name
        repo.mkdir()
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
                   GIT_COMMITTER_EMAIL='t@t')
        def git(*args):
            subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env=env)
        git('init', '-q', '-b', 'main')
        git('commit', '-q', '--allow-empty', '-m', 'init')
        git('worktree', 'add', '-q', '-b', 'feature', str(self.base / (name + '-wt')))
        return repo, self.base / (name + '-wt')

    def test_repository_name_from_common_dir(self):
        repo, wt = self.make_repository()
        self.assertEqual(repository_name(str(repo)), 'glow-core')
        self.assertEqual(repository_name(str(wt)), 'glow-core')
        plain = self.base / 'plain'
        plain.mkdir()
        self.assertIsNone(repository_name(str(plain)))

    def test_worktrees_of_one_repository_share_a_cluster_and_keep_branches(self):
        repo, wt = self.make_repository()
        self.local[0] = replace(self.local[0], cwd=str(repo))
        second = replace(self.local[0], session_id='s2', cwd=str(wt))
        self.local.append(second)
        snapshot = PrimedCollector(self.orca, config_path=self.config, sessions=lambda: self.local,
                                   tmux_sessions=lambda: {}).snapshot()
        first, other = self.node(snapshot, 'local:sid:s1'), self.node(snapshot, 'local:sid:s2')
        self.assertEqual((first['cluster'], other['cluster']), ('glow-core', 'glow-core'))
        self.assertEqual((first['repository'], other['repository']), ('glow-core', 'glow-core'))
        self.assertEqual((first['branch'], other['branch']), ('main', 'feature'))

    def test_local_folder_outside_any_repository_is_unsorted_but_unprimed_uses_path(self):
        with patch('fleetmap.model._git_metadata', return_value=('', '')):
            node = self.node(self.collector().snapshot())
        self.assertEqual(node['cluster'], 'Unsorted')
        self.assertEqual(node['repository'], '')
        fresh = Collector(self.orca, config_path=self.config, sessions=lambda: self.local,
                          tmux_sessions=lambda: {}, providers=[DirectoryProvider(self.base / 'progress')])
        self.assertEqual(self.node(fresh.snapshot())['repository'], 'project')

    def test_repository_lookup_runs_in_slow_thread_and_is_cached(self):
        collector = Collector(self.orca, config_path=self.config, sessions=lambda: [],
                              tmux_sessions=lambda: {}, providers=[DirectoryProvider(self.base / 'progress')])
        collector._local_input = ([], {'/work/project'}, [])
        with patch('fleetmap.model._git_metadata', return_value=('/work/project', 'main')), \
                patch('fleetmap.model.repository_name', return_value='glow-core') as lookup:
            collector.refresh_sources()
            collector.refresh_sources()
            self.assertEqual(lookup.call_count, 1)
            stamp, value = collector._slow['repository']['/work/project']
            collector._slow['repository']['/work/project'] = (stamp - 61, value)
            collector.refresh_sources()
            self.assertEqual(lookup.call_count, 2)
        with patch('fleetmap.model.repository_name', side_effect=AssertionError('foreground git')), \
                patch('fleetmap.model._git_metadata', side_effect=AssertionError('foreground git')):
            collector.snapshot()

    def test_screen_and_git_cache_ttls(self):
        self.local.clear()
        self.orca.put('terminal list', 'terminals', [terminal()])
        collector = Collector(self.orca, config_path=self.config, sessions=lambda: [],
                              tmux_sessions=lambda: {}, providers=[DirectoryProvider(self.base / 'progress')])
        collector._local_input = ([], {'/work/project'}, [])
        with patch.object(self.orca, 'screen', return_value='screen') as screen, \
                patch('fleetmap.model._git_metadata', return_value=('/work/project', 'main')) as git:
            collector.refresh_sources()
            collector.refresh_sources()
            self.assertEqual(screen.call_count, 1)
            self.assertEqual(git.call_count, 1)
            stamp, value = collector._screens[('local', 'term_a')]
            collector._screens[('local', 'term_a')] = (stamp - 31, value)
            collector.refresh_sources()
            self.assertEqual(screen.call_count, 2)
            self.assertEqual(git.call_count, 1)
            stamp, value = collector._slow['git']['/work/project']
            collector._slow['git']['/work/project'] = (stamp - 61, value)
            collector.refresh_sources()
            self.assertEqual(git.call_count, 2)

    def test_screen_timeout_does_not_starve_healthy_terminal_across_cycles(self):
        self.config.write_text(json.dumps({'hosts': {'laptop2': {}}}))
        self.orca.put('terminal list', 'terminals',
                      [terminal('term_bad'), terminal('term_good')], 'laptop2')
        original = self.orca.call
        for cached in (False, True):
            with self.subTest(cached=cached):
                collector = Collector(self.orca, config_path=self.config, sessions=lambda: [],
                                      providers=[DirectoryProvider(self.base / 'progress')])
                clock = [100.0]
                reads = []
                if cached:
                    collector._screens[('laptop2', 'term_bad')] = (1.0, 'Last good screen')
                    collector._screens[('laptop2', 'term_good')] = (2.0, 'Old healthy screen')

                def call(args, env=None):
                    if args[:2] == ['terminal', 'read']:
                        self.orca.remaining_timeout()
                        handle = args[args.index('--terminal') + 1]
                        reads.append(handle)
                        if handle == 'term_bad':
                            clock[0] += 5
                            raise OrcaError('timeout')
                        return {'screen': 'Healthy screen published'}
                    return original(args, env)

                snapshots = []
                with patch('fleetmap.model.time.monotonic', side_effect=lambda: clock[0]), \
                        patch.object(self.orca, 'call', side_effect=call):
                    for _ in range(3):
                        collector._refresh_host('laptop2', [])
                        snapshots.append(collector.snapshot())
                        clock[0] += 3
                self.assertIn('term_good', reads)
                self.assertLess(reads.count('term_bad'), 3)
                self.assertEqual(self.node(snapshots[-1], 'env:laptop2:term:term_good')
                                 ['last_said'], 'Healthy screen published')
                for snapshot in snapshots:
                    self.assertEqual(self.node(snapshot, 'env:laptop2:term:term_bad')
                                     ['last_said'], 'Last good screen' if cached else '')
                if cached:
                    self.assertEqual(collector._screens[('laptop2', 'term_bad')],
                                     (1.0, 'Last good screen'))

    def retire(self, *states):
        handles = ['term_r%d' % i for i in range(len(states))]
        self.orca.put('terminal list', 'terminals',
                      [terminal()] + [dict(terminal(h), title='Retired ' + h) for h in handles])
        self.orca.put('orchestration worker-list', 'workers', [
            {'dispatchId': 'd_' + h, 'runId': 'run_x', 'agentTerminalHandle': h,
             'workerState': state, 'terminalState': 'retained'}
            for h, state in zip(handles, states)])
        return handles

    def test_retired_worker_terminals_are_not_nodes(self):
        self.retire('released', 'abandoned')
        snap = self.collector().snapshot()
        self.assertEqual([n['id'] for n in snap['nodes'] if n['kind'] == 'terminal'], [])
        retired = [r for c in snap['clusters'].values() for r in c.get('retired_workers', [])]
        self.assertEqual(sorted((r['title'], r['dispatchId'], r['state']) for r in retired),
                         [('Retired term_r0', 'd_term_r0', 'released'),
                          ('Retired term_r1', 'd_term_r1', 'abandoned')])
        self.assertTrue(all(isinstance(r['retainedFor'], int) for r in retired))
        self.assertEqual(len({name for name, c in snap['clusters'].items()
                              if c.get('retired_workers')}), 1)

    def test_retired_worker_without_output_stamp_has_unknown_retention(self):
        handles = self.retire('released')
        self.orca.put('terminal list', 'terminals', [
            terminal(), dict(terminal(handles[0]), title='Retired', lastOutputAt=None)])
        snap = self.collector().snapshot()
        retired = [r for c in snap['clusters'].values() for r in c.get('retired_workers', [])]
        self.assertEqual([r['retainedFor'] for r in retired], [None])

    def test_live_agent_terminal_is_never_retired(self):
        self.orca.put('orchestration worker-list', 'workers', [
            {'dispatchId': 'd1', 'agentTerminalHandle': 'term_a',
             'workerState': 'released', 'terminalState': 'retained'}])
        snap = self.collector().snapshot()
        self.assertIn('local:sid:s1', [n['id'] for n in snap['nodes']])
        self.assertEqual([r for c in snap['clusters'].values()
                          for r in c.get('retired_workers', [])], [])

    def test_unretained_or_running_workers_stay_nodes(self):
        self.orca.put('terminal list', 'terminals', [dict(terminal('term_w'), title='W')])
        self.orca.put('orchestration worker-list', 'workers', [
            {'dispatchId': 'd1', 'agentTerminalHandle': 'term_w', 'workerState': 'succeeded'}])
        snap = self.collector().snapshot()
        self.assertIn('local:term:term_w', [n['id'] for n in snap['nodes']])

    def test_host_worker_count_excludes_retired(self):
        handles = self.retire('released', 'succeeded', 'failed')
        self.orca.put('terminal list', 'terminals',
                      [terminal(), dict(terminal('term_live'), title='Live')] +
                      [dict(terminal(h), title='Retired ' + h) for h in handles])
        self.orca.responses[None, ('orchestration', 'worker-list')]['workers'].append(
            {'dispatchId': 'd_live', 'agentTerminalHandle': 'term_live', 'workerState': 'running'})
        snap = self.collector().snapshot()
        self.assertEqual(snap['hosts'][0]['workers'], 1)

    def test_projection_joins_remote_chief_and_local_worker_over_pin(self):
        self.config.write_text(json.dumps({'assign': {'s1': 'Pinned'}, 'projects': [
            {'name': 'Pinned', 'slices': [{'name': 'Manual', 'stage': 'goal',
                                         'sessions': ['s1']}]}], 'caps': {'laptop2': 0}}))
        self.orca.put('terminal list', 'terminals', [terminal('term_chief')], 'laptop2')
        self.orca.put('orchestration worker-list', 'workers', [
            {'dispatchId': 'd1', 'runId': 'run_test', 'agentTerminalHandle': 'term_a',
             'workerState': 'running', 'host': 'laptop2'},
            {'dispatchId': 'd2', 'agentTerminalHandle': 'term_chief',
             'workerState': 'running', 'host': 'local'}])
        self.write_projection(projection(
            slices=[slice_row(stage='review', packages=['P1'])],
            packages=[package('P1', dispatchId='d1', machine='laptop2')],
            caps={'laptop2': 3}, decisions=[{'id': 'D1', 'class': 'D', 'text': 'Approve'}]))
        snap = self.collector().snapshot()
        node = self.node(snap)
        self.assertEqual((node['cluster'], node['cluster_source'], node['stage']),
                         ('Review run', 'run', 'review'))
        self.assertEqual(node['pin_overridden'], 'Pinned')
        self.assertIsNone(node['ladder'])
        matrix = snap['runs']['run_test']
        self.assertEqual(matrix['chief_node'], 'env:laptop2:term:term_chief')
        self.assertEqual(matrix['rows'][0]['live'], ['local:sid:s1'])
        self.assertEqual(snap['clusters']['Review run']['matrix_host'], 'laptop2')
        self.assertEqual(snap['decisions'][0]['run'], 'run_test')
        self.assertEqual([(h['workers'], h['cap'], h['amber']) for h in snap['hosts']],
                         [(1, None, False), (1, 3, False)])
        self.assertEqual(matrix['packages'][0]['id'], 'P1')
        self.assertEqual(matrix['run_plan']['path'], 'plan.md')

    def test_terminal_without_transcript_on_remote_host_groups_by_path_repository(self):
        self.orca.put('terminal list', 'terminals', [
            dict(terminal('term_worker'), worktreePath='/Users/hok/orca/workspaces/glow-core/wt-a',
                 branch='refs/heads/hok/handoff-l2-p06-outcomes'),
            dict(terminal('term_other'), worktreePath='/Users/hok/Documents/GlowDevelopment/glow-core/.claude/worktrees/wt-b')],
            'laptop2')
        snap = self.collector().snapshot()
        nodes = [self.node(snap, f'env:laptop2:term:{name}') for name in ('term_worker', 'term_other')]
        self.assertEqual([(n['cluster'], n['cluster_source']) for n in nodes],
                         [('glow-core', 'worktree')] * 2)
        self.assertIsNone(nodes[0]['you_at'])

    def test_projected_dispatch_joins_remote_terminal_from_any_hosts_scoped_list(self):
        self.write_projection(projection(chiefTerminal='term_a',
            slices=[slice_row(stage='review', packages=['P1'])],
            packages=[package('P1', dispatchId='d_remote', machine='laptop2')]))
        self.orca.put('terminal list', 'terminals', [terminal('term_worker')], 'laptop2')
        original = self.orca.call
        for storage_host in (None, 'laptop2'):
            with self.subTest(storage_host=storage_host):
                def call(args, env=None):
                    if args[:2] == ['orchestration', 'worker-list']:
                        # Unscoped calls inherit the map launcher's unrelated run.
                        if env == storage_host and '--run' in args and args[3] == 'run_test':
                            if '--cursor' not in args:
                                return {'workers': [], 'page': {'nextCursor': 'opaque cursor'}}
                            self.assertEqual(args[-2:], ['--cursor', 'opaque cursor'])
                            return {'workers': [{'dispatchId': 'd_remote', 'runId': 'run_test',
                                'agentTerminalHandle': 'term_worker', 'host': 'local',
                                'workerState': 'running'}]}
                        return {'workers': []}
                    return original(args, env)
                with patch.object(self.orca, 'call', side_effect=call):
                    snap = self.collector().snapshot()
                node_id = 'env:laptop2:term:term_worker'
                node = self.node(snap, node_id)
                self.assertEqual((node['cluster'], node['cluster_source'], node['stage']),
                                 ('Review run', 'run', 'review'))
                self.assertEqual(snap['runs']['run_test']['rows'][0]['live'], [node_id])
                self.assertEqual(snap['hosts'][1]['workers'], 1)

    def test_rejected_and_missing_projection_notes_are_on_run_clusters(self):
        self.write_projection(projection(chiefTerminal='term_a'))
        objective = 'Handoff scheduling: wave 1 running; waiting for approval | full objective'
        self.orca.put('orchestration run-list', 'runs',
                      [{'id': 'run_test', 'objective': objective, 'coordinator_handle': 'term_a'}])
        (self.base / 'progress/run_test.json').write_text('{"schemaVersion": 1}')
        collector = self.collector()
        snap = collector.snapshot()
        reason = snap['rejected_projections']['run_test.json']
        self.assertIn(reason, snap['clusters']['Handoff scheduling']['notes'])
        self.assertEqual(snap['clusters']['Handoff scheduling']['fallbacks'], [
            {'run': 'run_test', 'now': objective, 'note': reason}])
        (self.base / 'progress/run_test.json').unlink()
        snap = collector.snapshot()
        self.assertIn('projection v1, Chief must re-render',
                      snap['clusters']['Handoff scheduling']['notes'])
        self.assertEqual(snap['runs'], {})
        self.assertEqual(snap['clusters']['Handoff scheduling']['fallbacks'], [
            {'run': 'run_test', 'now': objective, 'note': 'projection v1, Chief must re-render'}])

    def test_rejected_known_run_keeps_last_good_projection_and_reason(self):
        self.write_projection(projection(chiefTerminal='term_a'))
        collector = self.collector()
        first = collector.snapshot()
        self.assertIn('run_test', first['runs'])
        self.assertIsNone(first['clusters']['Review run']['status_rejected'])
        (self.base / 'progress/run_test.json').write_text('{"schemaVersion": 1}')
        (self.base / 'progress/stray.json').write_text('{')
        second = collector.snapshot()
        reason = 'schemaVersion 1, Chief must re-render'
        self.assertEqual(second['runs']['run_test']['title'], first['runs']['run_test']['title'])
        self.assertEqual(second['clusters']['Review run']['status_rejected'], reason)
        self.assertEqual(second['unattributed_rejections'],
                         [{'path': 'stray.json', 'reason': 'unreadable'}])

    def git_repo(self):
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid',
                   GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null')
        repo = self.base / 'repo'
        repo.mkdir()
        def git(*args, cwd=repo):
            subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, env=env)
        git('init', '-q', '-b', 'main')
        git('commit', '-q', '--allow-empty', '-m', 'init')
        return repo, git

    def plan_text(self, **changes):
        data = json.loads(json.dumps(asdict(projection(chiefTerminal='term_a'))))
        data.pop('path'); data.pop('mtime')
        data.update(changes)
        return '# Plan\n\n```json run-status\n' + json.dumps(data) + '\n```\n'

    def test_plan_in_a_sibling_worktree_without_a_session_is_found(self):
        repo, git = self.git_repo()
        sibling = self.base / 'sibling'
        git('worktree', 'add', '-q', str(sibling), '-b', 'other')
        plan = sibling / 'engineering-os/r1/run-plan.md'
        plan.parent.mkdir(parents=True)
        plan.write_text(self.plan_text())
        self.orca.put('orchestration run-list', 'runs', [{'id': 'run_test', 'objective': 'Objective',
                                                          'coordinator_handle': 'term_a'}])
        provider = EngineeringOsProvider(extra_roots=[])
        collector = Collector(self.orca, config_path=self.config, sessions=lambda: [],
                              tmux_sessions=lambda: {}, providers=[provider])
        collector._local_input = ([], {str(repo)}, [])
        collector.refresh_sources()
        self.assertIn(Path(sibling.resolve()), [p.resolve() for p in collector._slow['roots']])
        good, bad = provider.load(collector._slow['roots'])
        self.assertEqual((bad, [p.run for p in good]), ({}, ['run_test']))
        self.assertEqual(good[0].runPlan['worktree'], str(sibling.resolve()))
        self.assertIn('run_test', collector.snapshot()['runs'])

    def test_rejected_run_plan_naming_an_orca_run_keeps_cluster_and_shows_reason(self):
        repo = self.base / 'plans'
        plan = repo / 'engineering-os/r1/run-plan.md'
        plan.parent.mkdir(parents=True)
        plan.write_text(self.plan_text())
        self.orca.put('orchestration run-list', 'runs', [{'id': 'run_test', 'objective': 'Objective',
                                                          'coordinator_handle': 'term_a'}])
        def collector():
            return PrimedCollector(self.orca, config_path=self.config, sessions=lambda: [],
                             tmux_sessions=lambda: {},
                             providers=[EngineeringOsProvider(extra_roots=[repo])])
        kept = collector()
        first = kept.snapshot()
        self.assertIsNone(first['clusters']['Review run']['status_rejected'])
        plan.write_text(self.plan_text(packages=None))
        second = kept.snapshot()
        self.assertEqual(second['clusters']['Review run']['status_rejected'], 'packages: expected array')
        self.assertEqual(second['runs']['run_test']['title'], first['runs']['run_test']['title'])
        self.assertEqual(second['unattributed_rejections'], [])
        fresh = collector().snapshot()
        record = next(c for c in fresh['clusters'].values() if c['run'] == 'run_test')
        self.assertEqual(record['status_rejected'], 'packages: expected array')
        self.assertNotIn('run_test', fresh['runs'])

    def test_last_good_projection_is_pruned_after_a_day_absent_everywhere(self):
        self.write_projection(projection(chiefTerminal='term_a'))
        collector = self.collector()
        collector.snapshot()
        self.assertIn('run_test', collector._last_good)
        (self.base / 'progress/run_test.json').unlink()
        self.orca.put('orchestration run-list', 'runs', [])
        collector.snapshot()
        self.assertIn('run_test', collector._last_good)
        self.clock.return_value = NOW + 24 * 3600 - 1
        collector.snapshot()
        self.assertIn('run_test', collector._last_good)
        self.clock.return_value = NOW + 24 * 3600 + 1
        collector.snapshot()
        self.assertNotIn('run_test', collector._last_good)

    def test_slow_refresh_gives_providers_the_local_roots(self):
        class Recording:
            name = 'recording'
            seen = []
            def refresh(self, roots): self.seen.append(roots)
            def load(self, roots): return [], {}
        provider = Recording()
        collector = Collector(self.orca, config_path=self.config, sessions=lambda: [],
                              tmux_sessions=lambda: {}, providers=[provider])
        collector._local_input = ([], {'/work/project'}, [])
        collector.refresh_sources()
        self.assertEqual(provider.seen, [[Path('/work/project')]])

    def test_fallback_run_preserves_matching_projected_cluster_binding(self):
        self.write_projection(projection())
        self.orca.put('terminal list', 'terminals', [terminal('term_chief')], 'laptop2')
        objective = 'Review run: legacy work; waiting'
        self.orca.put('orchestration run-list', 'runs', [
            {'id': 'run_test', 'objective': 'Projected review', 'coordinator_handle': 'term_chief'},
            {'id': 'run_legacy', 'objective': objective, 'coordinator_handle': 'term_a'}])
        snapshot = self.collector().snapshot()
        cluster = snapshot['clusters']['Review run']
        self.assertEqual(cluster['run'], 'run_test')
        self.assertEqual(cluster['matrix_host'], 'laptop2')
        self.assertIn(cluster['run'], snapshot['runs'])
        self.assertEqual(cluster['fallbacks'], [
            {'run': 'run_legacy', 'now': objective, 'note': 'projection v1, Chief must re-render'}])

    def test_projection_package_binds_even_when_not_listed_in_a_slice(self):
        self.write_projection(projection(slices=[slice_row(stage='review')],
            packages=[package('P1', dispatchId='d1')]))
        self.orca.put('orchestration worker-list', 'workers',
                      [{'dispatchId': 'd1', 'agentTerminalHandle': 'term_a'}])
        snap = self.collector().snapshot()
        self.assertEqual((self.node(snap)['cluster'], self.node(snap)['stage']),
                         ('Review run', 'review'))
        self.assertEqual(snap['clusters']['Review run']['matrix_host'], 'local')

    def test_run_without_terminals_keeps_note_and_does_not_bind_unhosted_session(self):
        self.orca.put('terminal list', 'terminals', [])
        self.orca.put('orchestration run-list', 'runs',
                      [{'id': 'missing', 'objective': 'Missing run: continue'}])
        snap = self.collector().snapshot()
        self.assertIsNone(self.node(snap)['run'])
        self.assertIn('projection v1, Chief must re-render',
                      snap['clusters']['Missing run']['notes'])

    def test_activity_stamp_tracks_all_three_inputs_and_first_observation(self):
        collector = self.collector()
        self.assertEqual(self.node(collector.snapshot())['activity_changed_at'], NOW)
        self.clock.return_value = NOW + 600
        self.assertTrue(self.node(collector.snapshot())['stalled'])
        with self.transcript.open('a') as output:
            output.write('{"type": "system"}\n')
        node = self.node(collector.snapshot())
        self.assertFalse(node['stalled'])
        self.assertEqual(node['activity_changed_at'], NOW + 600)
        self.clock.return_value = NOW + 1200
        self.assertTrue(self.node(collector.snapshot())['stalled'])
        self.orca.put('terminal list', 'terminals', [dict(terminal(), lastOutputAt=NOW + 1)])
        self.assertFalse(self.node(collector.snapshot())['stalled'])
        self.clock.return_value = NOW + 1800
        self.assertTrue(self.node(collector.snapshot())['stalled'])
        with self.transcript.open('a') as output:
            output.write(json.dumps({'type': 'assistant', 'timestamp': '2026-10-19T10:20:00Z',
                                      'message': {'content': []}}) + '\n')
        self.assertFalse(self.node(collector.snapshot())['stalled'])

    def test_slow_refresh_publishes_ladders_memory_and_stale_cells(self):
        self.write_projection(projection(chiefTerminal='term_other',
            gates=[{'id': 'goal', 'verdict': 'pass', 'at': None, 'headSha': 'aaaa'}]))
        collector = self.collector()
        initial = collector.snapshot()
        self.assertIsNone(self.node(initial)['ladder'])
        with patch.object(collector.ladder, 'rung', return_value={'rung': 'working', 'ahead': 2, 'pr': None}), \
             patch.object(collector.memory, 'probe', return_value={'free_pct': 30, 'swap_gb': 1}), \
             patch.object(collector.stale, 'check', return_value={'moved': True, 'commits': None}):
            collector.refresh_slow()
        snap = collector.snapshot()
        self.assertEqual(self.node(snap)['ladder']['rung'], 'working')
        self.assertTrue(snap['hosts'][0]['amber'])
        self.assertEqual(snap['runs']['run_test']['rows'][0]['cells']['goal']['stale'],
                         {'moved': True, 'commits': None})
        self.assertIsNone(initial['runs']['run_test']['rows'][0]['cells']['goal']['stale'])

    def test_stale_overlay_uses_effective_gate_and_invalidates_new_projection(self):
        value = projection(chiefTerminal='term_a',
            gates=[{'id': 'goal', 'verdict': 'pass', 'at': None, 'headSha': 'aaaa'},
                   {'id': 'general-code', 'verdict': 'pass', 'at': None, 'headSha': 'bbbb'}],
            slices=[dict(slice_row('1', gates=[
                {'id': 'general-code', 'verdict': 'pass', 'at': None, 'headSha': 'cccc'}]),
                branch='feature/slice')])
        self.write_projection(value)
        collector = self.collector()
        collector.snapshot()
        def evidence(p, gate, branch):
            return {'moved': True, 'commits': [branch or 'run', gate['headSha']]}
        with patch.object(collector.stale, 'check', side_effect=evidence), \
             patch.object(collector.memory, 'probe', return_value={'free_pct': None, 'swap_gb': None}):
            collector.refresh_slow()
        row = collector.snapshot()['runs']['run_test']['rows'][0]
        self.assertEqual(row['cells']['goal']['stale']['commits'], ['run', 'aaaa'])
        self.assertEqual(row['cells']['review']['chips'][-1]['stale']['commits'],
                         ['feature/slice', 'cccc'])
        value.gates[0]['headSha'] = 'dddd'
        self.write_projection(value)
        self.assertIsNone(collector.snapshot()['runs']['run_test']['rows'][0]['cells']['goal']['stale'])

    def test_memory_failure_blanks_and_worker_cap_is_independent(self):
        self.config.write_text(json.dumps({'caps': {'local': 0},
            'hosts': {'laptop2': {'ssh': 'test@remote'}}}))
        self.orca.put('orchestration worker-list', 'workers', [
            {'dispatchId': 'd1', 'agentTerminalHandle': 'term_a', 'workerState': 'running'}])
        collector = self.collector()
        collector.snapshot()
        with patch.object(collector.memory, 'probe', return_value={'free_pct': 70, 'swap_gb': 0}) as probe:
            collector.refresh_slow()
        self.assertIn(unittest.mock.call('laptop2', 'test@remote'), probe.call_args_list)
        snap = collector.snapshot()
        self.assertTrue(snap['hosts'][0]['amber'])
        self.assertFalse(snap['hosts'][1]['amber'])
        self.orca.errors['laptop2'] = OrcaError('offline')
        self.assertEqual(collector.snapshot()['hosts'][1]['memory'], {'free_pct': None, 'swap_gb': None})

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
        self.assertEqual(set(snap), {'generated_at', 'hosts', 'nodes', 'edges', 'runs', 'clusters',
                                     'decisions', 'rejected_projections',
                                     'unattributed_rejections'})
        self.assertEqual(snap['generated_at'], NOW)
        self.assertEqual(snap['hosts'][0], dict(name='local', label='This Mac', reachable=True,
            memory={'free_pct': None, 'swap_gb': None}, workers=0, cap=None, amber=False))
        node = self.node(snap)
        self.assertEqual(set(node), {
            'id', 'host', 'kind', 'parent', 'title', 'purpose', 'doing', 'last_said',
            'state', 'you_at', 'it_at', 'never_addressed', 'never_prompted', 'cluster', 'repo', 'repository',
            'worktree', 'branch', 'hosting', 'model', 'ctx_pct', 'cost', 'moves',
            'terminal', 'tmux', 'kitty_window', 'kitty_pid', 'subagents_total', 'subagents_shown',
            'stalled', 'ladder', 'stage', 'cluster_source', 'activity_changed_at',
            'transcript_offset', 'last_output_at', 'run', 'pin_overridden'})
        self.assertEqual((node['title'], node['purpose'], node['doing'], node['last_said']),
                         ('Handoff scheduling run', 'Review PR 6869 under run 20261007',
                          'SendMessage: PR Review', 'Review complete. The checks passed.'))
        self.assertEqual((node['you_at'], node['it_at']), (NOW - 600, NOW - 120))
        self.assertEqual((node['ctx_pct'], node['cost'], node['repo']), (42, 1.25, 'project'))
        self.assertEqual((node['host'], node['kind'], node['hosting'], node['terminal']),
                         ('local', 'claude', 'orca', 'term_a'))
        self.assertEqual((node['subagents_total'], node['subagents_shown']), (0, 0))
        self.assertEqual(node['moves'][0], [NOW - 120, 'said: Review complete. The checks passed.'])
        self.assertEqual(json.loads(json.dumps(snap)), snap)

    def test_prompt_without_timestamp_is_not_eligible_for_close_all(self):
        self.transcript.write_text(json.dumps({
            'type': 'user', 'message': {'content': 'Keep this human task'}}) + '\n')
        node = self.node(self.collector().snapshot())
        self.assertEqual(node['purpose'], 'Keep this human task')
        self.assertIsNone(node['you_at'])
        self.assertTrue(node['never_addressed'])
        self.assertFalse(node['never_prompted'])

    def test_no_prompt_and_no_timestamp_is_eligible_for_close_all(self):
        self.transcript.write_text('')
        node = self.node(self.collector().snapshot())
        self.assertEqual(node['purpose'], '')
        self.assertIsNone(node['you_at'])
        self.assertTrue(node['never_prompted'])

    def test_dispatched_worker_ignores_first_prompt(self):
        self.orca.put('orchestration worker-list', 'workers',
                      [{'dispatchId': 'd1', 'agentTerminalHandle': 'term_a'}], 'laptop2')
        collector = self.collector()
        node = self.node(collector.snapshot())
        self.assertIsNone(node['you_at'])
        self.assertTrue(node['never_addressed'])
        self.assertEqual(node['purpose'], 'Review PR 6869 under run 20261007')
        self.assertFalse(node['never_prompted'])
        self.assertEqual((node['worktree'], node['branch']), ('/work/project', 'feature/review'))
        self.assertEqual(node['cluster'], 'Unsorted')
        self.config.write_text(json.dumps({'assign': {'s1': 'Pinned'}}))
        node = self.node(collector.snapshot())
        self.assertIsNone(node['you_at'])
        self.assertEqual(node['cluster'], 'Pinned')
        self.config.unlink()
        self.assertEqual(self.node(collector.snapshot())['cluster'], 'Unsorted')
        with self.transcript.open('a') as fh:
            fh.write(json.dumps({'type': 'user', 'timestamp': '2026-10-19T10:10:00Z',
                                 'message': {'content': 'Please continue'}}) + '\n')
        node = self.node(collector.snapshot())
        self.assertEqual(node['you_at'], NOW)
        self.assertFalse(node['never_addressed'])
        self.assertEqual(node['cluster'], 'Unsorted')

    def test_dispatched_worker_run_objective_applies_before_human_follow_up(self):
        self.orca.put('orchestration worker-list', 'workers',
                      [{'dispatchId': 'd1', 'agentTerminalHandle': 'term_a', 'runId': 'r1'}])
        self.orca.put('orchestration run-list', 'runs',
                      [{'id': 'r1', 'objective': 'Fleet map: assemble'}])
        node = self.node(self.collector().snapshot())
        self.assertIsNone(node['you_at'])
        self.assertTrue(node['never_addressed'])
        self.assertEqual(node['cluster'], 'Fleet map')

    def test_unreachable_environment_is_listed_without_nodes(self):
        snap = self.collector(orca_errors={'laptop2': OrcaError('timeout')}).snapshot()
        host = next(h for h in snap['hosts'] if h['name'] == 'laptop2')
        self.assertEqual((host['reachable'], host['error']), (False, 'timeout'))
        self.assertFalse([n for n in snap['nodes'] if n['host'] == 'laptop2'])
        self.assertEqual(len(snap['nodes']), 1)

    def test_terminal_failure_retains_independent_local_sessions(self):
        self.orca.put('terminal list', 'terminals', [terminal('term_remote')], 'laptop2')
        for env in (None, 'laptop2'):
            with self.subTest(env=env):
                self.orca.errors = {(env, ('terminal', 'list')): OrcaError('offline')}
                snap = self.collector().snapshot()
                host = 'local' if env is None else env
                record = next(h for h in snap['hosts'] if h['name'] == host)
                self.assertEqual((record['reachable'], record['error']), (False, 'offline'))
                self.assertEqual(len([n for n in snap['nodes'] if n['host'] == host]),
                                 1 if host == 'local' else 0)

    def test_local_missing_orca_and_timeout_keep_transcript_and_kitty(self):
        self.local[0] = replace(self.local[0], kitty_key='111-7')
        for error in ('orca missing', 'terminal-list timeout'):
            with self.subTest(error=error):
                self.orca.errors = {(None, ('terminal', 'list')): OrcaError(error)}
                snap = self.collector().snapshot()
                node = self.node(snap)
                self.assertEqual(node['hosting'], 'kitty')
                self.assertTrue(node['purpose'])
                self.assertIsNone(node['terminal'])
                self.assertIn(error, snap['hosts'][0]['degraded'][0])

    def test_optional_source_failure_preserves_host_nodes(self):
        self.orca.put('terminal list', 'terminals', [terminal(), terminal('term_other')])
        self.orca.put('terminal list', 'terminals', [terminal('term_remote')], 'laptop2')
        for env in (None, 'laptop2'):
            self.orca.put('orchestration run-list', 'runs', [{'id': 'run_x'}], env)
            for source, command in (('runs', 'orchestration run-list'),
                                    ('workers', 'orchestration worker-list'),
                                    ('tasks', 'orchestration task-list'),
                                    ('inbox', 'orchestration inbox'),
                                    ('screen', 'terminal read')):
                with self.subTest(env=env, source=source):
                    error = 'run_required: No Run is bound' if source == 'tasks' else 'offline'
                    self.orca.errors = {(env, tuple(command.split())): OrcaError(error)}
                    snap = self.collector().snapshot()
                    host = next(h for h in snap['hosts']
                                if h['name'] == ('local' if env is None else env))
                    self.assertTrue(host['reachable'])
                    self.assertIn(f'{source}: {error}', host['degraded'])
                    self.assertNotIn('error', host)
                    self.assertEqual(len([n for n in snap['nodes'] if n['host'] == host['name']]),
                                     2 if env is None else 1)

    def test_tasks_are_collected_per_run_and_failed_run_is_skipped(self):
        self.orca.put('orchestration run-list', 'runs',
                      [{'id': 'run_bad'}, {'id': 'run_good'}])
        original_call = self.orca.call
        calls = []

        def call(args, env=None):
            if args[:2] == ['orchestration', 'task-list']:
                calls.append((args, env))
                if args[-1] == 'run_bad':
                    raise OrcaError('run_required: No Run is bound')
                return {'tasks': [{'id': 'task_good'}]}
            return original_call(args, env)

        with patch.object(self.orca, 'call', side_effect=call):
            records = self.collector()._poll_host('local', self.local)
        self.assertEqual(calls, [(['orchestration', 'task-list', '--run', 'run_bad'], None),
                                 (['orchestration', 'task-list', '--run', 'run_good'], None)])
        self.assertEqual(records['tasks'], [{'id': 'task_good'}])
        self.assertEqual(records['degraded'], ['tasks: run_required: No Run is bound'])

    def test_no_runs_does_not_query_unbound_tasks(self):
        with patch.object(self.orca, 'tasks', side_effect=AssertionError('unbound task-list')):
            self.assertTrue(self.collector().snapshot()['hosts'][0]['reachable'])

    def test_remote_terminal_nodes_from_environment(self):
        remote = [terminal('term_r1'), terminal('term_r2'), terminal('term_shell')]
        remote[2]['agentIdentity'] = None
        self.orca.put('orchestration worker-list', 'workers',
                      [{'agentTerminalHandle': 'term_r2', 'dispatchId': 'worker'}])
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
                                   Subagent('a2', str(agent_path), NOW - 120),
                                   Subagent('a3', str(agent_path), NOW - 7200)]
        snap = self.collector().snapshot()
        self.assertEqual([n['id'] for n in snap['nodes'] if n['kind'] == 'subagent'],
                         ['local:agent:a1', 'local:agent:a2'])
        self.assertEqual(len([e for e in snap['edges'] if e['kind'] == 'subagent']), 2)
        parent = self.node(snap)
        self.assertEqual((parent['subagents_total'], parent['subagents_shown']), (3, 2))
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

    def test_no_human_prompt_is_unsorted_unless_pinned(self):
        self.transcript.write_text('{"type":"ai-title","aiTitle":"Review"}\n')
        collector = self.collector()
        node = self.node(collector.snapshot())
        self.assertEqual(node['cluster'], 'Unsorted')
        self.assertTrue(node['never_addressed'])
        self.config.write_text(json.dumps({'assign': {'s1': 'Pinned'}}))
        node = self.node(collector.snapshot())
        self.assertEqual(node['cluster'], 'Pinned')
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
        self.assertEqual(self.node(collector.snapshot())['kitty_pid'], 456)
        self.local[0] = replace(self.local[0], kitty_key=None)
        snap = collector.snapshot()
        self.assertEqual(self.node(snap)['hosting'], 'unknown')
        self.assertEqual(len(snap['nodes']), 2)
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

    def test_same_cwd_terminal_edges_do_not_target_unverified_claude_node(self):
        self.local[0] = replace(self.local[0], orca_pane=None)
        self.orca.put('terminal list', 'terminals', [terminal(), terminal('term_b')])
        self.orca.put('orchestration inbox', 'messages',
                      [{'id': 'm1', 'from_handle': 'term_b', 'to_handle': 'term_a', 'created_at': 100}])
        self.assertEqual(self.collector().snapshot()['edges'],
                         [{'src': 'local:term:term_b', 'dst': 'local:term:term_a',
                           'count': 1, 'newest': 100.0, 'kind': 'dispatch'}])

    def test_same_cwd_independent_sessions_do_not_consume_orca_terminals(self):
        self.local[0] = replace(self.local[0], orca_pane=None, kitty_key='111-7')
        self.local.extend([replace(self.local[0], session_id='s2', kitty_key=None),
                           replace(self.local[0], session_id='s3', kitty_key=None)])
        self.orca.put('terminal list', 'terminals', [terminal(), terminal('term_codex')])
        snap = self.collector().snapshot()
        self.assertEqual(len(snap['nodes']), 5)
        self.assertEqual([n['hosting'] for n in snap['nodes'][:3]], ['kitty', 'unknown', 'unknown'])
        self.assertTrue(all(n['terminal'] is None for n in snap['nodes'][:3]))

    def test_disappeared_or_ambiguous_pane_has_no_action_target(self):
        for pane in (('old-tab', 'old-leaf'), ('tab', 'term_a')):
            with self.subTest(pane=pane):
                self.local[0] = replace(self.local[0], orca_pane=pane)
                self.orca.put('terminal list', 'terminals',
                              [terminal(), dict(terminal('other'), leafId='term_a')])
                snap = self.collector().snapshot()
                self.assertIsNone(self.node(snap)['terminal'])
                self.assertEqual(self.node(snap)['hosting'], 'unknown')
                self.assertEqual(len(snap['nodes']), 3)

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
                         ('project-root', str(repo.resolve()), 'feature/git-branch', 'project-root'))

    def test_missing_transcript_is_an_unprompted_node(self):
        self.transcript.unlink()
        node = self.node(self.collector().snapshot())
        self.assertEqual((node['title'], node['cluster']), ('Chief', 'Unsorted'))
        self.assertTrue(node['never_addressed'])

    def test_environment_discovery_error_keeps_local_host_visible(self):
        with patch.object(self.orca, 'environments', side_effect=OrcaError('offline')):
            snap = self.collector().snapshot()
        self.assertEqual(snap['hosts'], [dict(name='local', label='This Mac',
                                             reachable=True, degraded=['environments: offline'],
            memory={'free_pct': None, 'swap_gb': None}, workers=0, cap=None, amber=False)])
        self.assertEqual(len(snap['nodes']), 1)

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
        self.assertEqual(self.node(collector.snapshot())['cluster'], 'Unsorted')
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

from __future__ import annotations

"""Progress source discovery and selection through the provider interfaces."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.providers import load_from_providers, providers_from_config
from fleetmap.providers.directory import DirectoryProvider
from fleetmap.providers.engineering_os import EngineeringOsProvider

FIXTURE = ROOT / 'tests/fixtures/fleetmap/run_v2.json'


class ProgressProviders(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fleetmap-providers-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'worktree'
        self.root.mkdir()
        self.data = json.loads(FIXTURE.read_text())

    def write(self, relative, **changes):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(self.data, **changes)))
        return path

    def test_engineering_os_finds_only_the_three_documented_locations(self):
        paths = [self.write('run-status.json', run='root'),
                 self.write('engineering-os/run_a/run-status.json', run='a'),
                 self.write('run_b/run-status.json', run='b')]
        self.write('one/two/three/run-status.json', run='deep')
        self.write('other/run_a/run-status.json', run='wrong-prefix')
        self.write('run_b/other.json', run='wrong-name')
        good, bad = EngineeringOsProvider(extra_roots=[]).load([self.root])
        self.assertEqual({p.run for p in good}, {'root', 'a', 'b'})
        self.assertEqual({p.path for p in good}, set(map(str, paths)))
        self.assertEqual(bad, {})

    def test_engineering_os_rejects_invalid_sources_by_path_independently(self):
        valid = self.write('run-status.json')
        old = self.write('old/run-status.json', schemaVersion=1)
        malformed = self.write('bad/run-status.json')
        malformed.write_text('{')
        invalid = self.write('invalid/run-status.json', packages=None)
        good, bad = EngineeringOsProvider(extra_roots=[]).load([self.root])
        self.assertEqual([p.path for p in good], [str(valid)])
        self.assertEqual(bad[str(old)], 'schemaVersion 1, Chief must re-render')
        self.assertEqual(bad[str(malformed)], 'unreadable')
        self.assertEqual(bad[str(invalid)], 'packages: expected array')
        for version in ('2', 2.0, True, None):
            self.write('old/run-status.json', schemaVersion=version)
            self.assertIn(str(old), EngineeringOsProvider([]).load([self.root])[1])

    def test_engineering_os_ignores_symlinked_files_and_directories_outside_root(self):
        outside = self.base / 'outside'
        outside.mkdir()
        shutil.copyfile(FIXTURE, outside / 'run-status.json')
        (self.root / 'run-status.json').symlink_to(outside / 'run-status.json')
        (self.root / 'linked').symlink_to(outside, target_is_directory=True)
        (self.root / 'engineering-os').symlink_to(self.base, target_is_directory=True)
        self.assertEqual(EngineeringOsProvider([]).load([self.root]), ([], {}))

    def test_engineering_os_extra_roots_and_repeated_roots_read_each_source_once(self):
        self.write('run-status.json')
        provider = EngineeringOsProvider(extra_roots=[self.root])
        good, bad = provider.load([self.root, self.root, self.base / 'absent'])
        self.assertEqual(len(good), 1)
        self.assertEqual(bad, {})

    def test_directory_preserves_all_fields_and_reads_only_top_level_json(self):
        path = self.write('record.json')
        self.write('nested/record.json', run='nested')
        good, bad = DirectoryProvider(self.root).load([])
        self.assertEqual(bad, {})
        self.assertEqual(len(good), 1)
        fields = asdict(good[0])
        self.assertEqual(fields.pop('path'), str(path))
        self.assertEqual(fields.pop('mtime'), path.stat().st_mtime)
        self.assertEqual(fields, self.data)

    def test_directory_isolates_unreadable_invalid_and_old_files(self):
        self.write('valid.json')
        self.write('old.json', schemaVersion=1)
        self.write('invalid.json', packages=None)
        self.write('partial.json').write_text('{')
        (self.root / 'encoding.json').write_bytes(b'\xff')
        (self.root / 'missing.json').symlink_to(self.base / 'absent')
        (self.root / 'ignored.tmp').write_text('{')
        good, bad = DirectoryProvider(self.root).load([])
        self.assertEqual(len(good), 1)
        self.assertEqual(bad, {'old.json': 'schemaVersion 1, Chief must re-render',
                              'invalid.json': 'packages: expected array',
                              'partial.json': 'unreadable', 'encoding.json': 'unreadable',
                              'missing.json': 'unreadable'})
        self.assertEqual(DirectoryProvider(self.base / 'absent').load([]), ([], {}))

    def test_newer_updated_at_wins_across_providers_and_reports_superseded(self):
        older = self.write('run-status.json', updatedAt='2026-10-20T10:00:00Z')
        newer = self.write('exports/record.json', updatedAt='2026-10-20T04:00:00-07:00')
        self.write('exports/other.json', run='another')
        broken = self.write('bad/run-status.json')
        broken.write_text('{')
        providers = [EngineeringOsProvider([]), DirectoryProvider(self.root / 'exports')]
        for order in (providers, list(reversed(providers))):
            good, bad = load_from_providers(order, [self.root])
            self.assertEqual(len(good), 2)
            self.assertEqual(next(p.path for p in good if p.run == self.data['run']), str(newer))
            self.assertEqual(bad['engineering_os:' + str(older)], 'superseded')
            self.assertEqual(bad[str(broken)], 'unreadable')

    def test_config_defaults_to_engineering_os_and_expands_both_providers(self):
        defaults = providers_from_config({})
        self.assertEqual(len(defaults), 1)
        self.assertIsInstance(defaults[0], EngineeringOsProvider)
        self.assertEqual(defaults[0].extra_roots, [])
        configured = providers_from_config({'providers': {
            'engineering_os': {'roots': ['~/orca/workspaces/glow-core/lookdown']},
            'directory': {'path': '~/.glow/orca-progress'}}})
        self.assertEqual([p.name for p in configured], ['engineering_os', 'directory'])
        self.assertEqual(configured[0].extra_roots,
                         [Path('~/orca/workspaces/glow-core/lookdown').expanduser()])
        self.assertEqual(configured[1].path, Path('~/.glow/orca-progress').expanduser())
        self.assertEqual(providers_from_config({'providers': {}}), [])

    def test_unknown_provider_is_a_config_note_and_does_not_disable_known_provider(self):
        with self.assertLogs('fleetmap.providers', level='WARNING') as captured:
            providers = providers_from_config({'providers': {'future': {}, 'engineering_os': {}}})
        self.assertEqual([p.name for p in providers], ['engineering_os'])
        self.assertIn('unknown provider: future', captured.output[0])


def block(data, fence='```json run-status'):
    return fence + '\n' + json.dumps(data) + '\n```\n'


class RunPlanStatus(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fleetmap-plans-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'repo'
        self.root.mkdir()
        self.data = json.loads(FIXTURE.read_text())
        self.env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
                        GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid',
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null')
        self.git('init', '-q', '-b', 'main')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True, env=self.env).stdout.strip()

    def plan(self, text, relative='engineering-os/r1/run-plan.md', commit=True):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if commit:
            self.git('add', '.')
            self.git('commit', '-q', '-m', 'plan')
        return path

    def load(self):
        provider = EngineeringOsProvider(extra_roots=[])
        provider.refresh([self.root])
        return provider.load([self.root])

    def test_provider_reads_run_status_block_from_run_plan(self):
        path = self.plan('# Plan\n\n' + block(self.data))
        good, bad = self.load()
        self.assertEqual(bad, {})
        self.assertEqual(len(good), 1)
        self.assertEqual(good[0].run, self.data['run'])
        self.assertEqual(good[0].path, str(path))
        self.assertEqual(good[0].runPlan['commit'], self.git('log', '-1', '--format=%h'))
        self.assertEqual(good[0].runPlan['path'], 'engineering-os/r1/run-plan.md')
        self.assertEqual(good[0].runPlan['worktree'], str(self.root))
        self.assertEqual(good[0].plan_commit_at, float(self.git('log', '-1', '--format=%ct')))

    def test_plan_without_block_is_ignored(self):
        self.plan('# Plan\n\nNo status here.\n')
        self.assertEqual(self.load(), ([], {}))

    def test_plan_with_two_blocks_or_bad_json_is_rejected_with_reason(self):
        two = self.plan(block(self.data) + block(self.data), 'engineering-os/two/run-plan.md')
        bad = self.plan('```json run-status\n{\n```\n', 'engineering-os/bad/run-plan.md')
        invalid = self.plan(block(dict(self.data, packages=None)), 'engineering-os/inv/run-plan.md')
        good, rejected = self.load()
        self.assertEqual(good, [])
        self.assertIn('found 2', rejected[str(two)])
        self.assertTrue(rejected[str(bad)].startswith('json run-status'))
        self.assertEqual(rejected[str(invalid)], 'packages: expected array')

    def test_nested_example_fences_do_not_count(self):
        self.plan('````markdown\n' + block(self.data) + '````\n\n' + block(self.data))
        good, bad = self.load()
        self.assertEqual((len(good), bad), (1, {}))

    def test_block_and_file_for_same_run_newer_wins(self):
        plan = self.plan(block(dict(self.data, updatedAt='2026-10-21T10:00:00Z')))
        stale = self.root / 'engineering-os/r1/run-status.json'
        stale.write_text(json.dumps(dict(self.data, updatedAt='2026-10-20T10:00:00Z')))
        provider = EngineeringOsProvider(extra_roots=[])
        provider.refresh([self.root])
        good, bad = load_from_providers([provider], [self.root])
        self.assertEqual([p.path for p in good], [str(plan)])
        self.assertEqual(bad['engineering_os:' + str(stale)], 'superseded')
        stale.write_text(json.dumps(dict(self.data, updatedAt='2026-10-22T10:00:00Z')))
        good, bad = load_from_providers([provider], [self.root])
        self.assertEqual([p.path for p in good], [str(stale)])

    def test_fast_thread_never_calls_git_for_plans(self):
        self.plan(block(self.data))
        provider = EngineeringOsProvider(extra_roots=[])
        with patch('fleetmap.providers.engineering_os._plan_git',
                   side_effect=AssertionError('foreground git')), \
                patch('subprocess.run', side_effect=AssertionError('foreground git')):
            good, bad = provider.load([self.root])
        self.assertEqual((len(good), bad), (1, {}))
        self.assertEqual(good[0].runPlan['commit'], '')
        provider.refresh([self.root])
        self.assertNotEqual(provider.load([self.root])[0][0].runPlan['commit'], '')

    def test_plan_git_answers_are_cached_by_path_and_mtime(self):
        path = self.plan(block(self.data))
        provider = EngineeringOsProvider(extra_roots=[])
        with patch('fleetmap.providers.engineering_os._plan_git',
                   return_value=(str(self.root), 'abc1234', 5.0, 'h', 'h')) as git:
            provider.refresh([self.root])
            provider.refresh([self.root])
            self.assertEqual(git.call_count, 1)
            os.utime(path, (1, 1))
            provider.refresh([self.root])
            self.assertEqual(git.call_count, 2)

    def test_rejected_plan_names_its_run_from_block_or_directory(self):
        two = self.plan(block(self.data) + block(self.data), 'engineering-os/dir_run/run-plan.md')
        invalid = self.plan(block(dict(self.data, run='from_block', packages=None)),
                            'engineering-os/other_dir/run-plan.md')
        provider = EngineeringOsProvider(extra_roots=[])
        provider.load([self.root])
        self.assertEqual(provider.rejected_runs,
                         {str(two): 'dir_run', str(invalid): 'from_block'})

    def test_plan_changed_is_amber_only_when_a_commit_skips_the_block(self):
        path = self.plan('# Plan\n\n' + block(dict(self.data, updatedAt='2026-10-21T10:00:00Z')))
        self.assertIs(self.load()[0][0].plan_changed, False)
        path.write_text(path.read_text() + '\nMore prose.\n')
        self.git('commit', '-q', '-am', 'prose only')
        self.assertIs(self.load()[0][0].plan_changed, True)
        path.write_text('# Plan\n\nMore.\n\n' + block(dict(self.data, updatedAt='2026-10-21T11:00:00Z')))
        self.git('commit', '-q', '-am', 'block and prose together')
        self.assertIs(self.load()[0][0].plan_changed, False)

    def test_file_source_amber_uses_a_fifteen_minute_allowance(self):
        plan = self.plan('# Plan\n')
        committed = float(self.git('log', '-1', '--format=%ct'))
        results = []
        for lag in (600, 1200):
            updated = datetime.fromtimestamp(committed - lag, timezone.utc).isoformat()
            status = self.root / 'engineering-os/r1/run-status.json'
            status.write_text(json.dumps(dict(
                self.data, updatedAt=updated,
                runPlan=dict(self.data['runPlan'], path='engineering-os/r1/run-plan.md',
                             worktree=str(self.root)))))
            good, bad = self.load()
            self.assertEqual(bad, {})
            results.append(good[0].plan_changed)
        self.assertEqual(results, [False, True])
        self.assertEqual(good[0].plan_commit_at, committed)
        self.assertTrue(plan.exists())

    def test_git_cache_notices_a_commit_that_leaves_mtime_unchanged(self):
        path = self.plan(block(self.data), commit=False)
        os.utime(path, (1000, 1000))
        provider = EngineeringOsProvider(extra_roots=[])
        provider.refresh([self.root])
        self.assertEqual(provider.load([self.root])[0][0].runPlan['commit'], '')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'plan')
        os.utime(path, (1000, 1000))
        provider.refresh([self.root])
        self.assertEqual(provider.load([self.root])[0][0].runPlan['commit'],
                         self.git('log', '-1', '--format=%h'))


if __name__ == '__main__':
    unittest.main()

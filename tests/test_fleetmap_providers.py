from __future__ import annotations

"""Progress source discovery and selection through the provider interfaces."""
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()

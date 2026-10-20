from __future__ import annotations

"""Read Chief projections through the public reader and validator interfaces."""
import copy
from dataclasses import asdict
import inspect
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.projection import (
    GATE_IDS, PACKAGE_STATES, REQUIRED_FIELDS, SIZES, STAGES, VERDICTS,
    Projection, load_projections, validate,
)

FIX_V2 = ROOT / 'tests/fixtures/fleetmap/run_v2.json'
FIX_V1 = ROOT / 'tests/fixtures/fleetmap/run_v1.json'


class ProjectionReader(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fleetmap-projection-')
        self.addCleanup(temporary.cleanup)
        self.dir = Path(temporary.name)
        self.data = json.loads(FIX_V2.read_text())
        shutil.copyfile(FIX_V2, self.dir / FIX_V2.name)

    def write(self, data, name='run_v2.json'):
        (self.dir / name).write_text(json.dumps(data))

    def test_v2_fixture_loads_every_field(self):
        good, bad = load_projections(self.dir)
        self.assertEqual(bad, {})
        self.assertEqual(len(good), 1)
        projection = good[0]
        self.assertIsInstance(projection, Projection)
        self.assertEqual(projection.run, 'run_4d94eb181d65')
        self.assertEqual(projection.title, 'Handoff scheduling')
        self.assertEqual(projection.slices[0]['stage'], 'implementing')
        self.assertEqual(projection.packages[0]['dispatchId'], 'ctx_39129d9df0a8')
        fields = asdict(projection)
        self.assertEqual(fields.pop('path'), str(self.dir / FIX_V2.name))
        self.assertEqual(fields.pop('mtime'), (self.dir / FIX_V2.name).stat().st_mtime)
        self.assertEqual(fields, self.data)
        self.assertEqual(validate(self.data), [])

    def test_v1_file_is_rejected_with_rerender_reason(self):
        shutil.copyfile(FIX_V1, self.dir / FIX_V1.name)
        good, bad = load_projections(self.dir)
        self.assertEqual(len(good), 1)
        self.assertEqual(bad['run_v1.json'], 'schemaVersion 1, Chief must re-render')

    def test_missing_required_field_names_the_path(self):
        del self.data['packages'][0]['size']
        self.assertIn('packages[0].size: missing', validate(self.data))
        self.write(self.data)
        good, bad = load_projections(self.dir)
        self.assertEqual(good, [])
        self.assertEqual(bad['run_v2.json'], 'packages[0].size: missing')

    def test_unknown_stage_is_a_violation(self):
        self.data['slices'][0]['stage'] = 'shipping'
        self.assertIn("slices[0].stage: 'shipping' not in STAGES", validate(self.data))

    def test_unknown_package_size_is_a_violation(self):
        self.data['packages'][0]['size'] = 'XL'
        self.assertEqual(validate(self.data), ['packages[0].size: not in SIZES'])
        self.write(self.data)
        self.assertEqual(load_projections(self.dir),
                         ([], {'run_v2.json': 'packages[0].size: not in SIZES'}))

    def test_unknown_slice_package_reference_is_a_violation(self):
        self.data['slices'][0]['packages'].append('missing')
        error = 'slices[0].packages[8]: unknown package missing'
        self.assertEqual(validate(self.data), [error])
        self.write(self.data)
        self.assertEqual(load_projections(self.dir), ([], {'run_v2.json': error}))

    def test_half_written_file_is_skipped(self):
        (self.dir / 'partial.json').write_text('{"schemaVersion":2,')
        (self.dir / 'bad-encoding.json').write_bytes(b'\xff')
        (self.dir / 'ignored.tmp').write_text('{')
        good, bad = load_projections(self.dir)
        self.assertEqual(len(good), 1)
        self.assertEqual(bad, {'partial.json': 'unreadable', 'bad-encoding.json': 'unreadable'})

    def test_unreadable_file_does_not_hide_valid_file(self):
        (self.dir / 'missing.json').symlink_to(self.dir / 'absent')
        good, bad = load_projections(self.dir)
        self.assertEqual(len(good), 1)
        self.assertEqual(bad, {'missing.json': 'unreadable'})

    def test_missing_directory_is_empty(self):
        self.assertEqual(load_projections(self.dir / 'absent'), ([], {}))

    def test_version_must_be_integer_two(self):
        for version in (1, 3, '2', 2.0, True, None):
            with self.subTest(version=version):
                self.data['schemaVersion'] = version
                self.assertTrue(validate(self.data))
                self.write(self.data)
                good, bad = load_projections(self.dir)
                self.assertEqual(good, [])
                self.assertEqual(bad['run_v2.json'],
                                 f'schemaVersion {version}, Chief must re-render')
        del self.data['schemaVersion']
        self.write(self.data)
        self.assertEqual(load_projections(self.dir)[1]['run_v2.json'],
                         'schemaVersion 1, Chief must re-render')

    def test_all_violations_are_returned_including_nested_fields(self):
        del self.data['runPlan']['commit']
        del self.data['statusCard']['nextCheckpoint']
        del self.data['slices'][0]['gates'][0]['at']
        self.data['packages'][0]['state'] = 'shipping'
        errors = validate(self.data)
        self.assertIn('runPlan.commit: missing', errors)
        self.assertIn('statusCard.nextCheckpoint: missing', errors)
        self.assertIn('slices[0].gates[0].at: missing', errors)
        self.assertIn("packages[0].state: 'shipping' not in PACKAGE_STATES", errors)

    def test_vocabulary_at_each_scope(self):
        changes = [
            (self.data['gates'][0], 'id', 'unknown', "gates[0].id: 'unknown' not in GATE_IDS"),
            (self.data['slices'][0]['gates'][0], 'verdict', 'unknown',
             "slices[0].gates[0].verdict: 'unknown' not in VERDICTS"),
            (self.data['decisions'][0], 'class', 'A', "decisions[0].class: 'A' not in B, C, D"),
            (self.data['acceptance'], 'state', 'done', "acceptance.state: 'done' not in pending, accepted, merged"),
        ]
        for record, key, value, error in changes:
            record[key] = value
        errors = validate(self.data)
        for _, _, _, error in changes:
            self.assertIn(error, errors)

    def test_malformed_shapes_never_raise(self):
        for value in (None, [], 2, True, 'text'):
            with self.subTest(root=value):
                self.assertEqual(validate(value), ['$: expected object'])
        for key in self.data:
            if key == 'caps':
                continue
            for value in ([], {}, 42, False):
                if type(value) is type(self.data[key]):
                    continue
                with self.subTest(key=key, value=value):
                    data = copy.deepcopy(self.data)
                    data[key] = value
                    self.assertTrue(validate(data))
        for key in ('slices', 'packages', 'gates', 'decisions', 'proofs'):
            for value in (None, [], 'text', 42):
                data = copy.deepcopy(self.data)
                data[key] = [value]
                self.assertIn(f'{key}[0]: expected object', validate(data))

    def test_optional_fields_can_be_omitted(self):
        del self.data['caps']
        del self.data['pr']['number']
        for key in ('at', 'by'):
            del self.data['acceptance'][key]
        for decision in self.data['decisions']:
            for key in ('packet', 'applyAt'):
                decision.pop(key, None)
        for scope in [self.data] + self.data['slices']:
            for gate in scope['gates']:
                for key in ('headSha', 'ref'):
                    gate.pop(key, None)
        for item in self.data['slices']:
            item.pop('branch', None)
        for item in self.data['packages']:
            for key in ('headSha', 'lastEvent', 'lastEventAt'):
                item.pop(key, None)
        self.assertEqual(validate(self.data), [])
        self.write(self.data)
        good, bad = load_projections(self.dir)
        self.assertEqual(bad, {})
        self.assertEqual(good[0].caps, {})

    def test_empty_lists_are_valid(self):
        for key in ('slices', 'packages', 'gates', 'decisions', 'proofs'):
            self.data[key] = []
        self.assertEqual(validate(self.data), [])

    def test_wrong_scalar_and_list_element_types_are_reported(self):
        self.data['pr']['number'] = True
        self.data['mergeGate']['ready'] = 1
        self.data['mergeGate']['classDOpen'] = False
        self.data['packages'][0]['blockedBy'] = [None]
        self.data['caps']['laptop2'] = '7'
        errors = validate(self.data)
        for path in ('pr.number', 'mergeGate.ready', 'mergeGate.classDOpen',
                     'packages[0].blockedBy[0]', 'caps.laptop2'):
            self.assertTrue(any(error.startswith(path + ':') for error in errors), path)

    def test_worktree_and_decision_default_time(self):
        self.data['runPlan']['worktree'] = 'relative/path'
        self.data['decisions'][0].update({'class': 'B', 'applyAt': 'tomorrow'})
        errors = validate(self.data)
        self.assertIn('runPlan.worktree: expected absolute path', errors)
        self.assertIn('decisions[0].applyAt: expected ISO 8601 time', errors)
        self.data['runPlan']['worktree'] = '/checkout'
        self.data['decisions'][0]['applyAt'] = '2026-10-20T10:30:00Z'
        self.assertEqual(validate(self.data), [])

    def test_validator_can_be_copied_without_module_state(self):
        namespace = {}
        exec(inspect.getsource(validate), namespace)
        independent = namespace['validate']
        original = copy.deepcopy(self.data)
        self.assertEqual(independent(self.data), [])
        self.assertEqual(self.data, original)
        del self.data['packages'][0]['size']
        self.assertEqual(independent(self.data), ['packages[0].size: missing'])

    def test_unknown_fields_do_not_prevent_loading(self):
        self.data['futureField'] = {'something': True}
        self.write(self.data)
        good, bad = load_projections(self.dir)
        self.assertEqual(len(good), 1)
        self.assertEqual(bad, {})

    def test_non_object_json_is_rejected_with_first_violation(self):
        self.write([])
        self.assertEqual(load_projections(self.dir),
                         ([], {'run_v2.json': '$: expected object'}))

    def test_exported_vocabulary_matches_reference_h(self):
        self.assertEqual(set(REQUIRED_FIELDS), {
            'schemaVersion', 'run', 'title', 'updatedAt', 'runPlan', 'pr',
            'acceptance', 'chiefTerminal', 'now', 'statusCard', 'decisions',
            'gates', 'mergeGate', 'proofs', 'slices', 'packages',
        })
        self.assertEqual(set(STAGES), {
            'goal', 'design', 'plan', 'implementing', 'review', 'delivery', 'accepted',
        })
        self.assertEqual(set(PACKAGE_STATES), {
            'planned', 'assigned', 'running', 'returned', 'verified', 'blocked',
        })
        self.assertEqual(set(GATE_IDS), {
            'goal', 'design', 'plan', 'test-quality', 'code-standards',
            'commenting', 'general-code', 'delivery',
        })
        self.assertEqual(set(VERDICTS), {'pass', 'revise', 'pending'})
        self.assertEqual(set(SIZES), {'S', 'M', 'L'})
        for choices, record, key in (
                (STAGES, self.data['slices'][0], 'stage'),
                (PACKAGE_STATES, self.data['packages'][0], 'state'),
                (SIZES, self.data['packages'][0], 'size'),
                (GATE_IDS, self.data['gates'][0], 'id'),
                (VERDICTS, self.data['gates'][0], 'verdict')):
            for choice in choices:
                record[key] = choice
                self.assertEqual(validate(self.data), [])


if __name__ == '__main__':
    unittest.main()

from __future__ import annotations

"""Gate matrices through the public projection and terminal resolver interfaces."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.edges import Resolver
from fleetmap.matrix import build_matrix
from fleetmap.projection import Projection, validate
from fleetmap.registry import LocalSession

FIXTURE = ROOT / 'tests/fixtures/fleetmap/run_v2.json'


def projection(**overrides):
    data = dict(
        schemaVersion=2, run='run_test', title='Review run', updatedAt='2026-10-19',
        runPlan={'path': 'plan.md', 'commit': 'abc', 'worktree': '/work'},
        pr={'repo': 'example/repo'}, acceptance={'state': 'pending'},
        chiefTerminal='term_chief', now='Reviewing',
        statusCard={'done': '', 'running': '', 'blockedOn': '', 'nextCheckpoint': ''},
        decisions=[], gates=[],
        mergeGate={'ready': False, 'classDOpen': 0, 'classBUnratified': 0},
        proofs=[], slices=[], packages=[])
    data.update(overrides)
    errors = validate(data)
    if errors:
        raise AssertionError(errors)
    return Projection(**data, path='/unused/run.json', mtime=0)


def slice_row(ident='1', stage='implementing', gates=None, packages=None):
    return {'id': ident, 'name': 'Slice ' + ident, 'stage': stage,
            'gates': gates or [], 'packages': packages or []}


def package(ident, size='M', state='planned', **overrides):
    result = dict(id=ident, slice='1', title=ident, size=size, state=state,
                  dispatchId=None, machine=None, branch=None, blockedBy=[],
                  proofs=[], checkpointEvidence='', verifier='independent')
    result.update(overrides)
    return result


class GateMatrix(unittest.TestCase):
    def setUp(self):
        self.resolver = Resolver([], {}, {}, {})

    def build(self, **overrides):
        return build_matrix(projection(**overrides), self.resolver)

    def test_run_level_gate_fans_out_to_rows(self):
        matrix = self.build(
            gates=[{'id': 'goal', 'verdict': 'pass', 'at': '2026-10-19', 'ref': 'goal.md'}],
            slices=[slice_row('1'), slice_row('2')])
        self.assertEqual(len(matrix['rows']), 2)
        for row in matrix['rows']:
            self.assertEqual(row['cells']['goal'], {
                'verdict': 'pass', 'at': '2026-10-19', 'ref': 'goal.md', 'stale': None})

    def test_slice_gate_overrides_run_gate(self):
        matrix = self.build(
            gates=[{'id': 'design', 'verdict': 'pass', 'at': '2026-10-18', 'ref': 'run.md'}],
            slices=[slice_row('1', gates=[{'id': 'design', 'verdict': 'revise',
                                          'at': None}]), slice_row('2')])
        self.assertEqual(matrix['rows'][0]['cells']['design'], {
            'verdict': 'revise', 'at': None, 'ref': None, 'stale': None})
        self.assertEqual(matrix['rows'][1]['cells']['design']['ref'], 'run.md')

    def test_review_cell_has_four_chips_in_order(self):
        row = self.build()['rows'][0]
        self.assertEqual([chip['id'] for chip in row['cells']['review']['chips']],
                         ['test-quality', 'code-standards', 'commenting', 'general-code'])
        self.assertEqual([chip['verdict'] for chip in row['cells']['review']['chips']],
                         ['pending', 'pending', 'pending', 'pending'])

    def test_review_chips_inherit_and_override_evidence(self):
        row = self.build(
            gates=[{'id': 'general-code', 'verdict': 'pass', 'at': '2026-10-19'},
                   {'id': 'test-quality', 'verdict': 'pass', 'at': '2026-10-18'}],
            slices=[slice_row(gates=[{'id': 'test-quality', 'verdict': 'revise',
                                     'at': '2026-10-19', 'ref': 'tests.md'}])])['rows'][0]
        chips = row['cells']['review']['chips']
        self.assertEqual(chips[0], {'id': 'test-quality', 'verdict': 'revise',
                                   'at': '2026-10-19', 'ref': 'tests.md', 'stale': None})
        self.assertEqual(chips[3]['verdict'], 'pass')

    def test_verified_units_only_count_verified(self):
        row = self.build(packages=[package('P00', 'S', 'returned'),
                                   package('P01', 'M', 'verified')],
                         slices=[slice_row(packages=['P00', 'P01'])])['rows'][0]
        cell = row['cells']['implementing']
        self.assertEqual((cell['verified_units'], cell['total_units']), (2, 3))
        self.assertEqual(cell['segments'], [
            {'id': 'P00', 'size': 1, 'state': 'returned', 'node': None},
            {'id': 'P01', 'size': 2, 'state': 'verified', 'node': None}])

    def test_only_verified_state_earns_units(self):
        states = ['planned', 'assigned', 'running', 'returned', 'verified', 'blocked']
        packages = [package(str(i), 'L', state) for i, state in enumerate(states)]
        row = self.build(packages=packages,
                         slices=[slice_row(packages=[p['id'] for p in packages])])['rows'][0]
        cell = row['cells']['implementing']
        self.assertEqual((cell['verified_units'], cell['total_units']), (3, 18))

    def test_packages_follow_row_membership_and_order(self):
        row = self.build(packages=[package('P00'), package('P01'), package('P02')],
                         slices=[slice_row(packages=['P02', 'P00'])])['rows'][0]
        self.assertEqual([p['id'] for p in row['cells']['implementing']['segments']],
                         ['P02', 'P00'])

    def test_no_slices_gives_one_run_row(self):
        matrix = self.build(packages=[package('P00', 'S', 'verified')])
        self.assertEqual(len(matrix['rows']), 1)
        row = matrix['rows'][0]
        self.assertEqual((row['id'], row['name']), ('run_test', 'Review run'))
        self.assertEqual(row['cells']['implementing']['total_units'], 1)

    def test_run_row_stage_follows_consecutive_passed_gates(self):
        cases = [([], 'goal', [1, 0, 0, 0, 0, 0, 0]),
                 (['goal'], 'design', [1, 1, 0, 0, 0, 0, 0]),
                 (['goal', 'design'], 'plan', [1, 1, 1, 0, 0, 0, 0]),
                 (['goal', 'design', 'plan'], 'implementing', [1, 1, 1, 1, 0, 0, 0]),
                 (['design', 'plan'], 'goal', [1, 0, 0, 0, 0, 0, 0]),
                 (['goal', 'plan'], 'design', [1, 1, 0, 0, 0, 0, 0])]
        for gate_ids, stage, stepper in cases:
            with self.subTest(gates=gate_ids):
                row = self.build(gates=[{'id': ident, 'verdict': 'pass', 'at': None}
                                        for ident in gate_ids])['rows'][0]
                self.assertEqual((row['stage'], row['stepper']), (stage, stepper))

    def test_run_row_stage_stops_at_pending_or_revise(self):
        for verdict in ('pending', 'revise'):
            with self.subTest(verdict=verdict):
                row = self.build(gates=[{'id': 'goal', 'verdict': 'pass', 'at': None},
                                        {'id': 'design', 'verdict': verdict, 'at': None},
                                        {'id': 'plan', 'verdict': 'pass', 'at': None}])['rows'][0]
                self.assertEqual(row['stage'], 'design')

    def test_run_row_stage_is_review_for_any_review_gate_verdict(self):
        for gate_id in ('test-quality', 'code-standards', 'commenting', 'general-code'):
            for verdict in ('pending', 'revise', 'pass'):
                with self.subTest(gate=gate_id, verdict=verdict):
                    row = self.build(gates=[{'id': gate_id, 'verdict': verdict,
                                            'at': None}])['rows'][0]
                    self.assertEqual(row['stage'], 'review')

    def test_run_row_stage_delivery_requires_pass_and_precedes_review(self):
        for verdict, stage in [('pending', 'review'), ('revise', 'review'), ('pass', 'delivery')]:
            with self.subTest(verdict=verdict):
                row = self.build(gates=[{'id': 'general-code', 'verdict': 'pass', 'at': None},
                                        {'id': 'delivery', 'verdict': verdict, 'at': None}])['rows'][0]
                self.assertEqual(row['stage'], stage)

    def test_run_row_stage_acceptance_precedes_gate_evidence(self):
        for state in ('accepted', 'merged'):
            with self.subTest(state=state):
                row = self.build(acceptance={'state': state},
                                 gates=[{'id': 'delivery', 'verdict': 'pass', 'at': None}])['rows'][0]
                self.assertEqual(row['stage'], 'accepted')
                self.assertEqual(row['stepper'], [1, 1, 1, 1, 1, 1, 1])

    def test_stepper_for_review_stage(self):
        row = self.build(slices=[slice_row(stage='review')])['rows'][0]
        self.assertEqual(row['stage'], 'review')
        self.assertEqual(row['stepper'], [1, 1, 1, 1, 1, 0, 0])

    def test_stepper_boundaries(self):
        for stage, expected in [('goal', [1, 0, 0, 0, 0, 0, 0]),
                                ('accepted', [1, 1, 1, 1, 1, 1, 1])]:
            with self.subTest(stage=stage):
                row = self.build(slices=[slice_row(stage=stage)])['rows'][0]
                self.assertEqual(row['stepper'], expected)

    def test_cells_have_all_seven_columns_and_pending_defaults(self):
        cells = self.build()['rows'][0]['cells']
        self.assertEqual(list(cells), ['goal', 'design', 'plan', 'implementing',
                                      'review', 'delivery', 'accepted'])
        for stage in ('goal', 'design', 'plan', 'delivery'):
            self.assertEqual(cells[stage], {'verdict': 'pending', 'at': None,
                                           'ref': None, 'stale': None})
        self.assertEqual(cells['implementing'], {
            'segments': [], 'verified_units': 0, 'total_units': 0})

    def test_accepted_uses_acceptance_state_in_every_row(self):
        for state in ('pending', 'accepted', 'merged'):
            with self.subTest(state=state):
                matrix = self.build(acceptance={'state': state},
                                    slices=[slice_row('1'), slice_row('2', stage='accepted')])
                self.assertEqual([row['cells']['accepted']['state'] for row in matrix['rows']],
                                 [state, state])

    def test_waiting_counts_all_b_c_d_entries_without_merge_gate_double_counting(self):
        decisions = [dict(id='d' + str(i), **{'class': kind}, text='Decision', **extra)
                     for i, (kind, extra) in enumerate([
                         ('B', {'applyAt': '2026-10-18T12:00:00Z'}),
                         ('B', {'applyAt': '2026-10-21T12:00:00Z'}),
                         ('B', {}), ('C', {}), ('D', {})])]
        matrix = self.build(decisions=decisions,
                            mergeGate={'ready': False, 'classDOpen': 1, 'classBUnratified': 3})
        self.assertEqual(matrix['waiting'], 5)
        self.assertEqual(matrix['stalled'], 0)
        self.assertEqual(self.build()['waiting'], 0)

    def test_dispatches_resolve_across_hosts_and_unresolved_nodes_stay_null(self):
        self.resolver = Resolver([], {
            'local': [{'handle': 'term_local'}],
            'laptop2': [{'handle': 'term_remote'}]}, {
            'local': [{'dispatchId': 'ctx_remote', 'agentTerminalHandle': 'term_remote'},
                      {'dispatchId': 'ctx_local', 'agentTerminalHandle': 'term_local'}]}, {})
        row = self.build(packages=[
            package('P00', state='running', dispatchId='ctx_remote', machine='laptop2'),
            package('P01', state='running', dispatchId='ctx_local'),
            package('P02', state='running', dispatchId='ctx_missing', machine='laptop2'),
            package('P03')])['rows'][0]
        self.assertEqual([p['node'] for p in row['cells']['implementing']['segments']],
                         ['env:laptop2:term:term_remote', 'local:term:term_local', None, None])
        self.assertEqual(row['live'], ['env:laptop2:term:term_remote', 'local:term:term_local'])

    def test_chief_resolves_to_session_or_remote_terminal(self):
        session = LocalSession(
            pid=1, session_id='chief', name='Chief', cwd='/work', status='idle',
            started_at=0, status_updated_at=0, transcript=None, orca_pane=('tab', 'leaf'),
            hook_state=None, kitty_key=None, ctx_pct=None, cost=None, subagents=[])
        self.resolver = Resolver([session], {
            'local': [{'handle': 'term_chief', 'tabId': 'tab', 'leafId': 'leaf'}],
            'laptop2': [{'handle': 'term_remote'}]}, {}, {})
        self.assertEqual(self.build()['chief_node'], 'local:sid:chief')
        self.assertEqual(self.build(chiefTerminal='term_remote')['chief_node'],
                         'env:laptop2:term:term_remote')
        self.assertIsNone(self.build(chiefTerminal='')['chief_node'])

    def test_live_includes_resolved_dispatches_in_every_state_once(self):
        self.resolver = Resolver([], {}, {'local': [
            {'dispatchId': 'ctx_shared', 'agentTerminalHandle': 'term_worker'}]}, {})
        for state in ('planned', 'assigned', 'running', 'returned', 'verified', 'blocked'):
            with self.subTest(state=state):
                row = self.build(packages=[
                    package('P00', state=state, dispatchId='ctx_shared'),
                    package('P01', state=state, dispatchId='ctx_shared')])['rows'][0]
                self.assertEqual(row['live'], ['local:term:term_worker'])

    def test_real_projection_fixture(self):
        data = json.loads(FIXTURE.read_text())
        self.assertEqual(validate(data), [])
        matrix = build_matrix(Projection(**data, path=str(FIXTURE), mtime=0), self.resolver)
        self.assertEqual((matrix['run'], matrix['title'], matrix['now']),
                         (data['run'], 'Handoff scheduling', data['now']))
        self.assertEqual(matrix['proofs'], data['proofs'])
        self.assertEqual(matrix['merge_gate'], data['mergeGate'])
        self.assertEqual(matrix['waiting'], 1)
        self.assertEqual(matrix['notes'], [])
        self.assertEqual([row['name'] for row in matrix['rows']],
                         ['Statuses and history', 'AE settings', 'Automatic AE assignment'])
        self.assertEqual([(row['cells']['implementing']['verified_units'],
                           row['cells']['implementing']['total_units'])
                          for row in matrix['rows']], [(5, 16), (7, 7), (7, 16)])
        self.assertEqual(matrix['rows'][1]['cells']['review']['chips'][3]['verdict'], 'pass')

    def test_build_does_not_modify_projection(self):
        p = projection(**json.loads(FIXTURE.read_text()))
        before = copy.deepcopy(asdict(p))
        build_matrix(p, self.resolver)
        self.assertEqual(asdict(p), before)

    def test_unknown_size_uses_one_unit_and_adds_a_note(self):
        p = projection(packages=[package('P00', 'S', 'verified')])
        p.packages[0]['size'] = 'XL'
        matrix = build_matrix(p, self.resolver)
        cell = matrix['rows'][0]['cells']['implementing']
        self.assertEqual((cell['verified_units'], cell['total_units']), (1, 1))
        self.assertEqual(cell['segments'][0]['size'], 1)
        self.assertEqual(matrix['notes'], ['package P00: unknown size XL; using weight 1'])

    def test_dangling_package_reference_is_skipped_with_a_note(self):
        p = projection(packages=[package('P00', 'M', 'verified')],
                       slices=[slice_row(packages=['P00'])])
        p.slices[0]['packages'].insert(0, 'missing')
        matrix = build_matrix(p, self.resolver)
        cell = matrix['rows'][0]['cells']['implementing']
        self.assertEqual([segment['id'] for segment in cell['segments']], ['P00'])
        self.assertEqual((cell['verified_units'], cell['total_units']), (2, 2))
        self.assertEqual(matrix['notes'], ['slice 1: unknown package missing; skipped'])

    def test_invalid_stages_fall_back_to_goal_with_notes(self):
        for stage in ('shipping', [], {}, None, 42):
            with self.subTest(stage=stage):
                p = projection(slices=[slice_row()])
                p.slices[0]['stage'] = stage
                matrix = build_matrix(p, self.resolver)
                row = matrix['rows'][0]
                self.assertEqual(row['stage'], 'goal')
                self.assertEqual(row['stepper'], [1, 0, 0, 0, 0, 0, 0])
                self.assertTrue(any('stage' in note for note in matrix['notes']))

    def test_non_string_sizes_use_one_unit_with_notes(self):
        for size in ([], {}, None, 42, True):
            with self.subTest(size=size):
                p = projection(packages=[package('P00', state='verified')])
                p.packages[0]['size'] = size
                matrix = build_matrix(p, self.resolver)
                cell = matrix['rows'][0]['cells']['implementing']
                self.assertEqual((cell['verified_units'], cell['total_units']), (1, 1))
                self.assertEqual(cell['segments'][0]['size'], 1)
                self.assertTrue(any('size' in note for note in matrix['notes']))

    def test_malformed_packages_are_skipped_without_losing_valid_packages(self):
        bad_records = [None, [], 'package', {}, {'id': []}]
        for field in package('bad'):
            record = package('bad')
            del record[field]
            bad_records.append(record)
        for field, value in [('id', []), ('state', []), ('state', 'unknown'),
                             ('dispatchId', []), ('machine', {}), ('blockedBy', None)]:
            record = package('bad')
            record[field] = value
            bad_records.append(record)
        for bad in bad_records:
            with self.subTest(record=bad):
                p = projection(packages=[package('P00', 'M', 'verified')])
                p.packages.insert(0, bad)
                matrix = build_matrix(p, self.resolver)
                cell = matrix['rows'][0]['cells']['implementing']
                self.assertEqual([segment['id'] for segment in cell['segments']], ['P00'])
                self.assertEqual((cell['verified_units'], cell['total_units']), (2, 2))
                self.assertTrue(any('packages[0]' in note for note in matrix['notes']))

    def test_malformed_slices_are_skipped_without_losing_valid_rows(self):
        bad_records = [None, [], 'slice', {}, {'id': []}]
        for field in slice_row('bad'):
            record = slice_row('bad')
            del record[field]
            bad_records.append(record)
        for field, value in [('id', []), ('name', {}), ('gates', None),
                             ('packages', None), ('packages', [[]])]:
            record = slice_row('bad')
            record[field] = value
            bad_records.append(record)
        for bad in bad_records:
            with self.subTest(record=bad):
                p = projection(slices=[slice_row()])
                p.slices.insert(0, bad)
                matrix = build_matrix(p, self.resolver)
                self.assertEqual([row['id'] for row in matrix['rows']], ['1'])
                self.assertTrue(any('slices[0]' in note for note in matrix['notes']))

    def test_malformed_gates_are_skipped_at_run_and_slice_scope(self):
        for bad in (None, [], {}, {'id': []},
                    {'id': 'goal', 'verdict': [], 'at': None}):
            for sliced in (False, True):
                with self.subTest(gate=bad, sliced=sliced):
                    p = projection(slices=[slice_row()] if sliced else [])
                    p.gates = [bad, {'id': 'goal', 'verdict': 'pass', 'at': None}]
                    if sliced:
                        p.slices[0]['gates'] = [bad]
                    matrix = build_matrix(p, self.resolver)
                    self.assertEqual(matrix['rows'][0]['cells']['goal']['verdict'], 'pass')
                    self.assertTrue(matrix['notes'])

    def test_malformed_projection_containers_have_safe_defaults(self):
        for field in ('packages', 'slices', 'gates', 'acceptance', 'decisions',
                      'proofs', 'mergeGate'):
            for value in (None, 42, 'bad'):
                with self.subTest(field=field, value=value):
                    p = projection()
                    setattr(p, field, value)
                    matrix = build_matrix(p, self.resolver)
                    self.assertEqual(matrix['rows'][0]['stage'], 'goal')
                    self.assertEqual(matrix['waiting'], 0)
                    self.assertTrue(matrix['notes'])

    def test_malformed_header_records_are_skipped_or_defaulted(self):
        p = projection()
        p.acceptance = {'state': []}
        p.decisions = [None, {}, {'class': []}, {'class': 'C'}]
        p.proofs = [None, {}, {'id': []}, {'id': 'E1', 'status': 'pass'}]
        p.chiefTerminal = []
        matrix = build_matrix(p, self.resolver)
        self.assertEqual(matrix['rows'][0]['cells']['accepted'], {'state': 'pending'})
        self.assertEqual(matrix['waiting'], 1)
        self.assertEqual(matrix['proofs'], [{'id': 'E1', 'status': 'pass'}])
        self.assertIsNone(matrix['chief_node'])
        self.assertTrue(matrix['notes'])


if __name__ == '__main__':
    unittest.main()

from __future__ import annotations

"""Initiative precedence and config persistence through public interfaces."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.clusters import ClusterConfig, cluster_for, load, save_assign
from fleetmap import clusters


class InitiativeClusters(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fleetmap-clusters-')
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'config' / 'fleet-map.json'

    def test_assign_beats_everything(self):
        cfg = ClusterConfig(initiatives=[("Commissions", ["commission"])], assign={"local:sid:s1": "Handoff"})
        self.assertEqual(cluster_for("local:sid:s1", run_objective="Commissions audit", title="commission",
                                     purpose="", worktree="", branch="", config=cfg), "Handoff")

    def test_run_objective_is_cut_at_colon(self):
        self.assertEqual(cluster_for("x", run_objective="Engineering OS run 20261015-handoff-scheduling: design", title="",
                                     purpose="", worktree="", branch="", config=ClusterConfig([], {})),
                         "Engineering OS run 20261015-handoff-scheduling")

    def test_match_is_case_insensitive_substring_over_four_fields(self):
        cfg = ClusterConfig(initiatives=[("PR 6869 review", ["pr-6869"])], assign={})
        self.assertEqual(cluster_for("x", run_objective=None, title="", purpose="", worktree="",
                                     branch="refs/heads/DMHoodoo/PR-6869-review-chief", config=cfg), "PR 6869 review")

    def test_worktree_rule_names_branch_segment(self):
        self.assertEqual(cluster_for("x", run_objective=None, title="", purpose="", worktree="/w/lookdown",
                                     branch="refs/heads/hok/handoff-l2", config=ClusterConfig([], {})), "handoff-l2")

    def test_unsorted_when_nothing_matches(self):
        self.assertEqual(cluster_for("x", run_objective=None, title="", purpose="", worktree="", branch="",
                                     config=ClusterConfig([], {})), "Unsorted")

    def test_save_assign_round_trips(self):
        save_assign("local:sid:s1", "Commissions", path=self.path)
        self.assertEqual(load(self.path).assign, {"local:sid:s1": "Commissions"})

    def cluster(self, config=None, node_id='x', **fields):
        values = dict(run_objective=None, title='', purpose='', worktree='', branch='')
        values.update(fields)
        return cluster_for(node_id, config=config or ClusterConfig([], {}), **values)

    def test_missing_file_loads_empty_config_without_creating_file(self):
        self.assertEqual(load(path=self.path), ClusterConfig([], {}))
        self.assertFalse(self.path.exists())

    def test_load_preserves_initiative_order_and_normalizes_bare_session_ids(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({
            'initiatives': [{'name': 'First', 'match': ['alpha', 'beta']},
                            {'name': 'Second', 'match': ['beta']}],
            'assign': {'s1': 'Pinned', 'env:laptop2:term:t1': 'Remote'}}))
        self.assertEqual(load(self.path), ClusterConfig(
            [('First', ['alpha', 'beta']), ('Second', ['beta'])],
            {'local:sid:s1': 'Pinned', 'env:laptop2:term:t1': 'Remote'}))

    def test_save_preserves_other_keys_and_existing_assignments(self):
        self.path.parent.mkdir()
        original = {'initiatives': [{'name': 'Commissions', 'match': ['commission']}],
                    'assign': {'local:sid:s1': 'Old', 'env:laptop2:term:t1': 'Remote'},
                    'layout': {'zoom': 2}, 'future': [None, True, 'café']}
        self.path.write_text(json.dumps(original))
        save_assign('s1', 'New', path=self.path)
        original['assign']['local:sid:s1'] = 'New'
        self.assertEqual(json.loads(self.path.read_text()), original)

    def test_bare_session_ids_work_in_config_and_lookup(self):
        for assignments in ({'s1': 'Pinned'}, {'local:sid:s1': 'Pinned'}):
            for node_id in ('s1', 'local:sid:s1'):
                with self.subTest(assignments=assignments, node_id=node_id):
                    self.assertEqual(self.cluster(ClusterConfig([], assignments),
                                                  node_id=node_id), 'Pinned')

    def test_canonical_assignment_beats_bare_alias(self):
        cfg = ClusterConfig([], {'s1': 'Alias', 'local:sid:s1': 'Canonical'})
        self.assertEqual(self.cluster(cfg, node_id='s1'), 'Canonical')

    def test_objective_beats_patterns_and_worktree(self):
        cfg = ClusterConfig([('Pattern', ['match'])], {})
        self.assertEqual(self.cluster(cfg, run_objective='Run; details: more',
                                      title='match', worktree='/w', branch='topic'), 'Run')

    def test_objective_cuts_at_first_delimiter_and_sixty_characters(self):
        for objective, expected in (
                ('Alpha: beta; gamma', 'Alpha'), ('Alpha; beta: gamma', 'Alpha'),
                ('123456789012345678901234567890123456789012345678901234567890EXTRA',
                 '123456789012345678901234567890123456789012345678901234567890')):
            with self.subTest(objective=objective):
                self.assertEqual(self.cluster(run_objective=objective), expected)

    def test_first_matching_initiative_wins_in_each_field(self):
        cfg = ClusterConfig([('First', ['absent', 'needle']), ('Second', ['needle'])], {})
        for field in ('title', 'purpose', 'worktree', 'branch'):
            with self.subTest(field=field):
                self.assertEqual(self.cluster(cfg, **{field: 'prefix-NEEDLE-suffix'}), 'First')

    def test_empty_objective_falls_through(self):
        self.assertEqual(self.cluster(run_objective='', worktree='/w', branch='topic'), 'topic')

    def test_worktree_and_branch_are_both_required(self):
        for worktree, branch in (('', 'topic'), ('/w', ''), ('', '')):
            with self.subTest(worktree=worktree, branch=branch):
                self.assertEqual(self.cluster(worktree=worktree, branch=branch), 'Unsorted')

    def test_worktree_branch_prefix_and_nested_segment(self):
        for branch in ('refs/heads/hok/topic', 'hok/topic', 'refs/heads/topic', 'topic'):
            with self.subTest(branch=branch):
                self.assertEqual(self.cluster(worktree='/w', branch=branch), 'topic')

    def write_config(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding='utf-8')

    def test_projection_cluster_beats_assign(self):
        cfg = ClusterConfig([('Matched', ['needle'])], {'local:sid:s1': 'Pinned'})
        self.assertEqual(self.cluster(cfg, node_id='s1', projection_cluster='Run projection',
                                      run_objective='Old run', title='needle',
                                      worktree='/w', branch='topic'), 'Run projection')

    def test_bare_session_id_in_assign_is_accepted(self):
        self.write_config({'assign': {'s1': 'Pinned'}})
        cfg = load(self.path)
        self.assertEqual(cfg.assign, {'local:sid:s1': 'Pinned'})
        self.assertEqual(self.cluster(cfg, node_id='local:sid:s1'), 'Pinned')

    def test_promote_writes_assign_and_project_together(self):
        clusters.promote('s1', 'Core lint speed', 'root cause 6962', 'review', path=self.path)
        cfg = load(self.path)
        self.assertEqual(cfg.assign, {'local:sid:s1': 'Core lint speed'})
        self.assertEqual(cfg.projects, [{'name': 'Core lint speed', 'slices': [
            {'name': 'root cause 6962', 'stage': 'review', 'sessions': ['local:sid:s1']}]}])
        self.assertEqual(clusters.stage_for('s1', cfg), 'review')

    def test_move_to_non_project_drops_project_entry(self):
        clusters.promote('s1', 'Core lint speed', 'root cause 6962', 'review', path=self.path)
        clusters.move('local:sid:s1', 'Commissions', self.path)
        cfg = load(self.path)
        self.assertEqual(self.cluster(cfg, node_id='s1'), 'Commissions')
        self.assertIsNone(clusters.stage_for('s1', cfg))
        self.assertFalse(any('local:sid:s1' in item['sessions']
                             for project in cfg.projects for item in project['slices']))

    def test_never_prompted_session_is_unsorted_not_branch(self):
        self.assertEqual(self.cluster(purpose=None, worktree='/w', branch='topic'), 'Unsorted')

    def test_never_prompted_session_can_still_be_explicitly_clustered_or_matched(self):
        cfg = ClusterConfig([('Matched', ['needle'])], {'local:sid:s1': 'Pinned'})
        self.assertEqual(self.cluster(cfg, node_id='s1', purpose=None), 'Pinned')
        self.assertEqual(self.cluster(cfg, purpose=None, title='needle'), 'Matched')
        self.assertEqual(self.cluster(purpose=None, projection_cluster='Projected'), 'Projected')

    def test_reference_j_config_and_bare_project_sessions_load(self):
        self.write_config({
            'projects': [{'name': 'Core lint speed', 'slices': [
                {'name': 'root cause 6962', 'stage': 'review',
                 'sessions': ['s1', 'env:laptop2:term:t1']}]}],
            'hosts': {'laptop2': {'ssh': 'hok@Hassans-MacBook-Pro.local'}},
            'caps': {'laptop2': 7, 'local': 3}})
        cfg = load(self.path)
        self.assertEqual(cfg.hosts, {'laptop2': {'ssh': 'hok@Hassans-MacBook-Pro.local'}})
        self.assertEqual(cfg.caps, {'laptop2': 7, 'local': 3})
        self.assertEqual(cfg.projects[0]['slices'][0]['sessions'],
                         ['local:sid:s1', 'env:laptop2:term:t1'])
        for node_id in ('s1', 'local:sid:s1', 'env:laptop2:term:t1'):
            with self.subTest(node_id=node_id):
                self.assertEqual(self.cluster(cfg, node_id=node_id, run_objective='Old run'),
                                 'Core lint speed')
                self.assertEqual(clusters.stage_for(node_id, cfg), 'review')
        self.assertIsNone(clusters.stage_for('missing', cfg))

    def test_v2_defaults_are_empty_and_independent(self):
        first, second = ClusterConfig([], {}), ClusterConfig([], {})
        self.assertEqual((first.projects, first.hosts, first.caps), ([], {}, {}))
        first.projects.append({'name': 'Project'})
        first.hosts['local'] = {}
        first.caps['local'] = 3
        self.assertEqual((second.projects, second.hosts, second.caps), ([], {}, {}))

    def test_assign_beats_project_and_projection_beats_both(self):
        clusters.promote('s1', 'Core lint speed', 'root cause 6962', 'review', self.path)
        save_assign('s1', 'Pinned', self.path)
        cfg = load(self.path)
        self.assertEqual(self.cluster(cfg, node_id='s1'), 'Pinned')
        self.assertEqual(self.cluster(cfg, node_id='s1', projection_cluster='Run'), 'Run')

    def test_promote_updates_existing_slice_without_duplicates_or_losing_peers(self):
        clusters.promote('s1', 'Core lint speed', 'root cause 6962', 'plan', self.path)
        clusters.promote('env:laptop2:term:t1', 'Core lint speed', 'root cause 6962',
                         'review', self.path)
        clusters.promote('s1', 'Core lint speed', 'root cause 6962', 'delivery', self.path)
        cfg = load(self.path)
        self.assertEqual(cfg.projects, [{'name': 'Core lint speed', 'slices': [
            {'name': 'root cause 6962', 'stage': 'delivery',
             'sessions': ['local:sid:s1', 'env:laptop2:term:t1']}]}])
        self.assertEqual(clusters.stage_for('env:laptop2:term:t1', cfg), 'delivery')

    def test_repromotion_moves_membership_and_preserves_peer_stage(self):
        clusters.promote('s1', 'Old', 'Old slice', 'plan', self.path)
        clusters.promote('s2', 'Old', 'Old slice', 'plan', self.path)
        clusters.promote('s1', 'New', 'New slice', 'review', self.path)
        cfg = load(self.path)
        self.assertEqual(clusters.stage_for('s1', cfg), 'review')
        self.assertEqual(clusters.stage_for('s2', cfg), 'plan')
        self.assertEqual(cfg.projects[0]['slices'][0]['sessions'], ['local:sid:s2'])

    def test_move_removes_bare_aliases_from_all_slices_preserving_peers(self):
        self.write_config({'assign': {'s1': 'Old'}, 'projects': [
            {'name': 'Old', 'slices': [{'name': 'One', 'stage': 'review',
                                      'sessions': ['s1', 's2']} ]},
            {'name': 'Other', 'slices': [{'name': 'Two', 'stage': 'plan',
                                        'sessions': ['local:sid:s1']}]}]})
        clusters.move('s1', 'Unsorted', self.path)
        cfg = load(self.path)
        self.assertEqual(self.cluster(cfg, node_id='s1'), 'Unsorted')
        self.assertIsNone(clusters.stage_for('s1', cfg))
        self.assertEqual(clusters.stage_for('s2', cfg), 'review')

    def test_move_to_project_retains_project_entries(self):
        clusters.promote('s1', 'Core lint speed', 'root cause 6962', 'review', self.path)
        before = load(self.path).projects
        clusters.move('s1', 'Core lint speed', self.path)
        self.assertEqual(load(self.path).projects, before)
        self.assertEqual(clusters.stage_for('s1', load(self.path)), 'review')

    def test_config_mutations_preserve_unowned_values(self):
        untouched = {'hosts': {'laptop2': {'ssh': 'hok@Hassans-MacBook-Pro.local'}},
                     'caps': {'laptop2': 7, 'local': 3}, 'future': [None, True, 'café'],
                     'initiatives': [{'name': 'Commissions', 'match': ['commission']} ]}
        self.write_config(dict(untouched, assign={'env:laptop2:term:t1': 'Remote'}))
        for mutate in (lambda: clusters.promote('s1', 'Project', 'Slice', 'review', self.path),
                       lambda: clusters.move('s1', 'Unsorted', self.path),
                       lambda: save_assign('s1', 'Pinned', self.path)):
            mutate()
            saved = json.loads(self.path.read_text())
            self.assertEqual({key: saved[key] for key in untouched}, untouched)
            self.assertEqual(saved['assign']['env:laptop2:term:t1'], 'Remote')

    def test_failed_atomic_replace_preserves_original_and_cleans_temp_files(self):
        for operation in ('promote', 'move', 'save_assign'):
            with self.subTest(operation=operation):
                self.write_config({'assign': {'s1': 'Old'}, 'future': True})
                before = self.path.read_bytes()
                with patch('os.replace', side_effect=OSError('replace failed')):
                    with self.assertRaises(OSError):
                        if operation == 'promote':
                            clusters.promote('s1', 'Project', 'Slice', 'review', self.path)
                        elif operation == 'move':
                            clusters.move('s1', 'New', self.path)
                        else:
                            save_assign('s1', 'New', self.path)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_invalid_json_is_not_overwritten(self):
        self.path.parent.mkdir()
        self.path.write_text('{broken', encoding='utf-8')
        for mutate in (lambda: clusters.promote('s1', 'Project', 'Slice', 'review', self.path),
                       lambda: clusters.move('s1', 'New', self.path),
                       lambda: save_assign('s1', 'New', self.path)):
            with self.assertRaises(json.JSONDecodeError):
                mutate()
            self.assertEqual(self.path.read_text(), '{broken')


if __name__ == '__main__':
    unittest.main()

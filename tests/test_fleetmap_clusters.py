"""Initiative precedence and config persistence through public interfaces."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.clusters import ClusterConfig, cluster_for, load, save_assign


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


if __name__ == '__main__':
    unittest.main()

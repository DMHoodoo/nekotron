from __future__ import annotations

"""Exercise ladder derivation at the git and GitHub executable boundaries."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.ladder import Ladder, never_prompted


class OneOffLadder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fleetmap-ladder-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.worktree = self.base / 'work tree'
        self.worktree.mkdir()
        (self.worktree / '.git').write_text('gitdir: /fake/worktree\n')
        self.log = self.base / 'calls.jsonl'
        self.config = self.base / 'responses.json'
        self.responses = {
            'symbolic-ref': {'stdout': 'refs/remotes/origin/main\n'},
            'rev-parse': {'stdout': 'abc123\n'},
            'rev-list': {'stdout': '0\n'},
            'gh': {'stdout': '[]'},
        }
        self.save()
        self.git = self.tool('git')
        self.gh = self.tool('gh')
        self.ladder = Ladder(git=self.git, gh=self.gh, ttl=0)

    def save(self):
        self.config.write_text(json.dumps(self.responses))

    def tool(self, name):
        path = self.base / name
        path.write_text(
            '#!' + sys.executable + '\n'
            'from __future__ import annotations\n'
            'import json, os, sys, time\n'
            f'with open({str(self.log)!r}, "a") as log:\n'
            f'    log.write(json.dumps([{name!r}, os.getcwd(), sys.argv[1:]]) + "\\n")\n'
            f'with open({str(self.config)!r}) as config:\n'
            '    responses = json.load(config)\n'
            f'key = "gh" if {name!r} == "gh" else sys.argv[1]\n'
            'response = responses.get(" ".join(sys.argv[1:]), responses[key])\n'
            'time.sleep(response.get("sleep", 0))\n'
            'sys.stdout.write(response.get("stdout", ""))\n'
            'sys.exit(response.get("code", 0))\n')
        path.chmod(0o755)
        return str(path)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def rung(self, branch='feature'):
        return self.ladder.rung(str(self.worktree), branch)

    def set_pr(self, state='OPEN', checks=None, draft=False):
        self.responses['gh']['stdout'] = json.dumps([{
            'number': 42, 'state': state, 'isDraft': draft,
            'statusCheckRollup': checks,
        }])
        self.save()

    def test_no_commits_ahead_is_asked(self):
        self.assertEqual(self.rung(), {'rung': 'asked', 'ahead': 0, 'pr': None})

    def test_commits_ahead_without_pr_is_working(self):
        self.responses['rev-list']['stdout'] = '3\n'
        self.save()
        self.assertEqual(self.rung(), {'rung': 'working', 'ahead': 3, 'pr': None})

    def test_open_pr_with_green_checks_is_pr(self):
        self.set_pr(checks=[{'status': 'COMPLETED', 'conclusion': 'SUCCESS'}], draft=True)
        self.assertEqual(self.rung(), {
            'rung': 'pr', 'ahead': 0,
            'pr': {'number': 42, 'state': 'OPEN', 'isDraft': True, 'checks': 'pass'},
        })

    def test_merged_pr_is_merged(self):
        self.set_pr(state='MERGED')
        self.assertEqual(self.rung(), {
            'rung': 'merged', 'ahead': 0,
            'pr': {'number': 42, 'state': 'MERGED', 'isDraft': False, 'checks': 'none'},
        })

    def test_closed_pr_does_not_advance_the_ladder(self):
        self.set_pr(state='CLOSED')
        self.assertEqual(self.rung()['rung'], 'asked')
        self.responses['rev-list']['stdout'] = '2'
        self.save()
        self.assertEqual(self.rung()['rung'], 'working')

    def test_checks_roll_up_failure_pending_pass_and_none(self):
        cases = [
            ([], 'none'),
            ([{'state': 'SUCCESS'}], 'pass'),
            ([{'state': 'PENDING'}], 'pending'),
            ([{'state': 'ERROR'}], 'fail'),
            ([{'state': 'FAILURE'}, {'state': 'PENDING'}], 'fail'),
            ([{'status': 'QUEUED', 'conclusion': None}], 'pending'),
            ([{'status': 'IN_PROGRESS', 'conclusion': ''},
              {'status': 'COMPLETED', 'conclusion': 'SUCCESS'}], 'pending'),
            ([{'status': 'COMPLETED', 'conclusion': 'NEUTRAL'},
              {'status': 'COMPLETED', 'conclusion': 'SKIPPED'}], 'pass'),
        ]
        for conclusion in ('FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STALE'):
            cases.append(([{'status': 'COMPLETED', 'conclusion': conclusion}], 'fail'))
        for checks, expected in cases:
            with self.subTest(checks=checks):
                self.set_pr(checks=checks)
                self.assertEqual(self.rung()['pr']['checks'], expected)

    def test_failing_gh_keeps_previous_value_and_does_not_raise(self):
        self.set_pr()
        previous = self.rung()
        self.responses['rev-list']['stdout'] = '9'
        self.responses['gh']['code'] = 1
        self.save()
        self.assertEqual(self.rung(), previous)

    def test_failed_command_without_cache_is_asked(self):
        for command in ('rev-list', 'gh'):
            with self.subTest(command=command):
                self.responses[command]['code'] = 1
                self.save()
                self.assertEqual(self.rung(command), {'rung': 'asked', 'ahead': 0, 'pr': None})
                self.responses[command]['code'] = 0

    def test_git_failure_keeps_previous_value(self):
        self.set_pr(state='MERGED')
        previous = self.rung()
        self.responses['rev-list']['code'] = 1
        self.save()
        self.assertEqual(self.rung(), previous)

    def test_missing_executable_is_asked(self):
        ladder = Ladder(git=str(self.base / 'missing'), gh=self.gh)
        self.assertEqual(ladder.rung(str(self.worktree), 'feature'),
                         {'rung': 'asked', 'ahead': 0, 'pr': None})

    def test_invalid_output_preserves_previous_value(self):
        self.set_pr()
        previous = self.rung()
        for command, output in (('rev-list', 'not a count'), ('rev-list', '-1'),
                                ('gh', 'not JSON'), ('gh', '{}'), ('gh', '[{}]')):
            with self.subTest(command=command, output=output):
                original = self.responses[command]['stdout']
                self.responses[command]['stdout'] = output
                self.save()
                self.assertEqual(self.rung(), previous)
                self.responses[command]['stdout'] = original

    def test_timeout_keeps_previous_value(self):
        self.set_pr()
        previous = self.rung()
        self.responses['gh']['sleep'] = 10
        self.save()
        start = time.monotonic()
        self.assertEqual(self.rung(), previous)
        self.assertLess(time.monotonic() - start, 8)

    def test_cache_ttl_prevents_second_call(self):
        self.ladder = Ladder(git=self.git, gh=self.gh)
        with patch('fleetmap.ladder.time.monotonic', return_value=100):
            previous = self.rung()
        count = len(self.calls())
        self.set_pr()
        with patch('fleetmap.ladder.time.monotonic', return_value=159):
            self.assertEqual(self.rung(), previous)
        self.assertEqual(len(self.calls()), count)
        with patch('fleetmap.ladder.time.monotonic', return_value=160):
            self.assertEqual(self.rung()['rung'], 'pr')

    def test_cache_is_scoped_to_worktree_and_branch(self):
        self.ladder = Ladder(git=self.git, gh=self.gh)
        self.rung()
        self.set_pr()
        self.assertEqual(self.rung('other')['rung'], 'pr')
        other = self.base / 'other'
        other.mkdir()
        (other / '.git').mkdir()
        self.assertEqual(self.ladder.rung(str(other), 'feature')['rung'], 'pr')
        self.assertEqual(self.rung()['rung'], 'asked')

    def test_no_branch_or_git_directory_is_asked_without_commands(self):
        self.assertEqual(self.rung(None), {'rung': 'asked', 'ahead': 0, 'pr': None})
        (self.worktree / '.git').unlink()
        self.assertEqual(self.rung(), {'rung': 'asked', 'ahead': 0, 'pr': None})
        self.assertFalse(self.log.exists())

    def test_commands_use_worktree_and_literal_branch(self):
        branch = 'feature; $(echo unsafe)'
        self.rung(branch)
        calls = self.calls()
        self.assertTrue(all(call[1] == str(self.worktree) for call in calls))
        self.assertIn(['git', str(self.worktree),
                       ['symbolic-ref', 'refs/remotes/origin/HEAD']], calls)
        self.assertIn(['git', str(self.worktree),
                       ['rev-list', '--count', 'origin/HEAD..HEAD']], calls)
        self.assertIn(['gh', str(self.worktree), [
            'pr', 'list', '--head', branch, '--state', 'all', '--json',
            'number,state,isDraft,statusCheckRollup', '--limit', '1']], calls)

    def test_default_branch_is_resolved_once_per_worktree(self):
        self.rung()
        self.rung('other')
        calls = [call for call in self.calls() if call[2][0] == 'symbolic-ref']
        self.assertEqual(len(calls), 1)

    def test_missing_origin_head_uses_only_unambiguous_fallback(self):
        self.responses['symbolic-ref']['code'] = 1
        for default in ('master', 'main'):
            with self.subTest(default=default):
                self.ladder = Ladder(git=self.git, gh=self.gh)
                for name in ('master', 'main'):
                    self.responses['rev-parse --verify refs/remotes/origin/' + name] = {
                        'code': 0 if default == name else 1, 'stdout': 'abc123'}
                self.responses['rev-list']['stdout'] = '2'
                self.save()
                self.assertEqual(self.rung()['rung'], 'working')
                self.assertIn(['git', str(self.worktree),
                               ['rev-list', '--count', 'origin/' + default + '..HEAD']],
                              self.calls())

    def test_ambiguous_fallback_without_previous_value_is_asked(self):
        self.responses['symbolic-ref']['code'] = 1
        self.responses['rev-list']['stdout'] = '9'
        self.save()
        self.assertEqual(self.rung(), {'rung': 'asked', 'ahead': 0, 'pr': None})

    def test_ambiguous_fallback_retains_previous_value_and_recovers(self):
        self.responses['symbolic-ref']['code'] = 1
        self.responses['rev-parse --verify refs/remotes/origin/main'] = {'code': 1}
        self.responses['rev-list']['stdout'] = '2'
        self.save()
        previous = self.rung()
        self.assertEqual(previous, {'rung': 'working', 'ahead': 2, 'pr': None})

        self.responses['rev-parse --verify refs/remotes/origin/main']['code'] = 0
        self.responses['rev-list']['stdout'] = '9'
        self.save()
        self.assertEqual(self.rung(), previous)

        self.responses['symbolic-ref'] = {'stdout': 'refs/remotes/origin/develop\n'}
        self.responses['rev-list --count origin/HEAD..HEAD'] = {'stdout': '0'}
        self.save()
        self.assertEqual(self.rung(), {'rung': 'asked', 'ahead': 0, 'pr': None})

    def test_fallback_is_replaced_by_repaired_origin_head_after_ttl(self):
        self.ladder = Ladder(git=self.git, gh=self.gh)
        self.responses['symbolic-ref']['code'] = 1
        self.responses['rev-parse --verify refs/remotes/origin/main'] = {'code': 1}
        self.responses['rev-list']['stdout'] = '2'
        self.save()
        with patch('fleetmap.ladder.time.monotonic', return_value=100):
            previous = self.rung()
        self.assertEqual(previous, {'rung': 'working', 'ahead': 2, 'pr': None})

        self.responses['symbolic-ref'] = {'stdout': 'refs/remotes/origin/develop\n'}
        self.responses['rev-list --count origin/HEAD..HEAD'] = {'stdout': '0'}
        self.save()
        with patch('fleetmap.ladder.time.monotonic', return_value=159):
            self.assertEqual(self.rung(), previous)
        with patch('fleetmap.ladder.time.monotonic', return_value=160):
            self.assertEqual(self.rung(), {'rung': 'asked', 'ahead': 0, 'pr': None})

    def test_no_default_branch_is_asked(self):
        self.responses['symbolic-ref']['code'] = 1
        self.responses['rev-parse']['code'] = 1
        self.save()
        self.assertEqual(self.rung(), {'rung': 'asked', 'ahead': 0, 'pr': None})

    def test_never_prompted_requires_no_timestamp_and_no_purpose(self):
        for node, expected in (({}, True), ({'you_at': None, 'purpose': None}, True),
                               ({'you_at': 0, 'purpose': None}, False),
                               ({'you_at': None, 'purpose': ''}, True),
                               ({'you_at': None, 'purpose': 'Older human prompt'}, False),
                               ({'you_at': 10, 'purpose': 'Fix it'}, False)):
            with self.subTest(node=node):
                self.assertEqual(never_prompted(node), expected)


if __name__ == '__main__':
    unittest.main()

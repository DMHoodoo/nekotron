from __future__ import annotations

"""Exercise fleet signals through snapshot records and fake probe executables."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.projection import Projection
from fleetmap.signals import MemoryProbe, StaleChecker, decision_strip, is_stalled, running_workers


class FleetSignals(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fleetmap-signals-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.worktree = self.base / 'work tree'
        self.worktree.mkdir()
        self.log = self.base / 'calls.jsonl'
        self.config = self.base / 'responses.json'
        self.old = 'a' * 40
        self.new = 'b' * 40
        self.vm_stat = ('Mach Virtual Memory Statistics: (page size of 16384 bytes)\n'
                        'Pages free: 262144.\nPages active: 524288.\n'
                        'Pages inactive: 131072.\nPages speculative: 65536.\n')
        self.responses = {
            'gh': {'stdout': json.dumps({'headRefOid': self.new})},
            'git ls-remote': {'stdout': self.new + '\trefs/heads/feature\n'},
            'git log': {'stdout': self.new + '\n'},
            'vm_stat': {'stdout': self.vm_stat},
            'sysctl hw.memsize': {'stdout': 'hw.memsize: 17179869184\n'},
            'sysctl vm.swapusage': {'stdout': 'vm.swapusage: total = 4096.00M  used = 1536.00M  free = 2560.00M (encrypted)\n'},
            'ssh': {'code': 1},
        }
        self.save()
        self.git = self.tool('git')
        self.gh = self.tool('gh')
        self.ssh = self.tool('ssh')
        self.tool('vm_stat')
        self.tool('sysctl')
        env = patch.dict(os.environ, {'PATH': str(self.base) + os.pathsep + os.environ['PATH']})
        env.start()
        self.addCleanup(env.stop)
        self.p = Projection(
            schemaVersion=2, run='run-one', title='One', updatedAt='',
            runPlan={'path': 'plan.md', 'commit': '123', 'worktree': str(self.worktree)},
            pr={'repo': 'org/repo', 'number': 42}, acceptance={'state': 'pending'},
            chiefTerminal='chief', now='', statusCard={}, decisions=[], gates=[],
            mergeGate={}, proofs=[], slices=[], packages=[], path='', mtime=0)
        self.row = {'id': 'design', 'verdict': 'pass', 'headSha': self.old}
        self.checker = StaleChecker(gh=self.gh, git=self.git, ttl=0)
        self.probe = MemoryProbe(ssh=self.ssh, ttl=0)

    def save(self):
        self.config.write_text(json.dumps(self.responses))

    def tool(self, name):
        path = self.base / name
        path.write_text(
            '#!' + sys.executable + '\n'
            'from __future__ import annotations\n'
            'import json, os, subprocess, sys, time\n'
            f'with open({str(self.log)!r}, "a") as log:\n'
            f'    log.write(json.dumps([{name!r}, os.getcwd(), sys.argv[1:]]) + "\\n")\n'
            f'with open({str(self.config)!r}) as source:\n'
            '    responses = json.load(source)\n'
            f'name = {name!r}\n'
            'key = name + " " + sys.argv[1] if name in ("git", "sysctl") else name\n'
            'response = responses.get(key, {"code": 99})\n'
            'time.sleep(response.get("sleep", 0))\n'
            'if response.get("execute"):\n'
            '    sys.exit(subprocess.run(["/bin/sh", "-c", sys.argv[-1]], timeout=5).returncode)\n'
            'sys.stdout.write(response.get("stdout", ""))\n'
            'sys.exit(response.get("code", 0))\n')
        path.chmod(0o755)
        return str(path)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_strip_orders_class_b_by_apply_at_first(self):
        self.p.decisions = [
            {'id': 'd', 'class': 'D', 'text': 'Approve'},
            {'id': 'late', 'class': 'B', 'text': 'Default', 'applyAt': '2026-10-19T13:00:00Z'},
            {'id': 'c', 'class': 'C', 'text': 'Choose', 'packet': 'packet.md'},
            {'id': 'undated', 'class': 'B', 'text': 'No deadline'},
        ]
        other = replace(self.p, run='run-two', title='Two', decisions=[
            {'id': 'early', 'class': 'B', 'text': 'First', 'applyAt': '2026-10-19T14:00:00+02:00'}])
        original = json.dumps(self.p.decisions)
        strip = decision_strip([self.p, other])
        self.assertEqual([item['id'] for item in strip], ['early', 'late', 'undated', 'c', 'd'])
        self.assertEqual(strip[0], {'run': 'run-two', 'title': 'Two', 'id': 'early', 'class': 'B',
                                   'text': 'First', 'packet': None, 'applyAt': '2026-10-19T14:00:00+02:00'})
        self.assertEqual(json.dumps(self.p.decisions), original)
        self.assertEqual(decision_strip([]), [])

    def test_stale_when_pr_head_moved_and_commits_unknown(self):
        self.responses['git log'] = {'code': 128}
        self.save()
        self.assertEqual(self.checker.check(self.p, self.row), {'moved': True, 'commits': None})
        self.assertEqual(self.calls()[0][2], ['pr', 'view', '42', '--repo', 'org/repo', '--json', 'headRefOid'])
        self.assertEqual(self.checker.check(self.p, self.row, branch='feature'),
                         {'moved': True, 'commits': None})
        self.assertIn(['git', str(self.worktree), ['ls-remote', 'origin', 'feature']], self.calls())
        self.assertTrue(all(call[1] == str(self.worktree) for call in self.calls()))
        self.assertFalse(any('fetch' in call[2] for call in self.calls()))

    def test_stale_with_local_commits(self):
        self.responses['git log']['stdout'] = self.new + '\n' + 'c' * 40 + '\n'
        self.save()
        self.assertEqual(self.checker.check(self.p, self.row),
                         {'moved': True, 'commits': [self.new, 'c' * 40]})
        self.assertIn(self.old + '..' + self.new, self.calls()[1][2])

    def test_slice_head_ignores_same_named_tag_and_unrelated_refs(self):
        self.responses['git ls-remote']['stdout'] = (
            self.new + '\trefs/tags/feature\n' + self.old + '\trefs/heads/feature\n')
        self.save()
        self.assertEqual(self.checker.check(self.p, self.row, branch='feature'),
                         {'moved': False, 'commits': []})

    def test_missing_executables_do_not_raise(self):
        missing = str(self.base / 'missing')
        self.assertIsNone(StaleChecker(gh=missing).check(self.p, self.row))
        self.assertIsNone(StaleChecker(git=missing).check(self.p, self.row, branch='feature'))
        self.assertEqual(MemoryProbe(ssh=missing).probe('remote', 'host'),
                         {'free_pct': None, 'swap_gb': None})

    def test_not_stale_when_head_unchanged(self):
        self.responses['gh']['stdout'] = json.dumps({'headRefOid': self.old})
        self.save()
        self.assertEqual(self.checker.check(self.p, row=self.row), {'moved': False, 'commits': []})
        self.assertEqual(len(self.calls()), 1)

    def test_not_stale_without_head_sha(self):
        self.row.pop('headSha')
        self.assertIsNone(self.checker.check(self.p, self.row))
        self.assertEqual(self.calls(), [])

    def test_no_check_for_unpassed_gate_missing_worktree_or_missing_target(self):
        for verdict in ('pending', 'revise'):
            self.assertIsNone(self.checker.check(self.p, dict(self.row, verdict=verdict)))
        self.p.pr['number'] = None
        self.assertIsNone(self.checker.check(self.p, self.row))
        self.p.runPlan['worktree'] = str(self.base / 'missing')
        self.assertIsNone(self.checker.check(self.p, self.row, branch='feature'))
        self.assertEqual(self.calls(), [])

    def test_failed_or_malformed_head_has_no_flag(self):
        for response in ({'code': 1}, {'stdout': 'invalid'}, {'stdout': '{}'},
                         {'stdout': '{"headRefOid": null}'}):
            self.responses['gh'] = response
            self.save()
            self.assertIsNone(self.checker.check(self.p, self.row))
        self.responses['git ls-remote']['stdout'] = ''
        self.save()
        self.assertIsNone(self.checker.check(self.p, self.row, branch='feature'))

    def test_stale_cache_expires_and_keys_include_head_and_target(self):
        checker = StaleChecker(gh=self.gh, git=self.git)
        with patch('fleetmap.signals.time.monotonic', return_value=100):
            self.assertTrue(checker.check(self.p, self.row)['moved'])
        self.responses['gh']['stdout'] = json.dumps({'headRefOid': self.old})
        self.save()
        with patch('fleetmap.signals.time.monotonic', return_value=159):
            self.assertTrue(checker.check(self.p, self.row)['moved'])
            self.assertEqual(len(self.calls()), 2)
            self.assertFalse(checker.check(self.p, dict(self.row, headSha=self.old[:8]))['moved'])
            self.assertTrue(checker.check(self.p, self.row, branch='feature')['moved'])
        with patch('fleetmap.signals.time.monotonic', return_value=160):
            self.assertFalse(checker.check(self.p, self.row)['moved'])

    def test_stall_when_activity_stamp_is_old_enough(self):
        node = {'state': 'working', 'activity_changed_at': 100}
        self.assertTrue(is_stalled(node, None, 700))
        self.assertFalse(is_stalled(node, None, 700, window=601))

    def test_no_stall_when_activity_stamp_is_recent(self):
        # The collector advances the stamp when an offset advances, even when
        # the assistant timestamp stays old and the next poll is unchanged.
        node = {'kind': 'claude', 'state': 'working', 'it_at': 100, 'offset': 20,
                'activity_changed_at': 650}
        self.assertFalse(is_stalled(node, dict(node), 700))

    def test_no_stall_without_activity_stamp(self):
        node = {'kind': 'claude', 'state': 'working', 'it_at': 100}
        self.assertFalse(is_stalled(node, dict(node), 700))
        node['activity_changed_at'] = None
        self.assertFalse(is_stalled(node, dict(node), 700))

    def test_no_stall_unless_working(self):
        for state in ('idle', 'attention', 'done'):
            with self.subTest(state=state):
                node = {'state': state, 'activity_changed_at': 100}
                self.assertFalse(is_stalled(node, None, 700))

    def test_memory_probe_parses_vm_stat_and_swapusage(self):
        self.assertEqual(self.probe.probe('local', None), {'free_pct': 43.75, 'swap_gb': 1.5})
        self.assertEqual([call[2] for call in self.calls()], [[], ['hw.memsize'], ['vm.swapusage']])

    def test_memory_counts_inactive_and_speculative_pages_when_free_is_zero(self):
        self.responses['vm_stat']['stdout'] = (
            'Mach Virtual Memory Statistics: (page size of 16384 bytes)\n'
            'Pages free: 0.\nPages inactive: 262144.\nPages speculative: 262144.\n')
        self.save()
        self.assertEqual(self.probe.probe('local', None),
                         {'free_pct': 50.0, 'swap_gb': 1.5})

    def test_memory_supports_intel_pages_and_swap_units(self):
        self.responses['vm_stat']['stdout'] = self.vm_stat.replace('16384', '4096')
        for unit, value in (('G', '1.5'), ('M', '1536'), ('K', '1572864'), ('B', '1610612736')):
            self.responses['sysctl vm.swapusage']['stdout'] = 'used = ' + value + unit
            self.save()
            self.assertEqual(self.probe.probe('local', None), {'free_pct': 10.9375, 'swap_gb': 1.5})

    def test_remote_probe_failure_returns_blanks(self):
        self.assertEqual(self.probe.probe('laptop2', 'worker@host'), {'free_pct': None, 'swap_gb': None})
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls()[0][2][:5], ['-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=3', 'worker@host'])

    def test_remote_probe_uses_one_ssh_with_three_output_lines(self):
        self.responses['ssh'] = {'stdout': self.vm_stat.replace('\n', ' ') + '\n17179869184\nused = 1536.00M\n'}
        self.save()
        self.assertEqual(self.probe.probe('laptop2', 'worker@host'), {'free_pct': 43.75, 'swap_gb': 1.5})
        self.assertEqual(len(self.calls()), 1)
        command = self.calls()[0][2][-1]
        for part in ('vm_stat', 'sysctl hw.memsize', 'sysctl vm.swapusage'):
            self.assertIn(part, command)

    def test_remote_shell_command_produces_parseable_probe_values(self):
        self.responses['ssh'] = {'execute': True}
        self.save()
        self.assertEqual(self.probe.probe('laptop2', 'worker@host'),
                         {'free_pct': 43.75, 'swap_gb': 1.5})
        self.assertEqual([call[0] for call in self.calls()],
                         ['ssh', 'vm_stat', 'sysctl', 'sysctl'])

    def test_incomplete_remote_response_is_blank(self):
        self.responses['ssh'] = {'stdout': '17179869184\nused = 1536.00M\n'}
        self.save()
        self.assertEqual(self.probe.probe('laptop2', 'worker@host'),
                         {'free_pct': None, 'swap_gb': None})

    def test_remote_without_ssh_target_does_not_probe_local_machine(self):
        self.assertEqual(self.probe.probe('laptop2', None), {'free_pct': None, 'swap_gb': None})
        self.assertEqual(self.calls(), [])

    def test_memory_falls_back_to_proc_meminfo_without_vm_stat(self):
        meminfo = self.base / 'meminfo'
        meminfo.write_text('MemTotal: 16000000 kB\nMemFree: 1000000 kB\n'
                           'MemAvailable: 4000000 kB\nSwapTotal: 2097152 kB\n'
                           'SwapFree: 1048576 kB\n')
        probe = MemoryProbe(ttl=0, meminfo=str(meminfo))
        with patch.dict(os.environ, {'PATH': str(self.base / 'empty')}):
            self.assertEqual(probe.probe('local', None), {'free_pct': 25.0, 'swap_gb': 1.0})
        meminfo.write_text('MemTotal: 16000000 kB\n')
        with patch.dict(os.environ, {'PATH': str(self.base / 'empty')}):
            self.assertEqual(probe.probe('local', None), {'free_pct': None, 'swap_gb': None})

    def test_invalid_memory_is_blank(self):
        for command, output in (('vm_stat', ''), ('sysctl hw.memsize', '0'),
                                ('sysctl vm.swapusage', 'used = nonsense')):
            original = self.responses[command]
            self.responses[command] = {'stdout': output}
            self.save()
            self.assertEqual(self.probe.probe('local', None), {'free_pct': None, 'swap_gb': None})
            self.responses[command] = original

    def test_memory_cache_expires_and_does_not_cross_hosts_or_targets(self):
        probe = MemoryProbe(ssh=self.ssh)
        with patch('fleetmap.signals.time.monotonic', return_value=100):
            self.assertEqual(probe.probe('local', None)['free_pct'], 43.75)
        self.responses['vm_stat']['code'] = 1
        self.save()
        with patch('fleetmap.signals.time.monotonic', return_value=114):
            self.assertEqual(probe.probe('local', None)['free_pct'], 43.75)
            self.assertEqual(len(self.calls()), 3)
            self.assertIsNone(probe.probe('laptop2', 'host')['free_pct'])
            self.assertIsNone(probe.probe('laptop2', 'new-host')['free_pct'])
            self.assertEqual(len(self.calls()), 5)
        with patch('fleetmap.signals.time.monotonic', return_value=115):
            self.assertIsNone(probe.probe('local', None)['free_pct'])

    def test_every_probe_command_times_out_after_five_seconds(self):
        cases = ('gh', 'git ls-remote', 'git log', 'ssh', 'vm_stat', 'sysctl hw.memsize', 'sysctl vm.swapusage')
        for command in cases:
            with self.subTest(command=command):
                self.responses[command]['sleep'] = 10
                self.save()
                start = time.monotonic()
                if command.startswith('git') or command == 'gh':
                    branch = 'feature' if command == 'git ls-remote' else None
                    result = self.checker.check(self.p, self.row, branch=branch)
                    self.assertEqual(result, {'moved': True, 'commits': None} if command == 'git log' else None)
                else:
                    result = self.probe.probe('remote', 'host') if command == 'ssh' else self.probe.probe('local', None)
                    self.assertEqual(result, {'free_pct': None, 'swap_gb': None})
                self.assertLess(time.monotonic() - start, 8)
                self.responses[command].pop('sleep')

    def test_running_workers_ignore_worker_host_field(self):
        workers = {'local': [
            {'dispatchId': 'a', 'agentTerminalHandle': 'remote', 'host': 'local', 'workerState': 'running'},
            {'dispatchId': 'b', 'agentTerminalHandle': 'local', 'host': 'laptop2', 'workerState': 'waiting'},
            {'dispatchId': 'c', 'agentTerminalHandle': 'missing', 'workerState': 'running'},
        ], 'laptop2': []}
        terminals = {'local': [{'handle': 'local'}], 'laptop2': [{'handle': 'remote'}], 'empty': []}
        self.assertEqual(running_workers(workers, terminals), {'local': 1, 'laptop2': 1, 'empty': 0})

    def test_running_workers_exclude_settled_and_count_each_dispatch_once(self):
        workers = [{'dispatchId': str(i), 'agentTerminalHandle': 'term', 'workerState': state}
                   for i, state in enumerate(('settled', 'released', 'abandoned', 'running', 'waiting'))]
        self.assertEqual(running_workers({'local': workers, 'remote': workers}, {'remote': [{'handle': 'term'}]}),
                         {'local': 0, 'remote': 2})


if __name__ == '__main__':
    unittest.main()

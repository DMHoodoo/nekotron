from __future__ import annotations

"""Local registry discovery without real ps calls or transcript parsing."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.registry import list_local_sessions, run_ps, run_args, transcript_path


class LocalRegistry(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fleetmap-registry-')
        self.addCleanup(tmp.cleanup)
        self.sess, self.proj, self.state = [Path(tmp.name) / name
                                           for name in ('sessions', 'projects', 'state')]
        for directory in (self.sess, self.proj, self.state):
            directory.mkdir()
        alive = patch('os.kill', return_value=None)
        self.kill = alive.start()
        self.addCleanup(alive.stop)

    def write_registry(self, pid=55409, sid='s1', name='Handoff Project',
                       cwd='/w/lookdown', **extra):
        data = dict(pid=pid, sessionId=sid, name=name, cwd=cwd, status='busy',
                    startedAt=1792176064674, statusUpdatedAt=1792439115658,
                    kind='interactive')
        data.update(extra)
        (self.sess / f'{pid}.json').write_text(json.dumps(data))

    def sessions(self, ps=lambda pid: 'claude', identity=None):
        return list_local_sessions(sessions_dir=self.sess, projects_dir=self.proj,
                                   state_dir=self.state, ps=ps, identity=identity or ps)

    def test_lists_live_claude_session_with_pane_and_hook_state(self):
        self.write_registry(pid=os.getpid())
        (self.state / 'sid-s1').write_text('attention')
        [session] = self.sessions(lambda pid: 'claude ORCA_AGENT_PANE=tab1:leaf1 HOME=/x')
        self.assertEqual((session.session_id, session.orca_pane, session.hook_state),
                         ('s1', ('tab1', 'leaf1'), 'attention'))
        self.assertEqual((session.pid, session.name, session.cwd, session.status),
                         (os.getpid(), 'Handoff Project', '/w/lookdown', 'busy'))
        self.assertEqual(session.started_at, 1792176064.674)
        self.assertEqual(session.status_updated_at, 1792439115.658)
        self.assertIsNone(session.transcript)
        self.assertIsNone(session.kitty_key)
        self.assertIsNone(session.ctx_pct)
        self.assertIsNone(session.cost)
        self.assertEqual(session.subagents, [])
        self.kill.assert_called_once_with(os.getpid(), 0)

    def test_dead_pid_is_skipped(self):
        self.write_registry(pid=2**22 - 1, sid='s2', name='gone', cwd='/w')
        self.kill.side_effect = ProcessLookupError
        self.assertEqual(self.sessions(lambda pid: 'claude'), [])

    def test_reused_pid_without_claude_command_is_skipped(self):
        self.write_registry(pid=os.getpid(), sid='s3', name='x', cwd='/w')
        self.assertEqual(self.sessions(lambda pid: '/usr/bin/python3 something.py'), [])

    def test_environment_and_unrelated_arguments_do_not_identify_claude(self):
        self.write_registry()
        for command in ('/usr/bin/python3 worker.py PATH=/Users/hok/.claude/local:/usr/bin',
                        '/usr/bin/python3 worker.py CLAUDE_SESSION=active',
                        '/bin/echo claude', '/usr/bin/python3 worker.py --label=claude'):
            with self.subTest(command=command):
                self.assertEqual(self.sessions(lambda pid: command), [])
        self.assertEqual(self.sessions(lambda pid: 'claude KITTY_PID=1',
                                       identity=lambda pid: '/bin/python worker.py'), [])

    def test_claude_executable_launch_forms(self):
        self.write_registry()
        for command in ('claude --resume session', '/Users/hok/.local/bin/claude --model opus'):
            with self.subTest(command=command):
                self.assertEqual(len(self.sessions(identity=lambda pid: command)), 1)

    def test_identity_query_excludes_environment(self):
        with patch('subprocess.run', return_value=Mock(stdout='/bin/claude --resume s')) as run:
            self.assertEqual(run_args(123), '/bin/claude --resume s')
        self.assertEqual(run.call_args.args[0], ['ps', '-p', '123', '-o', 'args='])

    def test_permission_error_is_skipped_even_with_claude_command(self):
        self.write_registry()
        self.kill.side_effect = PermissionError
        self.assertEqual(self.sessions(lambda pid: 'claude'), [])

    def test_subagents_are_listed_from_project_dir(self):
        self.write_registry(sid='s4')
        directory = self.proj / '-w-lookdown' / 's4' / 'subagents'
        directory.mkdir(parents=True)
        transcript = directory / 'agent-abc.jsonl'
        transcript.write_text('not parsed as JSON\n')
        (directory / 'agent-abc.meta.json').write_text('{}')
        (directory / 'unrelated.jsonl').write_text('{}')
        os.utime(transcript, (1700000000, 1700000000))
        [session] = self.sessions()
        self.assertEqual([(a.agent_id, a.transcript, a.mtime) for a in session.subagents],
                         [('abc', str(transcript), 1700000000.0)])

    def test_transcript_slug_and_missing_file(self):
        cwd = '/Users/a.b/my_project'
        self.assertIsNone(transcript_path(cwd, 's1', self.proj))
        transcript = self.proj / '-Users-a-b-my-project' / 's1.jsonl'
        transcript.parent.mkdir()
        transcript.write_text('not parsed as JSON\n')
        self.assertEqual(transcript_path(cwd, 's1', str(self.proj)), str(transcript))
        self.write_registry(cwd=cwd)
        self.assertEqual(self.sessions()[0].transcript, str(transcript))

    def test_kitty_hook_and_metrics_require_control_socket(self):
        self.write_registry()
        (self.state / '123-4').write_text('working\n')
        (self.state / 'ctx-123-4').write_text('42\n')
        (self.state / 'usage-123-4').write_text('1.25\n')
        ps = lambda pid: 'claude KITTY_PID=123 KITTY_WINDOW_ID=4'
        with patch('os.path.exists', return_value=True) as exists:
            [session] = self.sessions(ps)
        exists.assert_any_call('/tmp/kitty-ctl-123')
        self.assertEqual((session.kitty_key, session.hook_state, session.ctx_pct, session.cost),
                         ('123-4', 'working', 42, 1.25))
        with patch('os.path.exists', return_value=False):
            [session] = self.sessions(ps)
        self.assertEqual((session.kitty_key, session.hook_state, session.ctx_pct, session.cost),
                         ('123-4', None, None, None))

    def test_session_hook_takes_precedence_over_kitty_hook(self):
        self.write_registry()
        (self.state / 'sid-s1').write_text('done\n')
        (self.state / '123-4').write_text('working')
        (self.state / 'ctx-s1').write_text('99')
        (self.state / 'usage-s1').write_text('99')
        with patch('os.path.exists', return_value=True):
            [session] = self.sessions(lambda pid: 'claude KITTY_PID=123 KITTY_WINDOW_ID=4')
        self.assertEqual(session.hook_state, 'done')
        self.assertIsNone(session.ctx_pct)
        self.assertIsNone(session.cost)

    def test_partial_or_invalid_host_metadata_is_ignored(self):
        self.write_registry()
        for env in ('KITTY_PID=123', 'KITTY_WINDOW_ID=4',
                    'OTHER_KITTY_PID=123 KITTY_WINDOW_ID=4',
                    'ORCA_AGENT_PANE=tab', 'ORCA_AGENT_PANE=tab:',
                    'OTHER_ORCA_AGENT_PANE=tab:leaf'):
            with self.subTest(env=env), patch('os.path.exists', return_value=True):
                [session] = self.sessions(lambda pid: 'claude ' + env)
                self.assertIsNone(session.kitty_key)
                self.assertIsNone(session.orca_pane)

    def test_invalid_optional_state_does_not_hide_session(self):
        self.write_registry()
        (self.state / 'sid-s1').write_text('invalid')
        (self.state / '123-4').write_text('attention')
        (self.state / 'ctx-123-4').write_text('bad')
        (self.state / 'usage-123-4').write_text('bad')
        with patch('os.path.exists', return_value=True):
            [session] = self.sessions(lambda pid: 'claude KITTY_PID=123 KITTY_WINDOW_ID=4')
        self.assertEqual(session.hook_state, 'attention')
        self.assertIsNone(session.ctx_pct)
        self.assertIsNone(session.cost)

    def test_missing_directories_are_empty(self):
        self.sess.rmdir()
        self.proj.rmdir()
        self.state.rmdir()
        self.assertEqual(self.sessions(), [])

    def test_malformed_registry_files_do_not_hide_valid_session(self):
        self.write_registry()
        for i, value in enumerate(('not json', '[]', 'null', '{}',
                                   '{"pid": 0}', '{"pid": "bad"}')):
            (self.sess / f'bad-{i}.json').write_text(value)
        (self.sess / 'partial.json').write_bytes(b'\xff')
        self.assertEqual([s.session_id for s in self.sessions()], ['s1'])

    def test_ps_failure_does_not_hide_other_sessions(self):
        self.write_registry(pid=1, sid='gone')
        self.write_registry(pid=2, sid='live')
        def ps(pid):
            if pid == 1:
                raise ProcessLookupError
            return 'claude'
        self.assertEqual([s.session_id for s in self.sessions(ps)], ['live'])

    def test_run_ps_uses_environment_and_full_command_output(self):
        with patch('subprocess.run', return_value=Mock(stdout='claude HOME=/x\n')) as run:
            self.assertEqual(run_ps(55409), 'claude HOME=/x\n')
        self.assertEqual(run.call_args.args[0], ['ps', 'eww', '-p', '55409', '-o', 'command='])
        self.assertTrue(run.call_args.kwargs['text'])
        self.assertTrue(run.call_args.kwargs['capture_output'])

    def test_run_ps_failure_returns_empty_output(self):
        for error in (OSError('unavailable'), subprocess.TimeoutExpired('ps', 5)):
            with self.subTest(error=error), patch('subprocess.run', side_effect=error):
                self.assertEqual(run_ps(55409), '')


if __name__ == '__main__':
    unittest.main()

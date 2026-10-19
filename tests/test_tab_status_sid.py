"""Session state published by the hook without a kitty window."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
STATE = Path('/tmp/claude-kitty-status')


class SidStateFile(unittest.TestCase):
    def setUp(self):
        self.sid_file = STATE / 'sid-abc-123'
        self.sid_file.unlink(missing_ok=True)
        self.addCleanup(self.sid_file.unlink, missing_ok=True)

    def run_hook(self, state, session_id='abc-123', env_extra=None):
        env = dict(os.environ, KITTY_PID='', KITTY_WINDOW_ID='', TMUX='',
                   NEKOTRON_TMUX_SESSION='')
        env.update(env_extra or {})
        subprocess.run([str(ROOT / 'hooks/kitty-tab-status.sh'), state],
                       env=env, check=True, input=json.dumps({'session_id': session_id}),
                       text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5)

    def test_writes_sid_file_without_kitty(self):
        self.run_hook('working')
        self.assertEqual(self.sid_file.read_text(), 'working')

    def test_attention_never_downgrades_done(self):
        self.run_hook('done')
        self.run_hook('attention')
        self.assertEqual(self.sid_file.read_text(), 'done')

    def test_reset_removes_sid_file(self):
        self.run_hook('working')
        self.run_hook('reset')
        self.assertFalse(self.sid_file.exists())

    def test_no_stdin_json_is_harmless(self):
        subprocess.run([str(ROOT / 'hooks/kitty-tab-status.sh'), 'working'],
                       input='', text=True, check=True, timeout=5,
                       env=dict(os.environ, KITTY_PID='', KITTY_WINDOW_ID='',
                                TMUX='', NEKOTRON_TMUX_SESSION=''))

    def test_open_stdin_pipe_exits_without_session_state(self):
        self.check_open_pipe(b'')

    def test_unclosed_payload_is_discarded_and_other_state_is_published(self):
        for payload in (b'{"session_id":"abc-123"}', b'{"session_id":'):
            with self.subTest(payload=payload):
                self.check_open_pipe(payload)

    def check_open_pipe(self, payload):
        key = f'test-sid-pipe-{os.getpid()}'
        kitty_file = STATE / f'{key}-1'
        tmux_file = STATE / f'tmux-neko-{key}'
        for path in (kitty_file, tmux_file, STATE / f'provider-{key}-1'):
            path.unlink(missing_ok=True)
            self.addCleanup(path.unlink, missing_ok=True)
        process = subprocess.Popen(
            [str(ROOT / 'hooks/kitty-tab-status.sh'), 'working'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, KITTY_PID=key, KITTY_WINDOW_ID='1',
                     TMUX='', NEKOTRON_TMUX_SESSION=f'neko-{key}'))
        try:
            if payload:
                process.stdin.write(payload)
                process.stdin.flush()
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertFalse(self.sid_file.exists())
            self.assertEqual(kitty_file.read_text(), 'working')
            self.assertEqual(tmux_file.read_text(), 'working')
        finally:
            process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait()


if __name__ == '__main__':
    unittest.main()

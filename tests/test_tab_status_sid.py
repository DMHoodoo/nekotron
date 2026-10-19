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


if __name__ == '__main__':
    unittest.main()

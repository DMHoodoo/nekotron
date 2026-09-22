"""Run with python3 -m unittest discover -s tests -v (no model calls)."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CodexOneShot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.log = self.home / "states"
        self.env = dict(os.environ, HOME=str(self.home), PATH="/usr/bin:/bin", STATE_LOG=str(self.log))
        hook = self.home / ".claude/hooks/kitty-tab-status.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text('#!/bin/bash\nprintf "%s\\n" "$1" >> "$STATE_LOG"\n')
        hook.chmod(0o755)

    def states(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def fake_codex(self, rc=0):
        p = self.home / '.local/bin/codex'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('#!/bin/bash\n[ "$1" = exec ] && [ "$2" = - ] || exit 99\ncat > "$HOME/prompt"\nprintf "answer\\n"\nexit '+str(rc)+'\n')
        p.chmod(0o755)

    def test_qo_pipe_and_exit_status(self):
        for rc, end in [(0, 'done'), (7, 'attention')]:
            with self.subTest(rc=rc):
                self.fake_codex(rc)
                result = subprocess.run([str(ROOT/'bin/qo'), 'explain', 'this'], input='context\n', env=self.env, text=True, capture_output=True)
                self.assertEqual(result.returncode, rc)
                self.assertEqual(result.stdout, 'answer\n')
                self.assertEqual((self.home/'prompt').read_text(), 'context\n\nexplain this\n')
                self.assertEqual(self.states()[-2:], ['working', end])

    def test_qo_usage_and_missing_binary(self):
        for args, rc in [([], 1), (['hello'], 127)]:
            result = subprocess.run([str(ROOT/'bin/qo'), *args], input='', env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, rc)
            self.assertTrue(result.stderr)
        self.assertEqual(self.states(), [])

if __name__ == '__main__':
    unittest.main()

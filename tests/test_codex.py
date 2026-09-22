"""Run with python3 -m unittest discover -s tests -v (no model calls)."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CodexLane(unittest.TestCase):
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

    def notify(self, payload, stdin=False):
        raw = json.dumps(payload)
        args = [str(ROOT / "hooks/codex-notify.sh")]
        if not stdin:
            args.append(raw)
        result = subprocess.run(args, input=raw if stdin else '', env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')  # Never accidentally approve or steer a tool.

    def test_real_lifecycle_sequence(self):
        for event in ['UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'PostToolUse', 'Stop']:
            self.notify({'hook_event_name': event, 'tool_name': 'Bash'}, stdin=True)
        self.assertEqual(self.states(), ['working', 'working', 'attention', 'working', 'done'])

    def test_notify_completion_and_forward_events(self):
        for event in ['agent-turn-started', 'approval-requested', 'input-requested', 'agent-turn-complete']:
            self.notify({'type': event})
        self.assertEqual(self.states(), ['working', 'attention', 'attention', 'done'])

    def test_background_title_does_not_clear_attention(self):
        self.notify({'hook_event_name': 'PermissionRequest'}, stdin=True)
        self.notify({'type': 'agent-turn-complete', 'input-messages': [
            'Generate a concise, single-line task title of at most 36 characters and under five words where possible.'],
            'last-assistant-message': '{"title":"Test hooks"}'})
        self.assertEqual(self.states(), ['attention'])

    def test_input_question_and_interrupt(self):
        self.notify({'hook_event_name': 'PreToolUse', 'tool_name': 'request_user_input'}, stdin=True)
        self.notify({'hook_event_name': 'PostToolUse', 'tool_name': 'request_user_input'}, stdin=True)
        self.notify({'hook_event_name': 'Interrupt'}, stdin=True)
        self.assertEqual(self.states(), ['attention', 'working', 'done'])

    def test_malformed_and_missing_writer_are_noops(self):
        for raw in ['not json', '{}', '[]', 'null', '{"type": []}']:
            result = subprocess.run([str(ROOT/'hooks/codex-notify.sh'), raw], env=self.env, capture_output=True)
            self.assertEqual(result.returncode, 0)
        self.assertEqual(self.states(), [])
        (self.home/'.claude/hooks/kitty-tab-status.sh').unlink()
        self.notify({'type': 'agent-turn-complete'})

if __name__ == '__main__':
    unittest.main()

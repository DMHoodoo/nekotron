# Codex event probe

Observed on macOS with Codex CLI 0.155.1, 2026-09-22. Session identifiers and
home paths below are redacted. The logger was configured before implementing
the adapter, and the interactive probe included a real approval prompt.

```sh
#!/bin/bash
printf '%s\n' "$1" | jq . >> /tmp/codex-events
```

Point `notify` at an executable containing the above (a per-run
`-c 'notify=["/ABS/PATH/logger.sh"]'` override avoids altering existing config).
Run `codex --no-alt-screen -a on-request -s read-only` and ask it to request
`require_escalated` approval for `/usr/bin/true`, then reply with a fixed marker.
Inspect the log while the prompt is visible, approve once, and inspect again.

There was **no approval or start notify event**. A background title-generation
turn emitted its own completion while the real approval was pending. The actual
completion arrived after approval. Filter the observed title prompt prefix;
notify alone cannot provide a working/attention lifecycle. This filter depends
on Codex's internal title prompt and should be rechecked after CLI upgrades.

```json
[
  {
    "type": "agent-turn-complete",
    "thread-id": "example-thread-id",
    "turn-id": "example-turn-id",
    "cwd": "/tmp/nekotron-codex-probe",
    "client": "codex-tui",
    "input-messages": [
      "Generate a concise, single-line task title of at most 36 characters and under five words where possible. Start with an imperative verb. Capitalize only the first word unless the user's language, proper nouns, acronyms, or code terms require otherwise. Preserve ticket references exactly. Write in the user's language. Do not use quotes, markdown, or trailing punctuation. Do not answer the request.\n\nUser prompt:\nThis is a notification integration test. Request approval for the harmless command /usr/bin/true using require_escalated, with justification \"Nekotron approval notification test\". Do not change files. After it is approved, reply exactly NEKOTRON_PROBE_DONE."
    ],
    "last-assistant-message": "{\"title\":\"Request harmless command approval\"}"
  },
  {
    "type": "agent-turn-complete",
    "thread-id": "example-thread-id",
    "turn-id": "example-turn-id",
    "cwd": "/tmp/nekotron-codex-probe",
    "client": "codex-tui",
    "input-messages": [
      "This is a notification integration test. Request approval for the harmless command /usr/bin/true using require_escalated, with justification \"Nekotron approval notification test\". Do not change files. After it is approved, reply exactly NEKOTRON_PROBE_DONE."
    ],
    "last-assistant-message": "NEKOTRON_PROBE_DONE"
  },
  {
    "type": "agent-turn-complete",
    "thread-id": "example-thread-id",
    "turn-id": "example-turn-id",
    "cwd": "/tmp/nekotron-codex-probe",
    "client": "codex-tui",
    "input-messages": [
      "Generate a concise, single-line task title of at most 36 characters and under five words where possible. Start with an imperative verb. Capitalize only the first word unless the user's language, proper nouns, acronyms, or code terms require otherwise. Preserve ticket references exactly. Write in the user's language. Do not use quotes, markdown, or trailing punctuation. Do not answer the request.\n\nUser prompt:\nTest lifecycle events. First run /bin/sleep 8 normally. Then request require_escalated approval for /usr/bin/true with justification Nekotron-test. After approval run /bin/sleep 8 normally then reply NEKOTRON_LIFECYCLE_DONE. Do not edit files."
    ],
    "last-assistant-message": "{\"title\":\"Test lifecycle events\"}"
  },
  {
    "type": "agent-turn-complete",
    "thread-id": "example-thread-id",
    "turn-id": "example-turn-id",
    "cwd": "/tmp/nekotron-codex-probe",
    "client": "codex-tui",
    "input-messages": [
      "Test lifecycle events. First run /bin/sleep 8 normally. Then request require_escalated approval for /usr/bin/true with justification Nekotron-test. After approval run /bin/sleep 8 normally then reply NEKOTRON_LIFECYCLE_DONE. Do not edit files."
    ],
    "last-assistant-message": "NEKOTRON_LIFECYCLE_DONE"
  }
]
```

A second probe in a kitty tab logged lifecycle JSON from stdin using
`jq -c . >> /tmp/codex-lifecycle-events`. It slept, requested approval for
`/usr/bin/true`, slept again, and completed. Hooks were synchronous, without
any output or approval decision. Only the main task emitted these hooks:

```json
[
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "UserPromptSubmit",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "prompt": "Test lifecycle events. First run /bin/sleep 8 normally. Then request require_escalated approval for /usr/bin/true with justification Nekotron-test. After approval run /bin/sleep 8 normally then reply NEKOTRON_LIFECYCLE_DONE. Do not edit files."
  },
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "PreToolUse",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "tool_name": "Bash",
    "tool_input": {
      "command": "/bin/sleep 8"
    },
    "tool_use_id": "example-tool-call"
  },
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "PostToolUse",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "tool_name": "Bash",
    "tool_input": {
      "command": "/bin/sleep 8"
    },
    "tool_response": "",
    "tool_use_id": "example-tool-call"
  },
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "PreToolUse",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "tool_name": "Bash",
    "tool_input": {
      "command": "/usr/bin/true"
    },
    "tool_use_id": "example-tool-call"
  },
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "PermissionRequest",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "tool_name": "Bash",
    "tool_input": {
      "command": "/usr/bin/true",
      "description": "Nekotron-test"
    }
  },
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "PostToolUse",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "tool_name": "Bash",
    "tool_input": {
      "command": "/usr/bin/true"
    },
    "tool_response": "",
    "tool_use_id": "example-tool-call"
  },
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "PreToolUse",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "tool_name": "Bash",
    "tool_input": {
      "command": "/bin/sleep 8"
    },
    "tool_use_id": "example-tool-call"
  },
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "PostToolUse",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "tool_name": "Bash",
    "tool_input": {
      "command": "/bin/sleep 8"
    },
    "tool_response": "",
    "tool_use_id": "example-tool-call"
  },
  {
    "session_id": "example-session",
    "turn_id": "example-turn",
    "transcript_path": "/Users/YOU/.codex/sessions/example.jsonl",
    "cwd": "/tmp/nekotron-codex-probe",
    "hook_event_name": "Stop",
    "model": "gpt-6-astra",
    "permission_mode": "default",
    "stop_hook_active": false,
    "last_assistant_message": "NEKOTRON_LIFECYCLE_DONE"
  }
]
```

`codex/hooks.json` supplies these lifecycle events. Review/trust it via `/hooks`.
No hook grants permission or changes the approval policy. The reference writer
handles tmux resolution, state deduplication, notifications, and sound unchanged.

Regression checks: `python3 -m unittest discover -s tests -v`.

## Live integration verification

With installed hooks trusted through `/hooks`, a Codex kitty tab produced
`working → attention → working → done` around a real `/usr/bin/true` approval.
The fleet board's `gather()` matched each state, and its overlay rendered
`NEEDS YOU` while approval was pending. A second Plan-mode turn used an actual
`request_user_input` question: attention appeared and the reference hook spawned
`afplay ~/.claude/sounds/meow.wav`. The attention-jump action selected this tab.
The tab-bar reader saw the same attention file; its spinner/pulse/green color
functions passed checks in kitty's own Python runtime. macOS window capture was
unavailable, so no screenshot-based assertion is made.

A real `printf 'The marker is NEKOTRON_QO_OK.\n' | qo 'Reply only with the marker
from stdin. Do not use tools.'` returned the marker, exit 0, and a done fleet card.
All repository Bash scripts passed `bash -n`, zsh setup passed `zsh -n`, all
Python sources passed `py_compile`, and board `--print` / `--frames 3` ran cleanly.

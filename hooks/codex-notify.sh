#!/bin/bash
# Codex notify: one JSON argument. Lifecycle hooks: one JSON object on stdin.
# Keep all kitty/tmux resolution, deduplication and sounds in the reference writer.
# Observed payloads and limitations: docs/codex-events.md.
JQ="$(command -v jq || echo /opt/homebrew/bin/jq)"
[ -x "$JQ" ] || exit 0
if [ $# -gt 0 ]; then payload="$1"; else payload="$(cat)"; fi
state=$(printf '%s' "$payload" | "$JQ" -er '
    select(type == "object") |
    # Codex 0.155.1 also notifies for its background title-generation turn.
    # That completion must not clear a real turn waiting for approval.
    select(((."input-messages" // [])[0] // .prompt // "" |
        startswith("Generate a concise, single-line task title of at most 36 characters")) | not) |
    (.type // .hook_event_name // "") as $event |
    select($event | type == "string") |
    if ($event == "agent-turn-complete" or $event == "task-complete" or
        $event == "turn-complete" or $event == "Stop" or $event == "Interrupt") then "done"
    elif ($event == "approval-requested" or $event == "input-requested" or
          $event == "PermissionRequest") then "attention"
    elif ($event == "PreToolUse" and
          ((.tool_name // "") | test("(^|[._])request_user_input(_async)?$"))) then "attention"
    elif $event != "" then "working"
    else empty end
' 2>/dev/null) || exit 0
HOOK="$HOME/.claude/hooks/kitty-tab-status.sh"
[ -x "$HOOK" ] || exit 0
exec "$HOOK" "$state"

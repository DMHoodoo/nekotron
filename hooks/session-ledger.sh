#!/bin/bash
# Session black box: one TSV line per SessionStart, plus a debounced snapshot
# since the workspace layout just changed.
#   columns: datetime · session_id · cwd · kitty(pid-window) · source

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "?"' 2>/dev/null)
cwd=$(printf '%s' "$input" | jq -r '.cwd // "?"' 2>/dev/null)
src=$(printf '%s' "$input" | jq -r '.source // ""' 2>/dev/null)
printf '%s\t%s\t%s\t%s\t%s\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" "$sid" "$cwd" \
    "${KITTY_PID:-?}-${KITTY_WINDOW_ID:-?}" "$src" \
    >> "$HOME/.claude/session-ledger.tsv"

# layout changed: refresh the restore snapshot (max once per minute)
f="$HOME/.config/kitty/claude-restore.session"
if [ -z "$(find "$f" -mtime -60s 2>/dev/null)" ]; then
    ( sleep 5; "$HOME/bin/kitty-claude-snapshot.sh" >/dev/null 2>&1 ) &
fi
exit 0

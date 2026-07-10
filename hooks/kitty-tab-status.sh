#!/bin/bash
# Publish this Claude Code session's state for the kitty tab bar (~/.config/kitty/tab_bar.py).
#   usage: kitty-tab-status.sh done|attention|working|reset
# Writes /tmp/claude-kitty-status/<kitty_pid>-<kitty_window_id>.
#
# Sessions running INSIDE tmux inherit stale KITTY_* env (from wherever the
# tmux session was first created — possibly a dead kitty instance), so for
# those we resolve the kitty window that is CURRENTLY displaying this tmux
# session, via tmux client pid -> kitten @ ls. Resolution is cached for 30s
# per claude process to keep per-tool-call events cheap.
#
# Must never block or fail Claude Code: always exits 0.

state="$1"
case "$state" in done|attention|working|reset) ;; *) exit 0 ;; esac

dir=/tmp/claude-kitty-status
mkdir -p "$dir" 2>/dev/null

KITTEN="$(command -v kitten || echo /Applications/kitty.app/Contents/MacOS/kitten)"

kpid="$KITTY_PID"
wid="$KITTY_WINDOW_ID"

if [ -n "$TMUX" ]; then
    key=""
    map="$dir/.map-${PPID}"    # PPID = the claude process that spawned this hook
    now=$(date +%s); mt=$(stat -f %m "$map" 2>/dev/null || echo 0)
    if [ $((now - mt)) -lt 300 ]; then
        key="$(cat "$map" 2>/dev/null)"
    else
        sess=$(tmux display-message -pt "$TMUX_PANE" '#{session_name}' 2>/dev/null)
        cpid=$(tmux list-clients -t "$sess" -F '#{client_pid}' 2>/dev/null | head -1)
        sock=$(ls -t /tmp/kitty-ctl-* 2>/dev/null | head -1)
        if [ -n "$cpid" ] && [ -n "$sock" ]; then
            rwid=$("$KITTEN" @ --to "unix:$sock" ls 2>/dev/null | jq -r --argjson p "$cpid" \
                'first(.[] | .tabs[] | .windows[] | select(.foreground_processes[]?.pid == $p) | .id) // empty')
            [ -n "$rwid" ] && key="${sock##*-}-$rwid" && printf '%s' "$key" > "$map"
        fi
    fi
    if [ -z "$key" ]; then
        # Detached tmux = agent teammates. Their env is inherited from the
        # session that spawned them — if that kitty instance is still alive,
        # map the agent's activity onto the spawning session's tab.
        if [ -n "$KITTY_PID" ] && [ -n "$KITTY_WINDOW_ID" ] && [ -S "/tmp/kitty-ctl-$KITTY_PID" ]; then
            key="$KITTY_PID-$KITTY_WINDOW_ID"
            printf '%s' "$key" > "$map"
        fi
    fi
    [ -n "$key" ] || exit 0    # truly unmappable: nothing to flag
    kpid="${key%-*}"
    wid="${key#*-}"
fi

[ -n "$wid" ] && [ -n "$kpid" ] || exit 0
f="$dir/$kpid-$wid"

# Dedupe: PostToolUse fires "working" on every tool call.
prev="$(cat "$f" 2>/dev/null)"
[ "$prev" = "$state" ] && exit 0

# Never downgrade a finished turn. Claude Code fires a "waiting for your
# input" Notification ~60s after every completed turn; real attention events
# (permission prompts, questions) arrive MID-turn while state is "working".
[ "$state" = attention ] && [ "$prev" = "done" ] && exit 0
if [ "$state" = reset ]; then rm -f "$f"; else printf '%s' "$state" > "$f"; fi
[ "$state" != attention ] && rm -f "$dir/.esc-$kpid-$wid" 2>/dev/null  # answered: clear escalation

# Attention side-effects (fire only on transition thanks to dedupe above):
# OS notification with Purr sound when kitty isn't frontmost; meow if the
# user has dropped a sound file at ~/.claude/sounds/meow.*. Never blocks.
if [ "$state" = attention ]; then
    (
        lsappinfo info -only name "$(lsappinfo front)" 2>/dev/null | grep -qi kitty || \
            osascript -e 'display notification "A Claude session needs your input" with title "ᓚᘏᗢ Nekotron" sound name "Purr"' 2>/dev/null
        m=$(ls ~/.claude/sounds/meow.* 2>/dev/null | head -1)
        [ -n "$m" ] && afplay "$m" 2>/dev/null
    ) &
fi

# NOTE: no remote-control calls here on purpose. The custom tab bar reads the
# state files directly; per-event kitten connections once piled up 100+ orphaned
# sockets and wedged kitty's remote control entirely (2026-07-10).

exit 0

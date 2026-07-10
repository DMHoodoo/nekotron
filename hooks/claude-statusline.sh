#!/bin/bash
# Claude Code statusline: session footer + Nekotron context watchdog.
# Receives session JSON on stdin every update. Renders one line, and:
#   - writes ctx-<kitty_pid>-<window_id> for the tab bar / fleet board
#   - purrs once when a session crosses 90% context (resets below 50%)
#   - triggers a debounced workspace snapshot at most every 30 min

input=$(cat)
dir=/tmp/claude-kitty-status
mkdir -p "$dir" 2>/dev/null
printf '%s' "$input" > "$dir/.statusline-sample.json" 2>/dev/null

j() { printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null; }

model=$(j '.model.display_name')
[ -z "$model" ] && model=$(j '.model.id')
cost=$(j '.cost.total_cost_usd')

# context %: try the shapes different builds expose
pct=$(printf '%s' "$input" | jq -r '
  (.context_window.used_percentage
   // .context_usage.percentage
   // .context.used_percent
   // empty)' 2>/dev/null | cut -d. -f1)
if [ -z "$pct" ]; then
    used=$(printf '%s' "$input" | jq -r '(.context_window.current_usage // .context_window.used_tokens // empty)' 2>/dev/null | cut -d. -f1)
    total=$(printf '%s' "$input" | jq -r '(.context_window.context_window_size // .context_window.total_tokens // empty)' 2>/dev/null | cut -d. -f1)
    if [ -n "$used" ] && [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then
        pct=$((used * 100 / total))
    fi
fi
[ -z "$pct" ] && [ "$(j '.exceeds_200k_tokens')" = "true" ] && pct=100

out="\033[38;2;107;115;148m${model}\033[0m"
if [ -n "$pct" ]; then
    color="2;107;115;148"                       # dim
    [ "$pct" -ge 70 ] 2>/dev/null && color="2;255;182;92"   # amber
    [ "$pct" -ge 88 ] 2>/dev/null && color="2;240;128;60"   # orange
    out="$out \033[38;2;58;65;96m·\033[0m \033[38;${color}mctx ${pct}%\033[0m"
    if [ -n "$KITTY_PID" ] && [ -n "$KITTY_WINDOW_ID" ]; then
        printf '%s' "$pct" > "$dir/ctx-$KITTY_PID-$KITTY_WINDOW_ID"
        # usage feeds for the fleet board: per-session cost + account rate limits
        [ -n "$cost" ] && printf '%s' "$cost" > "$dir/usage-$KITTY_PID-$KITTY_WINDOW_ID"
        limits=$(printf '%s' "$input" | jq -c '.rate_limits // empty' 2>/dev/null)
        [ -n "$limits" ] && printf '%s' "$limits" > "$dir/usage-limits"
        # cost burn-rate ledger: one sample per session per 5 min
        sid=$(j '.session_id')
        if [ -n "$cost" ] && [ -n "$sid" ]; then
            cl="$dir/.costlog-$KITTY_PID-$KITTY_WINDOW_ID"
            if [ -z "$(find "$cl" -mmin -5 2>/dev/null)" ]; then
                touch "$cl"
                printf '%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M')" "$sid" "$cost" "$model" \
                    >> "$HOME/.claude/cost-ledger.tsv"
            fi
        fi
        marker="$dir/.ctxwarn-$KITTY_PID-$KITTY_WINDOW_ID"
        if [ "$pct" -ge 90 ] && [ ! -f "$marker" ]; then
            touch "$marker"
            osascript -e 'display notification "Session context ≥90% — wrap up or /compact before it wedges" with title "ᓚᘏᗢ Nekotron" sound name "Purr"' 2>/dev/null &
        fi
        [ "$pct" -lt 50 ] 2>/dev/null && rm -f "$marker"
    fi
fi
[ -n "$cost" ] && out="$out \033[38;2;58;65;96m·\033[0m \033[38;2;107;115;148m\$$(printf '%.2f' "$cost" 2>/dev/null || printf '%s' "$cost")\033[0m"
printf '%b' "$out"

# attention escalation: any session sitting orange >10 min gets a re-purr
# (re-nudge at most every 15 min per session; scan at most once a minute)
if [ -z "$(find "$dir/.esc-scan" -mmin -1 2>/dev/null)" ]; then
    touch "$dir/.esc-scan"
    for f in "$dir"/*-*; do
        base=$(basename "$f")
        case "$base" in *[!0-9-]*) continue ;; esac   # state files are <pid>-<wid> only
        [ "$(cat "$f" 2>/dev/null)" = "attention" ] || continue
        [ -n "$(find "$f" -mmin +10 2>/dev/null)" ] || continue
        esc="$dir/.esc-$base"
        [ -n "$(find "$esc" -mmin -15 2>/dev/null)" ] && continue
        touch "$esc"
        osascript -e 'display notification "A session has been waiting on you for 10+ minutes (⌘⇧A)" with title "ᓚᘏᗢ Nekotron — still waiting" sound name "Purr"' 2>/dev/null &
    done
fi

# debounced auto-snapshot: at most every 30 min, one runner at a time
f="$HOME/.config/kitty/claude-restore.session"
find "$dir/.snap-lock" -mmin +10 -exec rmdir {} \; 2>/dev/null
if [ -z "$(find "$f" -mmin -30 2>/dev/null)" ] && mkdir "$dir/.snap-lock" 2>/dev/null; then
    ( sleep 2; "$HOME/bin/kitty-claude-snapshot.sh" >/dev/null 2>&1; rmdir "$dir/.snap-lock" 2>/dev/null ) &
fi
exit 0

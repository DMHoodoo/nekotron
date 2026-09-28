#!/bin/bash
# Stop hook: if Claude's just-finished reply references image files
# ([[img:/path]] or markdown ![](path)), pop an overlay in THIS tab showing
# them. Toggle off: touch ~/.config/nekotron/no-img-autopop
[ -f "$HOME/.config/nekotron/no-img-autopop" ] && exit 0
KP="$KITTY_PID"; WID="$KITTY_WINDOW_ID"
if [ -n "$TMUX" ]; then
    # tmux inherits STALE kitty env — use the tab-status hook's resolved cache
    map="/tmp/claude-kitty-status/.map-${PPID}"
    now=$(date +%s); mt=$(stat -f %m "$map" 2>/dev/null || echo 0)
    if [ $((now - mt)) -lt 300 ]; then
        cached=$(cat "$map" 2>/dev/null)
        KP="${cached%%-*}"; WID="${cached##*-}"
    else
        # same resolution the tab-status hook uses: tmux client -> kitty window
        sess=$(tmux display-message -pt "$TMUX_PANE" '#{session_name}' 2>/dev/null)
        cpids=$(tmux list-clients -t "$sess" -F '#{client_pid}' 2>/dev/null)
        sock0=$(ls -t /tmp/kitty-ctl-* 2>/dev/null | head -1)
        if [ -n "$cpids" ] && [ -n "$sock0" ]; then
            KITTEN0="$(command -v kitten || echo /Applications/kitty.app/Contents/MacOS/kitten)"
            rwid=$("$KITTEN0" @ --to "unix:$sock0" ls 2>/dev/null | /usr/bin/env jq -r --arg p "$cpids" \
                '($p | split("\n") | map(select(length>0) | tonumber)) as $clients | first(.[] | .tabs[] | .windows[] | select(any(.foreground_processes[]?; .pid as $pid | $clients | index($pid))) | .id) // empty' 2>/dev/null \
                || /opt/homebrew/bin/jq --version >/dev/null 2>&1 && "$KITTEN0" @ --to "unix:$sock0" ls 2>/dev/null | /opt/homebrew/bin/jq -r --arg p "$cpids" \
                '($p | split("\n") | map(select(length>0) | tonumber)) as $clients | first(.[] | .tabs[] | .windows[] | select(any(.foreground_processes[]?; .pid as $pid | $clients | index($pid))) | .id) // empty')
            [ -n "$rwid" ] && { KP="${sock0##*-}"; WID="$rwid"; } || exit 0
        else
            exit 0   # truly unresolvable; skip rather than mis-pop
        fi
    fi
fi
[ -n "$KP" ] && [ -n "$WID" ] || exit 0
input=$(cat)
tp=$(printf '%s' "$input" | /usr/bin/jq -r '.transcript_path // empty' 2>/dev/null)
[ -f "$tp" ] || exit 0

paths=$(/usr/bin/tail -c 300000 "$tp" | /usr/bin/python3 -c '
import sys, json, os, re
IMG = re.compile(r"\[\[img:([^\]\n]+?)\]\]|file://(/[^\s)\"]+?\.(?:png|jpe?g|gif|webp))|!\[[^\]\n]*\]\(([^)\n]+?\.(?:png|jpe?g|gif|webp))\)", re.I)
last = None
for line in sys.stdin:
    if "[[img:" not in line and "![" not in line:
        continue
    try:
        d = json.loads(line)
    except ValueError:
        continue
    if d.get("type") == "assistant":
        last = d
if last:
    cwd = last.get("cwd", "")
    seen = []
    for part in (last.get("message") or {}).get("content", []):
        if part.get("type") != "text":
            continue
        for m in IMG.finditer(part.get("text", "")):
            p = os.path.expanduser((m.group(1) or m.group(2) or m.group(3)).strip())
            if not os.path.isabs(p) and cwd:
                p = os.path.join(cwd, p)
            if os.path.isfile(p) and p not in seen:
                seen.append(p)
    print("\n".join(seen[-4:]))
' 2>/dev/null)
[ -n "$paths" ] || exit 0

sock="/tmp/kitty-ctl-$KP"
[ -S "$sock" ] || sock=$(ls -t /tmp/kitty-ctl-* 2>/dev/null | head -1)
[ -n "$sock" ] || exit 0
KITTEN="$(command -v kitten || echo /Applications/kitty.app/Contents/MacOS/kitten)"

# persistent rail: append to the tab's spool; create the split if absent
spool="/tmp/claude-kitty-status/imgs-$KP-$WID"
printf '%s\n' "$paths" >> "$spool"
if ! "$KITTEN" @ --to "unix:$sock" ls 2>/dev/null | /usr/bin/grep -q "\"imgrail-$WID\""; then
    "$KITTEN" @ --to "unix:$sock" launch --match "id:$WID" --type=window \
        --bias 25 --keep-focus --title "imgrail-$WID" \
        "$HOME/.config/kitty/img-rail.py" "$spool" >/dev/null 2>&1 \
    || printf '%s\n' "$paths" | /usr/bin/xargs "$KITTEN" @ --to "unix:$sock" launch \
        --type=overlay --match "id:$WID" \
        "$HOME/.config/kitty/img-show.py" >/dev/null 2>&1 &
fi
exit 0

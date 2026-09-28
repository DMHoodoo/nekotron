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
        exit 0   # can't resolve the window safely; skip rather than mis-pop
    fi
fi
[ -n "$KP" ] && [ -n "$WID" ] || exit 0
input=$(cat)
tp=$(printf '%s' "$input" | /usr/bin/jq -r '.transcript_path // empty' 2>/dev/null)
[ -f "$tp" ] || exit 0

paths=$(/usr/bin/tail -c 300000 "$tp" | /usr/bin/python3 -c '
import sys, json, os, re
IMG = re.compile(r"\[\[img:([^\]\n]+?)\]\]|!\[[^\]\n]*\]\(([^)\n]+?\.(?:png|jpe?g|gif|webp))\)", re.I)
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
            p = os.path.expanduser((m.group(1) or m.group(2)).strip())
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
# shellcheck disable=SC2086
printf '%s\n' "$paths" | /usr/bin/xargs "$KITTEN" @ --to "unix:$sock" launch \
    --type=overlay --match "id:$WID" \
    "$HOME/.config/kitty/img-show.py" >/dev/null 2>&1 &
exit 0

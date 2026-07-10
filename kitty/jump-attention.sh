#!/bin/bash
# Nekotron jump key (cmd+shift+a): focus the tab that needs you.
# Priority: attention first, then most-recent done. Silent no-op otherwise.

dir=/tmp/claude-kitty-status
sock=""
for s in $(ls -t /tmp/kitty-ctl-* 2>/dev/null); do
    kill -0 "${s##*-}" 2>/dev/null && sock="$s" && break
done
[ -n "$sock" ] || exit 0
kpid="${sock##*-}"
KITTEN="$(command -v kitten || echo /Applications/kitty.app/Contents/MacOS/kitten)"

jump() { "$KITTEN" @ --to "unix:$sock" focus-window --match "id:$1" >/dev/null 2>&1; }

for want in attention done; do
    # newest state file first, so "done" jumps to the most recently finished
    for f in $(ls -t "$dir/$kpid-"* 2>/dev/null); do
        [ "$(cat "$f" 2>/dev/null)" = "$want" ] || continue
        jump "${f##*-}" && exit 0
    done
done
exit 0

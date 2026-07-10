#!/bin/bash
# Nekotron day/night shift — applies the time-appropriate ground to every
# window, on demand (alias: theme). Night (19:00–06:59) warms the void.
# No daemon: run it when you feel it, or wire to launchd later if wanted.

sock=""
for s in $(ls -t /tmp/kitty-ctl-* 2>/dev/null); do
    kill -0 "${s##*-}" 2>/dev/null && sock="$s" && break
done
[ -n "$sock" ] || { echo "no live kitty socket"; exit 1; }
KITTEN="$(command -v kitten || echo /Applications/kitty.app/Contents/MacOS/kitten)"

h=$(date +%H)
if [ "$h" -ge 19 ] || [ "$h" -lt 7 ]; then
    bg="#120e14"; sel="#ffb65c"; mode="night (warm void)"
else
    bg="#0a0d18"; sel="#5fe9df"; mode="day (control room)"
fi

"$KITTEN" @ --to "unix:$sock" set-colors --all --configured \
    background="$bg" selection_background="$sel" >/dev/null 2>&1 \
    && echo "ᓚᘏᗢ theme: $mode"

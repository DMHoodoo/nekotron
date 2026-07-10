#!/bin/bash
# Nekotron new-shell splash: cat + one-line fleet state. Budget: <10ms.
# Wired into ~/.zshrc for interactive kitty shells only.

dir=/tmp/claude-kitty-status
k="${KITTY_PID:-0}"
w=0; d=0; a=0
for f in "$dir/$k"-*; do
    [ -f "$f" ] || continue
    case "$(cat "$f" 2>/dev/null)" in
        working)   w=$((w+1)) ;;
        done)      d=$((d+1)) ;;
        attention) a=$((a+1)) ;;
    esac
done

C=$'\033[38;2;95;233;223m'   # cyan
A=$'\033[38;2;255;182;92m'   # amber
D=$'\033[38;2;107;115;148m'  # dim
O=$'\033[38;2;240;128;60m'   # attention orange
B=$'\033[1m'; R=$'\033[0m'

fleet="${C}⠿ ${w} working${R}"
[ "$a" -gt 0 ] && fleet+="${D} · ${R}${O}● ${a} need you${R}"
fleet+="${D} · ✓ ${d} done${R}"

printf '\n'
printf '   %s∧,,∧%s\n'                "$A" "$R"
printf '  %s( ̳• · • ̳)%s   %s%sNEKOTRON%s  %s%s%s\n' "$A" "$R" "$B" "$C" "$R" "$D" "$(date '+%a %H:%M')" "$R"
printf '  %s/    づ%s     %b  %s⌘⇧F board · ⌘⇧K keys%s\n' "$A" "$R" "$fleet" "$D" "$R"
printf '\n'

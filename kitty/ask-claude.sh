#!/bin/bash
# ⌘⇧X: kitty pipes this window's scrollback to stdin; we hand it to a fresh
# Claude in a new tab (cwd inherited from the source window).
# ASK_DRY=1 prints the prompt instead of launching (testing).

f=$(mktemp /tmp/kitty-screen-XXXXXX.txt)
# strip ANSI/OSC noise, keep the last 400 lines
perl -pe 's/\e\[[0-9;]*[A-Za-z]//g; s/\e\][^\a\e]*(\a|\e\\)//g' 2>/dev/null | tail -400 > "$f"

lines=$(wc -l < "$f" | tr -d ' ')
export ASK_PROMPT="I captured my terminal screen to $f ($lines lines, ANSI stripped, newest at the bottom). Read it and tell me what's happening — if there's an error or failure in it, diagnose the cause and give me the fix."

if [ -n "$ASK_DRY" ]; then
    echo "would launch claude with prompt referencing $f"
    exit 0
fi

# reclaim a real tty for claude's TUI (our stdin was the scrollback pipe)
exec < /dev/tty
exec zsh -l -i -c 'claude "$ASK_PROMPT"; exec zsh'

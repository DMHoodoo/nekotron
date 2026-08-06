#!/usr/bin/env python3
"""Nekotron keybind cheatsheet (cmd+shift+k, kitty overlay).

Parses the live `map` lines out of kitty.conf (never goes stale) and adds
the built-in keys worth remembering. Any key dismisses.
"""
import os
import re
import sys

CYAN, MAG, AMBER, DIM, INK, RST = ("\033[38;2;95;233;223m", "\033[38;2;255;95;168m",
                                   "\033[38;2;255;182;92m", "\033[38;2;107;115;148m",
                                   "\033[38;2;232;236;255m", "\033[0m")

PRETTY = {"cmd": "⌘", "shift": "⇧", "ctrl": "⌃", "opt": "⌥", "alt": "⌥"}
DESC = {
    "fleet-board.py": "fleet board — every session, states, vitals; digits jump",
    "jump-attention.sh": "jump to the session that needs you",
    "fleet-say.py": "broadcast one message to every Claude",
    "fleet-peek.py": "peek any tab's live screen without switching",
    "keys-help.py": "this cheatsheet",
    "goto_tab": "go to tab",
    "send_key page_up": "page up (Claude Code scrollback)",
    "send_key page_down": "page down",
    "linenum": "open file:line from screen in Cursor",
    "--type regex": "copy a UUID from screen to clipboard",
    "kitten hints": "open a URL from screen",
    "show_scrollback": "search full scrollback in a pager (/ to search)",
    "focus_visible_window": "letter-hop between splits",
    "toggle_marker": "toggle ERROR red / PASS green highlighting",
}
BUILTINS = [
    ("⌘T / ⌘W", "new tab / close"),
    ("⌘1…⌘9", "go to tab N"),
    ("⌃⌘F", "toggle fullscreen (no titlebar needed)"),
    ("⌘= / ⌘-", "font size bigger / smaller"),
    ("⌃⇧F5", "reload kitty.conf (maps & colors, not tab_bar.py)"),
    ("drag / right-click", "reorder tabs in the tab bar"),
]


def pretty_key(k):
    parts = k.split("+")
    return "".join(PRETTY.get(p, p.upper() if len(p) == 1 else p) for p in parts)


def describe(action):
    for frag, d in DESC.items():
        if frag in action:
            if frag == "goto_tab":
                return f"go to tab {action.split()[-1]}"
            return d
    return action[:52]


def main():
    conf = os.path.expanduser("~/.config/kitty/kitty.conf")
    maps = []
    files = [conf]
    seen = set()
    while files:
        fp = files.pop(0)
        if fp in seen or not os.path.exists(fp):
            continue
        seen.add(fp)
        with open(fp) as f:
            for line in f:
                inc = re.match(r"\s*include\s+(\S+)", line)
                if inc:
                    files.append(os.path.expanduser(inc.group(1)))
                    continue
                m = re.match(r"\s*map\s+(\S+)\s+(.+)", line)
                if m:
                    maps.append((pretty_key(m.group(1)), describe(m.group(2).strip())))

    print(f"\n  {AMBER}ᓚᘏᗢ{RST}  {CYAN}KEYBINDS{RST}\n")
    print(f"  {MAG}yours (live from kitty.conf){RST}")
    for k, d in maps:
        print(f"    {INK}{k:<14}{RST}{DIM}{d}{RST}")
    print(f"\n  {MAG}built-in{RST}")
    for k, d in BUILTINS:
        print(f"    {INK}{k:<14}{RST}{DIM}{d}{RST}")
    print(f"\n  {DIM}any key to dismiss{RST}")

    if "--print" in sys.argv:
        return
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"keys-help error: {e}")
        import time; time.sleep(2)

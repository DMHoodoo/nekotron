#!/usr/bin/env python3
"""Nekotron fleet broadcast (cmd+shift+b, kitty overlay).

Type one line, send it to every window running claude. Confirms target
count first. --list prints targets without sending (for testing).
"""
import glob
import json
import os
import shutil
import subprocess
import sys

CYAN, AMBER, DIM, RST = "\033[38;2;95;233;223m", "\033[38;2;255;182;92m", "\033[38;2;107;115;148m", "\033[0m"
KITTEN = shutil.which("kitten") or "/Applications/kitty.app/Contents/MacOS/kitten"


def _alive(s):
    try:
        os.kill(int(s.rsplit("-", 1)[-1]), 0)
        return True
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def main():
    socks = [s for s in sorted(glob.glob("/tmp/kitty-ctl-*"), key=os.path.getmtime, reverse=True)
             if _alive(s)]
    if not socks:
        print("no live kitty socket"); return
    sock = f"unix:{socks[0]}"
    ls = json.loads(subprocess.run([KITTEN, "@", "--to", sock, "ls"],
                                   capture_output=True, text=True, timeout=5).stdout)
    targets = []  # (window_id, tab_title)
    for osw in ls:
        for tab in osw.get("tabs", []):
            for w in tab.get("windows", []):
                for fp in w.get("foreground_processes", []) or []:
                    cmd = os.path.basename((fp.get("cmdline") or [""])[0])
                    if cmd == "claude":
                        targets.append((w["id"], tab.get("title", "")[:40]))
                        break

    if not targets:
        print("no claude windows found"); input(); return

    print(f"\n  {AMBER}ᓚᘏᗢ{RST}  {CYAN}FLEET BROADCAST{RST}  {DIM}— {len(targets)} claude session(s){RST}\n")
    for wid, title in targets:
        print(f"    {DIM}window {wid:<4}{RST} {title}")
    if "--list" in sys.argv:
        return

    try:
        line = input(f"\n  {CYAN}message ❯{RST} ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not line:
        return
    ok = input(f"  send to {len(targets)} session(s)? [y/N] ").strip().lower()
    if ok != "y":
        print("  aborted"); return

    for wid, _ in targets:
        subprocess.run([KITTEN, "@", "--to", sock, "send-text", "--match", f"id:{wid}",
                        "--", line + "\r"], capture_output=True)
    print(f"  {CYAN}sent to {len(targets)} session(s){RST}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"fleet-say error: {e}")
        input()

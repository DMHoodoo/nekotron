#!/usr/bin/env python3
"""Nekotron image rail — a persistent split pane that renders the images a
Claude session references ([[img:]] / markdown) and STAYS. Watches a spool
file; re-renders when it changes. q closes.
  img-rail.py <spool-file>
"""
import os
import select
import shutil
import subprocess
import sys
import termios
import time
import tty

KITTEN = shutil.which("kitten") or "/Applications/kitty.app/Contents/MacOS/kitten"
CYAN = "\033[38;2;95;233;223m"
AMBER = "\033[38;2;255;182;92m"
DIM = "\033[38;2;107;115;148m"
BOLD, RST = "\033[1m", "\033[0m"


def read_spool(spool):
    try:
        return [p for p in open(spool).read().splitlines() if os.path.isfile(p)]
    except OSError:
        return []


def render(spool):
    # 2J clears TEXT only — kitty graphics placements survive it and stack
    # as ghosts across re-renders; delete all images first, every time.
    sys.stdout.write("\033_Ga=d,d=A\033\\" + "\033[2J\033[H")
    paths = read_spool(spool)
    shown = paths[-3:]
    print(f" {AMBER}\u14da\u160f\u15e2{RST} {BOLD}{CYAN}IMAGE RAIL{RST}  "
          f"{DIM}1-{len(shown) or 1} remove \u00b7 C clear \u00b7 q close{RST}\n")
    if not shown:
        print(f" {DIM}(waiting for images in this chat){RST}")
    for i, p in enumerate(shown, 1):
        subprocess.run([KITTEN, "icat", "--align", "left", p])
        print(f" {CYAN}{i}{RST} {DIM}\u00b7 {os.path.basename(p)}{RST}\n")
    sys.stdout.flush()
    return paths, shown


def main():
    spool = sys.argv[1] if len(sys.argv) > 1 else ""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\033[?25l")
    last = -1.0
    paths, shown = [], []
    try:
        while True:
            try:
                mt = os.path.getmtime(spool)
            except OSError:
                mt = 0
            if mt != last:
                last = mt
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                paths, shown = render(spool)
                tty.setraw(fd)
            r, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not r:
                continue
            ch = sys.stdin.read(1)
            if ch in ("q", "\x1b"):
                break
            if ch == "C":
                open(spool, "w").close()   # mtime change re-renders empty
            elif ch.isdigit() and 0 < int(ch) <= len(shown):
                idx = len(paths) - len(shown) + int(ch) - 1
                del paths[idx]
                open(spool, "w").write("\n".join(paths) + ("\n" if paths else ""))
    finally:
        sys.stdout.write("\033[?25h\033[0m")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"img-rail error: {e}")
        time.sleep(2)

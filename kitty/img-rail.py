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


def render(spool):
    sys.stdout.write("\033[2J\033[H")
    print(f" {AMBER}ᓚᘏᗢ{RST} {BOLD}{CYAN}IMAGE RAIL{RST}  {DIM}q closes{RST}\n")
    try:
        paths = [p for p in open(spool).read().splitlines() if os.path.isfile(p)]
    except OSError:
        paths = []
    if not paths:
        print(f" {DIM}(waiting for [[img:...]] in this chat){RST}")
    for p in paths[-3:]:
        subprocess.run([KITTEN, "icat", "--align", "left", p])
        print(f" {DIM}{os.path.basename(p)}{RST}\n")
    sys.stdout.flush()


def main():
    spool = sys.argv[1] if len(sys.argv) > 1 else ""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\033[?25l")
    last = -1.0
    try:
        while True:
            try:
                mt = os.path.getmtime(spool)
            except OSError:
                mt = 0
            if mt != last:
                last = mt
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                render(spool)
                tty.setraw(fd)
            r, _, _ = select.select([sys.stdin], [], [], 0.5)
            if r and sys.stdin.read(1) in ("q", "\x1b"):
                break
    finally:
        sys.stdout.write("\033[?25h\033[0m")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"img-rail error: {e}")
        time.sleep(2)

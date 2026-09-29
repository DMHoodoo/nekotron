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
    """Absolute layout: every image gets a bounded box (icat --place never
    scrolls). Full-width icat overflowed the pane and each re-render
    scrolled it further — the 'rail keeps growing' bug."""
    ts = shutil.get_terminal_size((80, 24))
    sys.stdout.write("\033_Ga=d,d=A\033\\" + "\033[2J\033[H")
    sys.stdout.flush()
    paths = read_spool(spool)
    shown = paths[-3:]
    sys.stdout.write(f"\033[1;1H {AMBER}\u14da\u160f\u15e2{RST} {BOLD}{CYAN}IMAGE RAIL{RST}  "
                     f"{DIM}1-{len(shown) or 1} remove \u00b7 C clear \u00b7 q close{RST}")
    if not shown:
        sys.stdout.write(f"\033[3;2H{DIM}(waiting for images in this chat){RST}")
    sys.stdout.flush()
    if shown:
        avail = ts.lines - 2                       # rows below the header
        box_h = max(3, avail // len(shown) - 2)
        box_w = max(10, ts.columns - 4)
        y = 2
        for i, p in enumerate(shown, 1):
            subprocess.run([KITTEN, "icat", "--place", f"{box_w}x{box_h}@2x{y}",
                            "--align", "left", "--z-index", "1", p],
                           stderr=subprocess.DEVNULL)
            sys.stdout.write(f"\033[{min(ts.lines, y + box_h + 1)};2H"
                             f"{CYAN}{i}{RST} {DIM}\u00b7 {os.path.basename(p)}{RST}")
            sys.stdout.flush()
            y += box_h + 2
    return paths, shown


def _self_dedupe():
    """Only one rail per tab: newest yields to the incumbent."""
    me = os.environ.get("KITTY_WINDOW_ID")
    kp = os.environ.get("KITTY_PID")
    if not me or not kp:
        return
    try:
        import json
        out = subprocess.run([KITTEN, "@", "--to", f"unix:/tmp/kitty-ctl-{kp}", "ls"],
                             capture_output=True, text=True, timeout=3).stdout
        for osw in json.loads(out):
            for tab in osw.get("tabs", []):
                ids = [w["id"] for w in tab.get("windows", [])]
                if int(me) not in ids:
                    continue
                rails = [w["id"] for w in tab.get("windows", [])
                         if (w.get("title") or "").startswith("imgrail-")
                         or "img-rail" in " ".join(
                             " ".join(p.get("cmdline") or []) for p in w.get("foreground_processes") or [])]
                others = [i for i in rails if i != int(me)]
                if others and min(others) < int(me):
                    open("/tmp/img-rail.log", "a").write(
                        f"dedupe: win {me} yields to {min(others)}\n")
                    sys.exit(0)
    except Exception:
        pass


def main():
    _self_dedupe()
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

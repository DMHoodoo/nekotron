#!/usr/bin/env python3
"""Nekotron image view (kitty overlay).

Two modes:
  img-show.py <path> [path...]   render the given images (used by the
                                 Stop-hook auto-pop when a Claude reply
                                 references images)
  img-show.py --scan             find recent images in THIS tab's Claude
                                 session transcript and render them (⌘⇧I)

Detects [[img:/path.png]] and markdown ![alt](/path.png). Any key closes.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

KITTEN = shutil.which("kitten") or "/Applications/kitty.app/Contents/MacOS/kitten"
LEDGER = os.path.expanduser("~/.claude/session-ledger.tsv")
PROJECTS = os.path.expanduser("~/.claude/projects")

CYAN = "\033[38;2;95;233;223m"
AMBER = "\033[38;2;255;182;92m"
DIM = "\033[38;2;107;115;148m"
BOLD, RST = "\033[1m", "\033[0m"

IMG_RE = re.compile(
    r"\[\[img:([^\]\n]+?)\]\]|file://(/[^\s)\"']+?\.(?:png|jpe?g|gif|webp))"                       # [[img:/path]]
    r"|!\[[^\]\n]*\]\(([^)\n]+?\.(?:png|jpe?g|gif|webp))\)",  # ![alt](/path.png)
    re.I)


def found_images(text, cwd=""):
    out = []
    for m in IMG_RE.finditer(text):
        p = (m.group(1) or m.group(2) or m.group(3)).strip()
        p = os.path.expanduser(p)
        if not os.path.isabs(p) and cwd:
            p = os.path.join(cwd, p)
        if os.path.isfile(p) and p not in out:
            out.append(p)
    return out


def scan_transcript():
    """This tab's session -> recent image paths from assistant messages."""
    kp = os.environ.get("KITTY_PID", "")
    sock = f"/tmp/kitty-ctl-{kp}"
    sid = None
    try:
        ls = json.loads(subprocess.run([KITTEN, "@", "--to", f"unix:{sock}", "ls"],
                                       capture_output=True, text=True, timeout=3).stdout)
        wid = None
        for osw in ls:
            for tab in osw.get("tabs", []):
                wins = tab.get("windows", [])
                if any(w.get("is_self") for w in wins):
                    others = [w for w in wins if not w.get("is_self")]
                    wid = others[0].get("id") if others else None
        key = f"{kp}-{wid}"
        for row in open(LEDGER):
            parts = row.rstrip("\n").split("\t")
            if len(parts) >= 4 and parts[3] == key:
                sid = parts[1]
    except Exception:
        pass
    if not sid:
        return []
    hits = glob.glob(f"{PROJECTS}/*/{sid}.jsonl")
    if not hits:
        return []
    tp = max(hits, key=os.path.getmtime)
    size = os.path.getsize(tp)
    with open(tp, "rb") as f:
        f.seek(max(0, size - 2 * 1024 * 1024))
        raw = f.read().decode("utf-8", "replace")
    imgs = []
    for line in raw.splitlines():
        if "[[img:" not in line and "![" not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        cwd = d.get("cwd", "")
        for part in (d.get("message") or {}).get("content", []):
            if part.get("type") == "text":
                for p in found_images(part.get("text", ""), cwd):
                    if p in imgs:
                        imgs.remove(p)
                    imgs.append(p)
    return imgs[-6:]


def main():
    if "--scan" in sys.argv:
        paths = scan_transcript()
        title = "recent images in this chat"
    else:
        paths = [p for p in sys.argv[1:] if os.path.isfile(p)]
        title = "from Claude's reply"
    print(f"\n  {AMBER}ᓚᘏᗢ{RST}  {BOLD}{CYAN}IMAGES{RST}   {DIM}{title}{RST}\n")
    if not paths:
        print(f"  {DIM}(no image references found){RST}")
    for p in paths:
        subprocess.run([KITTEN, "icat", "--align", "left", p])
        print(f"  {DIM}{p.replace(os.path.expanduser('~'), '~')}{RST}\n")
    print(f"  {DIM}any key to close{RST}")
    import termios
    import tty
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
        print(f"img-show error: {e}")
        time.sleep(2)

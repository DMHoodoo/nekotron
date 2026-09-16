#!/usr/bin/env python3
"""Nekotron code copy (cmd+shift+c, kitty overlay).

Lists the recent fenced code blocks from the ACTIVE tab's Claude session
(read from the transcript, so you get the exact original text — not the
screen-wrapped rendering) and copies one to the clipboard on a digit.
  --print   render the block list once (testing)
"""
import glob
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time

# kitty overlays get a minimal PATH — resolve binaries absolutely
KITTEN = shutil.which("kitten") or "/Applications/kitty.app/Contents/MacOS/kitten"
LEDGER = os.path.expanduser("~/.claude/session-ledger.tsv")
PROJECTS = os.path.expanduser("~/.claude/projects")

CYAN = "\033[38;2;95;233;223m"
MAG = "\033[38;2;255;95;168m"
AMBER = "\033[38;2;255;182;92m"
DIM = "\033[38;2;107;115;148m"
FAINT = "\033[38;2;58;65;96m"
INK = "\033[38;2;232;236;255m"
GREEN = "\033[38;2;76;195;138m"
BOLD, RST = "\033[1m", "\033[0m"

FENCE = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*\n(.*?)```", re.S)


def _sock_answers(s):
    try:
        r = subprocess.run([KITTEN, "@", "--to", f"unix:{s}", "ls"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or None
    except Exception:
        return None


def live_ls():
    cands = []
    kp = os.environ.get("KITTY_PID")
    if kp and os.path.exists(f"/tmp/kitty-ctl-{kp}"):
        cands.append(f"/tmp/kitty-ctl-{kp}")
    for s in sorted(glob.glob("/tmp/kitty-ctl-*"), key=os.path.getmtime, reverse=True):
        if s not in cands:
            cands.append(s)
    for s in cands:
        out = _sock_answers(s)
        if out:
            return s.rsplit("-", 1)[-1], json.loads(out)
    return None, None


def peer_window(ls):
    """The window under our overlay (the tab we were summoned on)."""
    for osw in ls or []:
        for tab in osw.get("tabs", []):
            wins = tab.get("windows", [])
            if any(w.get("is_self") for w in wins):
                others = [w for w in wins if not w.get("is_self")]
                return others[0] if others else None
    return None


def session_for(kpid, win):
    """kitty window -> Claude session id, via ledger then live pid map."""
    if win is None:
        return None
    key = f"{kpid}-{win.get('id')}"
    try:
        sid = None
        for row in open(LEDGER):
            parts = row.rstrip("\n").split("\t")
            if len(parts) >= 4 and parts[3] == key:
                sid = parts[1]
        if sid:
            return sid
    except OSError:
        pass
    return None


def transcript_path(sid):
    hits = glob.glob(f"{PROJECTS}/*/{sid}.jsonl")
    return max(hits, key=os.path.getmtime) if hits else None


def extract_blocks(path, tail_bytes=4 * 1024 * 1024, cap=9):
    """Newest-first fenced blocks from the transcript's assistant messages."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - tail_bytes))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    blocks, seen = [], set()
    for line in raw.splitlines():
        if '"```' not in line and "```" not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        for part in (d.get("message") or {}).get("content", []):
            if part.get("type") != "text":
                continue
            for lang, code in FENCE.findall(part.get("text", "")):
                code = code.rstrip("\n")
                h = hash(code)
                if code.strip() and h not in seen:
                    seen.add(h)
                    blocks.append((lang or "", code))
    blocks.reverse()  # newest first
    return blocks[:cap]


def render(blocks, cols):
    L = ["", f"  {AMBER}ᓚᘏᗢ{RST}  {BOLD}{CYAN}CODE BLOCKS{RST}   "
            f"{DIM}from this tab's Claude · newest first{RST}", ""]
    if not blocks:
        L.append(f"  {DIM}(no fenced code blocks found in this session){RST}")
    for i, (lang, code) in enumerate(blocks, 1):
        lines = code.splitlines()
        first = lines[0][: cols - 30] if lines else ""
        tag = f"{MAG}{lang}{RST} " if lang else ""
        L.append(f"  {INK}{i}{RST} {tag}{DIM}{len(lines)} line{'s' if len(lines) != 1 else ''}{RST}")
        L.append(f"     {FAINT}{first}{RST}")
        if len(lines) > 1:
            L.append(f"     {FAINT}{lines[1][: cols - 30]}{RST}")
        L.append("")
    L.append(f"  {DIM}1-{len(blocks)} copy a block · any other key exits{RST}")
    return L


def main():
    kpid, ls = live_ls()
    if not ls:
        print("no answering kitty socket"); return
    win = peer_window(ls)
    sid = session_for(kpid, win)
    tp = transcript_path(sid) if sid else None
    if not tp:
        print("no Claude session found for this tab"); time.sleep(2); return
    blocks = extract_blocks(tp)
    cols = shutil.get_terminal_size((160, 40)).columns

    if "--print" in sys.argv:
        print("\n".join(render(blocks, cols)))
        return

    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\033[?25l\033[2J")
    try:
        rows = render(blocks, cols)
        sys.stdout.write("".join(f"\033[{i + 1};1H{l}\033[K" for i, l in enumerate(rows)) + "\033[J")
        sys.stdout.flush()
        r, _, _ = select.select([sys.stdin], [], [], 60)
        ch = sys.stdin.read(1) if r else ""
        if ch.isdigit() and 0 < int(ch) <= len(blocks):
            lang, code = blocks[int(ch) - 1]
            subprocess.run(["/usr/bin/pbcopy"], input=code.encode())
            n = len(code.splitlines())
            sys.stdout.write(f"\033[{len(rows) + 2};1H  {GREEN}✓ copied {n} line"
                             f"{'s' if n != 1 else ''} to clipboard{RST}\033[K")
            sys.stdout.flush()
            time.sleep(0.55)
    finally:
        sys.stdout.write("\033[?25h\033[0m")
        import termios as _t
        _t.tcsetattr(fd, _t.TCSADRAIN, old)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"code copy error: {e}")
        time.sleep(2)

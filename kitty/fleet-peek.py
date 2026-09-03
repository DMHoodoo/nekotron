#!/usr/bin/env python3
"""Nekotron tab peek (cmd+shift+p, kitty overlay).

See any tab's live screen without switching to it: digits preview, enter
jumps to the previewed tab, any other key backs out. The preview refreshes
every second while open.
  --print    render the tab list once (testing)
  --peek N   render one preview frame of tab N (testing)
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
STATE_DIR = "/tmp/claude-kitty-status"

CYAN = "\033[38;2;95;233;223m"
MAG = "\033[38;2;255;95;168m"
AMBER = "\033[38;2;255;182;92m"
DIM = "\033[38;2;107;115;148m"
FAINT = "\033[38;2;58;65;96m"
INK = "\033[38;2;232;236;255m"
BOLD, RST = "\033[1m", "\033[0m"
ST_COLOR = {"working": "\033[38;2;79;142;247m", "done": "\033[38;2;76;195;138m",
            "attention": "\033[38;2;240;128;60m", "neutral": "\033[38;2;90;90;100m"}
ANSI = re.compile(r"\033\[[0-9;:]*m")  # get-text --ansi emits colon-style SGR


def vlen(s):
    return len(ANSI.sub("", s))


def vtrunc(s, limit):
    """ANSI-aware truncation, closing with a reset + ellipsis."""
    if vlen(s) <= limit:
        return s
    out, n = [], 0
    for tok in re.split(r"(\033\[[0-9;:]*m)", s):
        if tok.startswith("\033["):
            out.append(tok)
            continue
        room = limit - 1 - n
        if room <= 0:
            break
        out.append(tok[:room])
        n += min(len(tok), room)
    return "".join(out) + RST + "…"


def _sock_answers(s):
    """A socket that accepts but never replies (starved/wedged kitty) is useless."""
    try:
        r = subprocess.run([KITTEN, "@", "--to", f"unix:{s}", "ls"],
                           capture_output=True, text=True, timeout=3)
        return bool(r.stdout.strip())
    except Exception:
        return False


def live_sock():
    cands = []
    kp = os.environ.get("KITTY_PID")
    if kp and os.path.exists(f"/tmp/kitty-ctl-{kp}"):
        cands.append(f"/tmp/kitty-ctl-{kp}")  # our own kitty first
    for s in sorted(glob.glob("/tmp/kitty-ctl-*"), key=os.path.getmtime, reverse=True):
        if s not in cands:
            cands.append(s)
    best = None
    for s in cands:
        try:
            os.kill(int(s.rsplit("-", 1)[-1]), 0)
        except (ValueError, ProcessLookupError):
            try:
                os.unlink(s)  # crash leftover
            except OSError:
                pass
            continue
        except PermissionError:
            pass
        if best is None:
            best = s  # liveliest fallback if none answer
        if _sock_answers(s):
            return s
    return best


def tab_list(sock, kpid):
    out = subprocess.run([KITTEN, "@", "--to", f"unix:{sock}", "ls"],
                         capture_output=True, text=True, timeout=5).stdout
    if not out.strip():
        raise SystemExit("kitty control socket is WEDGED (leaked connections) — "
                         "restart kitty to recover")
    ls = json.loads(out)
    tabs = []
    for osw in ls:
        for tab in osw.get("tabs", []):
            all_wins = tab.get("windows", [])
            wins = [w for w in all_wins if not w.get("is_self")] or all_wins
            if not wins:
                continue
            state = "neutral"
            for w in wins:
                p = f"{STATE_DIR}/{kpid}-{w.get('id')}"
                if os.path.exists(p):
                    s = open(p).read().strip()
                    if s == "attention" or state == "neutral":
                        state = s if s in ST_COLOR else "neutral"
            title = tab.get("title") or ""
            if len(wins) < len(all_wins):
                title = wins[0].get("title") or title  # see through our overlay
            tabs.append({"title": title, "wid": wins[0].get("id"),
                         "state": state, "focused": bool(tab.get("is_focused"))})
    return tabs


def get_screen(sock, wid):
    try:
        r = subprocess.run([KITTEN, "@", "--to", f"unix:{sock}", "get-text",
                            "--match", f"id:{wid}", "--ansi", "--extent", "screen"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.splitlines()
    except Exception:
        pass
    return [f"{DIM}(could not read window {wid}){RST}"]


def draw(lines, cols, rows):
    """Absolute cursor addressing per line — raw mode has no newline CR."""
    buf = []
    for i, line in enumerate(lines[:rows]):
        buf.append(f"\033[{i + 1};1H{vtrunc(line, cols - 1)}\033[K")
    buf.append("\033[J")
    sys.stdout.write("".join(buf))
    sys.stdout.flush()


def list_lines(tabs):
    L = ["", f"  {AMBER}ᓚᘏᗢ{RST}  {BOLD}{CYAN}TAB PEEK{RST}   {DIM}{time.strftime('%H:%M')}{RST}", ""]
    for i, t in enumerate(tabs, 1):
        mark = f"{MAG}▶{RST}" if t["focused"] else " "
        c = ST_COLOR[t["state"]]
        L.append(f"  {mark} {INK}{i}{RST} {c}●{RST} {INK}{t['title'][:70]}{RST}")
    hint = f"1-9 · 0 = tab 10" if len(tabs) >= 10 else f"1-{len(tabs)}"
    L += ["", f"  {DIM}{hint} peek a tab · any other key exits{RST}"]
    return L


def preview_lines(tabs, idx, screen, cols):
    t = tabs[idx]
    c = ST_COLOR[t["state"]]
    head = (f"  {AMBER}ᓚᘏᗢ{RST}  {BOLD}{CYAN}PEEK {idx + 1}{RST} {c}●{RST} "
            f"{INK}{t['title'][:50]}{RST}   "
            f"{DIM}enter jumps · digits switch · any other key back{RST}")
    sep = "  " + FAINT + "─" * max(10, cols - 4) + RST
    return [head, sep] + screen


def main():
    sock = live_sock()
    if not sock:
        print("no live kitty socket"); return
    kpid = sock.rsplit("-", 1)[-1]
    tabs = tab_list(sock, kpid)
    if not tabs:
        print("no tabs found"); return
    ts = shutil.get_terminal_size((160, 40))

    if "--print" in sys.argv:
        print("\n".join(list_lines(tabs)))
        return
    if "--peek" in sys.argv:
        i = max(0, min(len(tabs) - 1, int(sys.argv[sys.argv.index("--peek") + 1]) - 1))
        print("\n".join(preview_lines(tabs, i, get_screen(sock, tabs[i]["wid"]), ts.columns)))
        return

    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\033[?25l\033[2J")
    mode_idx = None      # None = list view, else index of previewed tab
    jump = None
    screen = []
    last_fetch = 0.0
    try:
        while True:
            ts = shutil.get_terminal_size((160, 40))
            if mode_idx is None:
                draw(list_lines(tabs), ts.columns, ts.lines)
            else:
                if time.monotonic() - last_fetch > 1.0:  # live preview
                    screen = get_screen(sock, tabs[mode_idx]["wid"])
                    last_fetch = time.monotonic()
                draw(preview_lines(tabs, mode_idx, screen, ts.columns), ts.columns, ts.lines)
            r, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not r:
                continue
            ch = sys.stdin.read(1)
            sel = 10 if ch == "0" else (int(ch) if ch.isdigit() else 0)
            if 0 < sel <= len(tabs):
                mode_idx = sel - 1
                last_fetch = 0.0
            elif mode_idx is not None and ch in ("\r", "\n"):
                jump = mode_idx
                break
            elif mode_idx is not None:
                mode_idx = None
            else:
                break
    finally:
        sys.stdout.write("\033[?25h\033[0m")
        import termios as _t
        _t.tcsetattr(fd, _t.TCSADRAIN, old)
    if jump is not None:
        subprocess.run([KITTEN, "@", "--to", f"unix:{sock}", "focus-tab",
                        "--match", f"index:{jump}"], capture_output=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:  # deliberate diagnosis (e.g. wedged control socket)
        if e.code and not isinstance(e.code, int):
            print(f"\033[38;2;240;128;60m{e.code}\033[0m")
            time.sleep(6)
    except Exception as e:
        print(f"tab peek error: {e}")
        time.sleep(2)

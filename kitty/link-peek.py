#!/usr/bin/env python3
"""Nekotron link peek (cmd+shift+space, kitty overlay).

Mirrors the current window's screen 1:1 and makes image links hoverable:
move the mouse over a file:// image link (or [[img:]]) and the rendered
image floats beside the pointer. Click a link to send it to the image
rail. Any key closes.
  --print   list detected links once (testing)
"""
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
import unicodedata

KITTEN = shutil.which("kitten") or "/Applications/kitty.app/Contents/MacOS/kitten"
CYAN = "\033[38;2;95;233;223m"
DIM = "\033[38;2;107;115;148m"
ULC = "\033[4;38;2;95;233;223m"
RST = "\033[0m"
ANSI = re.compile(r"\033\[[0-9;:]*m")
IMG = re.compile(r"file://(/[^\s)\"]+?\.(?:png|jpe?g|gif|webp))|\[\[img:([^\]\n]+?)\]\]", re.I)


def _chw(ch):
    o = ord(ch)
    if unicodedata.combining(ch):
        return 0
    if o == 0xFE0F:
        return 1
    if unicodedata.east_asian_width(ch) in ("W", "F") or 0x1F000 <= o <= 0x1FAFF:
        return 2
    return 1


def vw(s):
    return sum(_chw(c) for c in s)


def peer_window():
    sock = None
    kp = os.environ.get("KITTY_PID")
    cands = [f"/tmp/kitty-ctl-{kp}"] if kp else []
    import glob as g
    cands += [s for s in sorted(g.glob("/tmp/kitty-ctl-*"), key=os.path.getmtime, reverse=True)
              if s not in cands]
    for s in cands:
        try:
            out = subprocess.run([KITTEN, "@", "--to", f"unix:{s}", "ls"],
                                 capture_output=True, text=True, timeout=3).stdout
            if out.strip():
                sock = s
                ls = json.loads(out)
                break
        except Exception:
            continue
    if not sock:
        return None, None
    for osw in ls:
        for tab in osw.get("tabs", []):
            wins = tab.get("windows", [])
            if any(w.get("is_self") for w in wins):
                others = [w for w in wins if not w.get("is_self")]
                return sock, (others[0].get("id") if others else None)
    return sock, None


def grab_screen(sock, wid):
    r = subprocess.run([KITTEN, "@", "--to", f"unix:{sock}", "get-text",
                        "--match", f"id:{wid}", "--ansi", "--extent", "screen"],
                       capture_output=True, text=True, timeout=5)
    return r.stdout.splitlines() if r.returncode == 0 else []


def link_map(lines):
    """[(row1based, col0, col1, path, shown_text)] from the screen text."""
    out = []
    for i, raw in enumerate(lines, 1):
        plain = ANSI.sub("", raw)
        for m in IMG.finditer(plain):
            p = os.path.expanduser((m.group(1) or m.group(2)).strip())
            c0 = vw(plain[: m.start()]) + 1
            c1 = c0 + vw(plain[m.start(): m.end()]) - 1
            if os.path.isfile(p):
                out.append((i, c0, c1, p, plain[m.start(): m.end()]))
    return out


def main():
    sock, wid = peer_window()
    if not wid:
        print("no window under the overlay"); time.sleep(1.5); return
    open("/tmp/link-peek.log", "a").write(f"start sock={sock} wid={wid}\n")
    lines = grab_screen(sock, wid)
    links = link_map(lines)

    if "--print" in sys.argv:
        for r, c0, c1, p, _t in links:
            print(f"row {r} cols {c0}-{c1}: {p}")
        print(f"({len(links)} image links)")
        return

    ts = shutil.get_terminal_size((200, 50))
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\033[?25l\033[2J\033[?1003h\033[?1006h")
    buf = []
    for i, line in enumerate(lines[: ts.lines], 1):
        buf.append(f"\033[{i};1H{line}\033[0m")
    for r, c0, c1, _p, txt in links:  # highlight the hoverable links
        buf.append(f"\033[{r};{c0}H{ULC}{txt}{RST}")
    hint = f" {CYAN}link peek{RST} {DIM}· hover an image link · click = rail · any key closes{RST}"
    buf.append(f"\033[{ts.lines};1H{hint}\033[K")
    sys.stdout.write("".join(buf))
    sys.stdout.flush()

    hover = None
    clicked = None
    t0 = time.monotonic()
    try:
        while True:
            r_, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not r_:
                continue
            data = os.read(fd, 64).decode("utf-8", "replace")
            if time.monotonic() - t0 < 0.4:
                continue  # swallow the launch chord's key-repeat spill
            while select.select([sys.stdin], [], [], 0.004)[0]:
                more = os.read(fd, 256)
                if not more:
                    break
                data += more.decode("utf-8", "replace")
            mouse = re.findall(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])", data)
            keys = re.sub(r"\x1b\[<\d+;\d+;\d+[Mm]", "", data)
            for mb, mx, my, kind in mouse:
                mb, mx, my = int(mb), int(mx), int(my)
                tgt = next((l for l in links if l[0] == my and l[1] <= mx <= l[2]), None)
                if kind == "M" and mb == 0 and tgt:
                    clicked = tgt[3]
                    break
                if (mb & 32) and tgt is not None and (hover is None or tgt[3] != hover[3]):
                    hover = tgt
                    subprocess.run([KITTEN, "icat", "--clear"], stdout=subprocess.DEVNULL)
                    pw, ph = 46, 22
                    px = mx + 3 if mx + 3 + pw < ts.columns else max(1, mx - pw - 3)
                    py = 2 if my > ts.lines // 2 else max(2, ts.lines - ph - 2)
                    subprocess.run([KITTEN, "icat", "--place", f"{pw}x{ph}@{px}x{py}",
                                    "--scale-up", "--z-index", "5", hover[3]],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    sys.stdout.write(f"\033[{ts.lines};1H {CYAN}{os.path.basename(hover[3])}{RST}"
                                     f" {DIM}· click sends to rail{RST}\033[K")
                    sys.stdout.flush()
                elif (mb & 32) and tgt is None and hover is not None:
                    hover = None
                    subprocess.run([KITTEN, "icat", "--clear"], stdout=subprocess.DEVNULL)
                    sys.stdout.write(f"\033[{ts.lines};1H{hint}\033[K")
                    sys.stdout.flush()
            if clicked or any(k in "\r\nq\x1b\x03" for k in keys):
                open("/tmp/link-peek.log", "a").write(
                    f"exit: clicked={clicked!r} keys={keys!r} raw={data!r}\n")
                break  # deliberate close keys only — held-chord repeats can't dismiss
    finally:
        subprocess.run([KITTEN, "icat", "--clear"], stdout=subprocess.DEVNULL)
        sys.stdout.write("\033[?1003l\033[?1006l\033[?25h\033[0m")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if clicked:
        env = dict(os.environ, NEKO_WID=str(wid))
        subprocess.Popen([os.path.expanduser("~/bin/img-rail-here"), clicked],
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        open("/tmp/link-peek.log", "a").write(traceback.format_exc() + "\n")
        time.sleep(3)

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
IMG = re.compile(
    r"file://(/[^\s)\"]+?\.(?:png|jpe?g|gif|webp))"      # file:// URL
    r"|\[\[img:([^\]\n]+?)\]\]"                          # [[img:...]]
    r"|((?:~|/)[\w@.+/-]+?\.(?:png|jpe?g|gif|webp))\b",   # bare abs/~ path
    re.I)


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



import base64
import struct
import tempfile

_sent = {}  # path -> (img_id, px_w, px_h) — transmit once, re-place per motion


def _gfx(keys, data=b""):
    payload = base64.standard_b64encode(data).decode() if data else ""
    out = []
    first = True
    while True:
        chunk, payload = payload[:4000], payload[4000:]
        k = dict(keys) if first else {}
        if data:
            k["m"] = 1 if payload else 0
        ser = ",".join(f"{a}={v}" for a, v in k.items())
        out.append(f"\033_G{ser};{chunk}\033\\")
        first = False
        if not payload:
            break
    return "".join(out)


def _ensure_sent(path):
    if path in _sent:
        return _sent[path]
    p = path
    if not p.lower().endswith(".png"):  # graphics f=100 wants PNG
        tmp = os.path.join(tempfile.gettempdir(), f"lp-{abs(hash(p))}.png")
        if not os.path.exists(tmp):
            subprocess.run(["/usr/bin/sips", "-s", "format", "png", p, "--out", tmp],
                           capture_output=True)
        p = tmp
    try:
        data = open(p, "rb").read()
        w, h = struct.unpack(">II", data[16:24])
    except Exception:
        _sent[path] = None
        return None
    iid = 4600 + len(_sent)
    sys.stdout.write(_gfx({"a": "t", "f": 100, "i": iid, "q": 2}, data))
    _sent[path] = (iid, w, h)
    return _sent[path]


def _float_at(path, mx, my, ts):
    got = _ensure_sent(path)
    if not got:
        return None
    iid, iw, ih = got
    pw = 42
    ph = max(5, min(22, round(pw * (ih / max(1, iw)) * 0.5)))
    px = mx + 2 if mx + 2 + pw <= ts.columns else max(1, mx - pw - 2)
    py = my - ph - 1 if my - ph - 1 >= 1 else my + 2
    py = max(1, min(py, ts.lines - ph))
    sys.stdout.write(_gfx({"a": "d", "d": "i", "i": iid, "q": 2})
                     + f"\033[{py};{px}H"
                     + _gfx({"a": "p", "i": iid, "c": pw, "r": ph, "z": 5, "q": 2}))
    sys.stdout.flush()
    return iid


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
            p = os.path.expanduser(next(g for g in m.groups() if g).strip())
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
    # spotlight mode: the mirror renders DIMMED (color stripped, faint gray)
    # so entering peek is unmistakable; image links glow cyan.
    FAINTG = "\033[38;2;80;88;115m"
    buf = []
    for i, line in enumerate(lines[: ts.lines], 1):
        buf.append(f"\033[{i};1H{FAINTG}{ANSI.sub('', line)}\033[0m")
    for r, c0, c1, _p, txt in links:  # highlight the hoverable links
        buf.append(f"\033[{r};{c0}H{ULC}{txt}{RST}")
    hint = (f" {CYAN}◉ LINK PEEK{RST}  {DIM}hover a glowing link to preview · "
            f"click = send to rail · esc closes{RST}")
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
                if (mb & 32) and tgt is not None:
                    shown = _float_at(tgt[3], mx, my, ts)  # glued to the pointer
                    if hover is None or hover[3] != tgt[3]:
                        hover = tgt
                        sys.stdout.write(f"\033[{ts.lines};1H {CYAN}{os.path.basename(tgt[3])}{RST}"
                                         f" {DIM}\u00b7 click sends to rail{RST}\033[K")
                        sys.stdout.flush()
                elif (mb & 32) and tgt is None and hover is not None:
                    got = _sent.get(hover[3])
                    if got:
                        sys.stdout.write(_gfx({"a": "d", "d": "i", "i": got[0], "q": 2}))
                    hover = None
                    sys.stdout.write(f"\033[{ts.lines};1H{hint}\033[K")
                    sys.stdout.flush()
            if clicked or any(k in "\r\nq\x1b\x03" for k in keys):
                open("/tmp/link-peek.log", "a").write(
                    f"exit: clicked={clicked!r} keys={keys!r} raw={data!r}\n")
                break  # deliberate close keys only — held-chord repeats can't dismiss
    finally:
        sys.stdout.write(_gfx({"a": "d", "d": "A", "q": 2}))
        sys.stdout.write("\033[?1003l\033[?1006l\033[?25h\033[0m")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if clicked:
        env = dict(os.environ, NEKO_WID=str(wid))
        subprocess.run([os.path.expanduser("~/bin/img-rail-here"), clicked],
                       env=env, start_new_session=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        open("/tmp/link-peek.log", "a").write(traceback.format_exc() + "\n")
        time.sleep(3)

#!/usr/bin/env python3
"""Nekotron fleet board v5 — live full-canvas kitty overlay (cmd+shift+f).

Block clock, session cards with live activity feeds, fleet timeline,
vitals — refreshing while open — and an animated cat living in a yard on
the right side. 10 fps cat, 2 s data, 6 s vitals; between data refreshes
only the cat's rows repaint. Digits jump; any other key dismisses.
  --print      one static frame (testing)
  --frames N   run N frames without a tty (testing)
"""
import base64
import datetime
import glob
import json
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import time
import zlib

KITTEN = shutil.which("kitten") or "/Applications/kitty.app/Contents/MacOS/kitten"
TMUX = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
MEMP = shutil.which("memory_pressure") or "/usr/sbin/memory_pressure"
STATE_DIR = "/tmp/claude-kitty-status"
PROJECTS = os.path.expanduser("~/.claude/projects")
SESSIONS = os.path.expanduser("~/.claude/sessions")

CYAN = "\033[38;2;95;233;223m"
DKCYAN = "\033[38;2;40;92;98m"
MAG = "\033[38;2;255;95;168m"
AMBER = "\033[38;2;255;182;92m"
DIM = "\033[38;2;107;115;148m"
FAINT = "\033[38;2;58;65;96m"
INK = "\033[38;2;232;236;255m"
BOLD, RST = "\033[1m", "\033[0m"
ST = {
    "working":   ("\033[38;2;79;142;247m", "⠿", "working"),
    "done":      ("\033[38;2;76;195;138m", "●", "done"),
    "attention": ("\033[38;2;240;128;60m", "●", "NEEDS YOU"),
    "neutral":   ("\033[38;2;90;90;100m", "●", "idle"),
}
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
REPO_HUE = {"glow-platform": CYAN, "glow-core": MAG, "glow-aws-sync": AMBER}
ANSI = re.compile(r"\033\[[0-9;:]*m")

DIGITS = {
    "0": ["██████", "██  ██", "██  ██", "██  ██", "██████"],
    "1": ["    ██", "    ██", "    ██", "    ██", "    ██"],
    "2": ["██████", "    ██", "██████", "██    ", "██████"],
    "3": ["██████", "    ██", "██████", "    ██", "██████"],
    "4": ["██  ██", "██  ██", "██████", "    ██", "    ██"],
    "5": ["██████", "██    ", "██████", "    ██", "██████"],
    "6": ["██████", "██    ", "██████", "██  ██", "██████"],
    "7": ["██████", "    ██", "    ██", "    ██", "    ██"],
    "8": ["██████", "██  ██", "██████", "██  ██", "██████"],
    "9": ["██████", "██  ██", "██████", "    ██", "██████"],
    ":": ["  ", "██", "  ", "██", "  "],
}

EYES_OPEN, EYES_BLINK, EYES_SLEEP, EYES_WIDE = "( ̳• · • ̳)", "( ̳- · - ̳)", "( ̳- ᴥ - ̳)", "( ⊙ · ⊙ )"
GAITS = ["  ﾉ   ﾉ ", "  ﾉ  ʃ  ", "  ʃ   ʃ ", "  ʃ  ﾉ  "]
TAILS = ["ﾉ~", "ﾉ,", "ﾉ~", "ﾉ`"]


# ── pixel-art sprite mode (toggle with `s` inside the board) ──────────
CAT_MODE_FILE = os.path.expanduser("~/.config/kitty/.fleet-cat-mode")
DENSITY_FILE = "/tmp/claude-kitty-status/board-density"
MIN_FILE = os.path.expanduser("~/.config/kitty/.fleet-minimized")


def _min_key(c):
    return c.get("sid") or c.get("title") or ""


def _load_min():
    try:
        return set(open(MIN_FILE).read().split("\n")) - {""}
    except OSError:
        return set()


def _save_min(s):
    try:
        open(MIN_FILE, "w").write("\n".join(sorted(s)))
    except OSError:
        pass
_NK = os.path.expanduser("~/Documents/GlowDevelopment/nekotron")
PALETTE = [
    ("jump to the session that needs you", "run_quit", _NK + "/kitty/jump-attention.sh"),
    ("broadcast to every Claude", "overlay", _NK + "/kitty/fleet-say.py"),
    ("peek a tab", "overlay", _NK + "/kitty/fleet-peek.py"),
    ("keybind cheatsheet", "overlay", _NK + "/kitty/keys-help.py"),
    ("snapshot workspace now", "run", _NK + "/bin/kitty-claude-snapshot.sh"),
    ("board-shot \u2192 Desktop PNG", "run", _NK + "/bin/board-shot"),
    ("theme day/night shift", "run", _NK + "/kitty/nekotron-theme.sh"),
    ("toggle compact density", "density", ""),
    ("minimize every quiet session", "minsweep", ""),
    ("toggle pixel/ascii cat", "sprite", ""),
    ("pet the cat", "pet", ""),
]
PAL = {"D": (74, 50, 22, 255), "O": (255, 182, 92, 255), "S": (199, 126, 46, 255),
       "W": (240, 236, 255, 255), "P": (255, 95, 168, 255), "B": (24, 26, 40, 255)}
SPRITE_MAPS = {
    "walk1": [
        "..DDD.....DDD.........",
        ".D.OOD...DOO.D........",
        ".DOOOODDDOOOOD........",
        "DOOOOOOOOOOOOOD.......",
        "DOOOOOOOOOOOOOOD......",
        "DOBBBOOOOBBBOOOD......",
        "DOBWBOOOOBWBOOOO..DD..",
        "DOBBBOOOOBBBOOOO.DOD..",
        "DOOOOOPOOOOOOOOODOD...",
        "DOOOODODOOOSOOSO......",
        ".DOOOOOOOOOOOOOOD.....",
        ".DOOD...DOOD...DOOD...",
        "..DD.....DD.....DD....",
        "......................",
    ],
    "walk2": [
        "..DDD.....DDD.........",
        ".D.OOD...DOO.D........",
        ".DOOOODDDOOOOD........",
        "DOOOOOOOOOOOOOD.......",
        "DOOOOOOOOOOOOOOD......",
        "DOBBBOOOOBBBOOOD......",
        "DOBWBOOOOBWBOOOO..DD..",
        "DOBBBOOOOBBBOOOO.DOD..",
        "DOOOOOPOOOOOOOOODOD...",
        "DOOOODODOOOSOOSO......",
        ".DOOOOOOOOOOOOOOD.....",
        "..DOOD...DOOD...DOOD..",
        "...DD.....DD.....DD...",
        "......................",
    ],
    "sit1": [
        "..DDD.....DDD.........",
        ".D.OOD...DOO.D........",
        ".DOOOODDDOOOOD........",
        "DOOOOOOOOOOOOOD.......",
        "DOOOOOOOOOOOOOOD......",
        "DOBBBOOOOBBBOOOD..DD..",
        "DOBWBOOOOBWBOOOOD.DOD.",
        "DOBBBOOOOBBBOOOOD.DOD.",
        "DOOOOOPOOOOOOOOOD.DOD.",
        "DOOOODODOOOSOOSOODDOD.",
        ".DOOOOOOOOOOOOOODDOD..",
        "..DOODDDDDDDDOOODDD...",
        "...DDDDDDDDDD.DD......",
    ],
    "sit2": [
        "..DDD.....DDD.........",
        ".D.OOD...DOO.D........",
        ".DOOOODDDOOOOD........",
        "DOOOOOOOOOOOOOD.......",
        "DOOOOOOOOOOOOOOD......",
        "DOBBBOOOOBBBOOOD..DD..",
        "DOBWBOOOOBWBOOOOD.DOD.",
        "DOBBBOOOOBBBOOOOD.DOD.",
        "DOOOOOPOOOOOOOOOD.DOD.",
        "DOOOODODOOOSOOSOODDOD.",
        ".DOOOOOOOOOOOOOODDOD..",
        "..DOODDDDDDDDOOODDD...",
        "...DDDDDDDDDD.DD......",
    ],
    "sleep1": [
        "..DDD.....DDD.........",
        ".D.OOD...DOO.D........",
        ".DOOOODDDOOOOD........",
        "DOOOOOOOOOOOOOD.......",
        "DOOOOOOOOOOOOOOD......",
        "DOOOOOOOOOOOOOOD......",
        "DODDDOOOODDDOOOO..DD..",
        "DOOOOOOOOOOOOOOO.DOD..",
        "DOOOOOPOOOOOOOOODOD...",
        "DOOOODODOOOSOOSO......",
        ".DDDDDDDDDDDDDDDD.....",
        "......................",
        "......................",
    ],
    "sleep2": [
        "..DDD.....DDD.........",
        ".D.OOD...DOO.D........",
        ".DOOOODDDOOOOD........",
        "DOOOOOOOOOOOOOD.......",
        "DOOOOOOOOOOOOOOD......",
        "DOOOOOOOOOOOOOOD......",
        "DODD.OOOODD.OOOO..DD..",
        "DOOOOOOOOOOOOOOO.DOD..",
        "DOOOOOPOOOOOOOOODOD...",
        "DOOOODODOOOSOOSO......",
        ".DDDDDDDDDDDDDDDD.....",
        "......................",
        "......................",
    ],
    "alert1": [
        "..DDD.....DDD....P....",
        ".DPOOD...DOOPD...P....",
        ".DOOOODDDOOOOD........",
        "DOOOOOOOOOOOOOD..P....",
        "DOOOOOOOOOOOOOOD......",
        "DOBBBOOOOBBBOOOD..DD..",
        "DOBWBOOOOBWBOOOOD.DOD.",
        "DOBBBOOOOBBBOOOOD.DOD.",
        "DOOOOOPOOOOOOOOOD.DOD.",
        "DOOOODODOOOSOOSOODDOD.",
        ".DOOOOOOOOOOOOOODDOD..",
        "..DOODDDDDDDDOOODDD...",
        "...DDDDDDDDDD.DD......",
    ],
    "alert2": [
        "..DDD.....DDD.........",
        ".D.OOD...DOO.D........",
        ".DOOOODDDOOOOD........",
        "DOOOOOOOOOOOOOD.......",
        "DOOOOOOOOOOOOOOD......",
        "DOBBBOOOOBBBOOOD..DD..",
        "DOBWBOOOOBWBOOOOD.DOD.",
        "DOBBBOOOOBBBOOOOD.DOD.",
        "DOOOOOPOOOOOOOOOD.DOD.",
        "DOOOODODOOOSOOSOODDOD.",
        ".DOOOOOOOOOOOOOODDOD..",
        "..DOODDDDDDDDOOODDD...",
        "...DDDDDDDDDD.DD......",
    ],
}
# mirrored walk frames: chosen by direction so he never moonwalks
SPRITE_MAPS.update({n + "R": [r[::-1] for r in rows]
                    for n, rows in list(SPRITE_MAPS.items()) if n.startswith("walk")})
SPRITE_ID = {name: 4200 + i for i, name in enumerate(sorted(SPRITE_MAPS))}
_transmitted = set()
_prev_sprite = None
_frames = None  # canonical name -> PNG bytes, built lazily
_pet_until = -1  # frame until which the cat is being petted



# ── card-UI design tokens ──────────────────────────────────────────────
PANEL = 0x131A30       # raised card background
PANEL_HI = 0x1B2542    # focused card background
PILL_BG = {"working": 0x1E3A5F, "done": 0x14532D, "attention": 0x7C2D12, "neutral": 0x262631}
RGB = {"good": (76, 195, 138), "warn": (255, 182, 92), "bad": (240, 128, 60),
       "track": (36, 42, 64), "ink": (232, 236, 255)}
_ring_cache = {}


def _bg(c):
    return f"\033[48;2;{(c >> 16) & 255};{(c >> 8) & 255};{c & 255}m"


def _fg(c):
    return f"\033[38;2;{(c >> 16) & 255};{(c >> 8) & 255};{c & 255}m"


def vtrunc(s, limit):
    """Truncate to `limit` visible chars, preserving ANSI, closing with reset."""
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


def panel_row(content, width, bg=PANEL, caps=True):
    """One row of a card: plain text — the panel itself is a z=-1 underlay."""
    return " " + pad(vtrunc(content, width - 2), width - 2) + " "


def pill(text, bg, fg=0xE8ECFF, panel=None):
    """Rounded chip; caps on default bg so underlays show through around it."""
    return (_fg(bg) + "\ue0b6" + RST + _bg(bg) + _fg(fg)
            + text + RST + _fg(bg) + "\ue0b4" + RST)


def _ring_png_cached(pct, color):
    key = (int(pct), color)
    if key in _ring_cache:
        return _ring_cache[key]
    import math
    size, ss = 66, 3
    S = size * ss
    cx = cy = (S - 1) / 2
    r_out, r_in = S * 0.47, S * 0.31
    cr = RGB[color]
    tr = RGB["track"]
    sweep = max(0.001, pct / 100.0) * 2 * math.pi
    buf = bytearray(S * S * 4)
    for y in range(S):
        dy = y - cy
        for x in range(S):
            dx = x - cx
            d = math.hypot(dx, dy)
            if r_in <= d <= r_out:
                a = math.atan2(dx, -dy) % (2 * math.pi)
                c = cr if a <= sweep else tr
                i = (y * S + x) * 4
                buf[i:i + 4] = bytes((*c, 255))
    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            rs = gs = bs = As = 0
            for sy in range(ss):
                row = ((y * ss + sy) * S + x * ss) * 4
                for sx in range(ss):
                    i = row + sx * 4
                    rs += buf[i]; gs += buf[i + 1]; bs += buf[i + 2]; As += buf[i + 3]
            n = ss * ss
            j = (y * size + x) * 4
            out[j:j + 4] = bytes((rs // n, gs // n, bs // n, As // n))
    png = _png_rgba(bytes(out), size, size)
    _ring_cache[key] = png
    return png


def grad_bar(pct, cells=6):
    """Tiny gradient bar: hue lerps green->amber->orange across the cells."""
    stops = [(76, 195, 138), (255, 182, 92), (240, 128, 60)]
    out = []
    for k in range(cells):
        t = k / max(1, cells - 1)
        seg = t * (len(stops) - 1)
        i0 = min(int(seg), len(stops) - 2)
        f = seg - i0
        c = tuple(int(stops[i0][j] + (stops[i0 + 1][j] - stops[i0][j]) * f) for j in range(3))
        filled = (k + 1) / cells <= pct / 100 + 0.08
        col = f"\033[38;2;{c[0]};{c[1]};{c[2]}m" if filled else _fg(0x2A3050)
        out.append(col + ("▰" if filled else "▱") + RST)
    return "".join(out)


_gauge_placed = set()  # ring image ids currently on screen


def gauge_escapes(row, col, gauges):
    """Place antialiased ring PNGs at (row, col): [(pct, color, label), ...]."""
    out = []
    for i, (pct, color, _label) in enumerate(gauges):
        gid = 4300 + i
        _gauge_placed.add(gid)
        out.append(_gfx({"a": "d", "d": "i", "i": gid, "q": 2}))
        out.append(_gfx({"a": "t", "f": 100, "i": gid, "q": 2}, _ring_png_cached(pct, color)))
        out.append(f"\033[{row};{col + i * 9}H")
        out.append(_gfx({"a": "p", "i": gid, "c": 6, "r": 3, "q": 2}))
    return "".join(out)



# ── underlay engine: images composited UNDER the text (z=-1) ───────────
CELL_W, CELL_H = 10, 20   # assumed cell pixel size; radius distortion is minor
VOID = (10, 13, 24)
_ul_ids = {}              # (kind, cols, rows) -> image id
_ul_pngs = {}             # id -> png bytes
_ul_sent = set()


def _panel_underlay(w, h, hi=False):
    """Rounded panel: vertical sheen, soft bottom shadow, alpha-faded edges."""
    import math
    top = (27, 37, 66) if hi else (23, 31, 56)
    bot = (19, 26, 48) if hi else (16, 22, 42)
    rad = 14
    pad = 4               # slim inset; shadow hugs the rect
    buf = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            dx = max(rad + pad - x, 0, x - (w - 1 - rad - pad))
            dy = max(rad + pad - y, 0, y - (h - 1 - rad - pad))
            m = rad + 1.0 - math.hypot(dx, dy) + pad
            i = (y * w + x) * 4
            if m >= pad:  # inside the rounded rect
                t = y / h
                a = 255 if m >= pad + 1.5 else int(255 * (m - pad) / 1.5)
                buf[i] = int(top[0] + (bot[0] - top[0]) * t)
                buf[i + 1] = int(top[1] + (bot[1] - top[1]) * t)
                buf[i + 2] = int(top[2] + (bot[2] - top[2]) * t)
                buf[i + 3] = a
            elif m > 0:   # shadow halo, strongest below
                fall = m / pad
                bias = 1.3 if y > h // 2 else 0.6
                a = int(60 * fall * fall * bias)
                if a > 2:
                    buf[i:i + 4] = bytes((3, 4, 9, a))
    return _png_rgba(bytes(buf), w, h)


def _aurora_underlay(w, h):
    """Ambient glow blobs that alpha-fade to nothing — blends with any bg."""
    import math
    buf = bytearray(w * h * 4)
    blobs = [(int(w * 0.16), int(h * 0.55), h * 1.9, (95, 233, 223), 34),
             (int(w * 0.46), int(h * 0.25), h * 1.5, (79, 142, 247), 22),
             (int(w * 0.82), int(h * 0.75), h * 1.6, (255, 95, 168), 14)]
    for y in range(h):
        for x in range(w):
            r = g = b = a = 0.0
            for bx, by, rad, c, amp in blobs:
                d = math.hypot((x - bx) * 0.55, y - by)  # squash horizontally
                if d < rad:
                    t = (1 - d / rad) ** 2 * amp
                    r += c[0] * t / 255
                    g += c[1] * t / 255
                    b += c[2] * t / 255
                    a += t
            if a > 1.5:
                a = min(64, a)
                i = (y * w + x) * 4
                buf[i:i + 4] = bytes((int(min(255, r * 4)), int(min(255, g * 4)),
                                      int(min(255, b * 4)), int(a)))
    return _png_rgba(bytes(buf), w, h)


def _identicon_png(seed, scale=8):
    """Symmetric 5x5 identicon: a face for every session."""
    import hashlib
    h = hashlib.md5(seed.split("|")[0].encode()).digest()
    hue = {"glow-platform": (95, 233, 223), "glow-core": (255, 95, 168),
           "glow-aws-sync": (255, 182, 92)}.get(seed.split("|")[-1], (139, 139, 150))
    size = 5 * scale
    buf = bytearray(size * size * 4)
    for gy in range(5):
        for gx in range(3):
            if h[gy * 3 + gx] % 2:
                for mx in {gx, 4 - gx}:
                    for dy in range(scale):
                        for dx in range(scale):
                            i = ((gy * scale + dy) * size + mx * scale + dx) * 4
                            buf[i:i + 4] = bytes((*hue, 230))
    return _png_rgba(bytes(buf), size, size)


_chart_series = {}


def _chart_png(series, w, h):
    """Filled area chart: cumulative spend today, cyan fading downward."""
    buf = bytearray(w * h * 4)
    peak = max(series) if series and max(series) > 0 else 1.0
    n = len(series) or 1
    for x in range(w):
        f = x / max(1, w - 1) * (n - 1)
        i0 = int(f)
        val = series[i0] + (series[min(n - 1, i0 + 1)] - series[i0]) * (f - i0)
        level = int((1 - val / peak * 0.9) * (h - 3)) + 1
        for y in range(level, h):
            t = (y - level) / max(1, h - level)
            a = int(150 * (1 - t * 0.8))
            i = (y * w + x) * 4
            buf[i:i + 4] = bytes((95, 233, 223, a))
        for y in (level - 1, level):  # crisp top line
            if 0 <= y < h:
                i = (y * w + x) * 4
                buf[i:i + 4] = bytes((95, 233, 223, 255))
    return _png_rgba(bytes(buf), w, h)


def _diorama_png(phase_bucket, h_px, w_px=440, chip_cells=0):
    """The cat's yard as a proper rounded panel with the (muted) time-of-day
    scene inside — same corner mask + shadow language as every other card."""
    import math
    ac = _animated_cat()
    if not ac:
        return _png_rgba(bytes(4), 1, 1)
    pal = ac.palette_at(phase_bucket / 144.0)
    total = max(20, h_px)
    horizon = int(total * 0.72)
    strip = bytearray(ac.draw_bg_color_strip(total, int(total * 0.44),
                                             int(total * 0.62), horizon, pal))
    k = 0.42
    for y in range(total):
        i = y * 4
        strip[i] = int(VOID[0] + (strip[i] - VOID[0]) * k)
        strip[i + 1] = int(VOID[1] + (strip[i + 1] - VOID[1]) * k)
        strip[i + 2] = int(VOID[2] + (strip[i + 2] - VOID[2]) * k)
    rad, pad_ = 14, 4
    buf = bytearray(w_px * h_px * 4)
    for y in range(h_px):
        srow = strip[min(total - 1, y * total // h_px) * 4:][:4]
        for x in range(w_px):
            dx = max(rad + pad_ - x, 0, x - (w_px - 1 - rad - pad_))
            dy = max(rad + pad_ - y, 0, y - (h_px - 1 - rad - pad_))
            m = rad + 1.0 - math.hypot(dx, dy) + pad_
            i = (y * w_px + x) * 4
            if m >= pad_:
                a = 255 if m >= pad_ + 1.5 else int(255 * (m - pad_) / 1.5)
                r, g, b = srow[0], srow[1], srow[2]
                scrim_top = h_px * 0.60
                if y > scrim_top:  # caption scrim: text sits on this, not on raw scene
                    s = min(1.0, (y - scrim_top) / (h_px * 0.28)) ** 1.4 * 0.72
                    r = int(r + (6 - r) * s)
                    g = int(g + (8 - g) * s)
                    b = int(b + (15 - b) * s)
                buf[i:i + 3] = bytes((r, g, b))
                buf[i + 3] = a
            elif m > 0:
                fall = m / pad_
                a = int(50 * fall * fall)
                if a > 2:
                    buf[i:i + 4] = bytes((3, 4, 9, a))
    if chip_cells:  # caption plate: rounded slate chip baked at the mood row
        cy0 = h_px - 2 * CELL_H + 2
        cy1 = h_px - CELL_H - 2
        cx0 = 3 * CELL_W - 6
        cx1 = cx0 + chip_cells * CELL_W + 12
        crad = (cy1 - cy0) / 2
        for y in range(max(0, cy0 - 2), min(h_px, cy1 + 3)):
            for x in range(max(0, cx0 - 2), min(w_px, cx1 + 3)):
                dx = max(cx0 + crad - x, 0, x - (cx1 - crad))
                dy = max(cy0 + crad - y, 0, y - (cy1 - crad))
                m = crad + 1.0 - math.hypot(dx, dy)
                if m > 0:
                    a2 = 255 if m >= 1.5 else int(255 * m / 1.5)
                    i = (y * w_px + x) * 4
                    er = buf[i:i + 4]
                    s = a2 / 255
                    buf[i] = int(er[0] * (1 - s) + 28 * s)
                    buf[i + 1] = int(er[1] * (1 - s) + 36 * s)
                    buf[i + 2] = int(er[2] * (1 - s) + 64 * s)
                    buf[i + 3] = max(er[3], a2)
    return _png_rgba(bytes(buf), w_px, h_px)


def underlay_escapes(placements):
    """placements: [(row, col, cols, rows, kind)] -> transmit/place at z=-1."""
    out = []
    for gid in _ul_ids.values():
        out.append(_gfx({"a": "d", "d": "i", "i": gid, "q": 2}))
    for row, col, cw, rh, kind in placements:
        key = (kind, cw, rh)
        if key not in _ul_ids:
            _ul_ids[key] = 4400 + len(_ul_ids)
            w_px, h_px = cw * CELL_W, rh * CELL_H
            if kind == "aurora":
                _ul_pngs[_ul_ids[key]] = _aurora_underlay(w_px, h_px)
            elif kind.startswith("icon:"):
                _ul_pngs[_ul_ids[key]] = _identicon_png(kind[5:])
            elif kind.startswith("ring:"):
                pct, color = kind[5:].split(",")
                _ul_pngs[_ul_ids[key]] = _ring_png_cached(int(pct), color)
            elif kind.startswith("chart:"):
                _ul_pngs[_ul_ids[key]] = _chart_png(_chart_series.get(kind[6:], []), w_px, h_px)
            elif kind.startswith("dio:"):
                pb, chip_cells = kind[4:].split(":")
                _ul_pngs[_ul_ids[key]] = _diorama_png(int(pb), h_px, w_px, int(chip_cells))
            else:
                _ul_pngs[_ul_ids[key]] = _panel_underlay(w_px, h_px, hi=(kind == "card_hi"))
        gid = _ul_ids[key]
        if gid not in _ul_sent:
            out.append(_gfx({"a": "t", "f": 100, "i": gid, "q": 2}, _ul_pngs[gid]))
            _ul_sent.add(gid)
        out.append(f"\033[{row};{col}H")
        zed = -1 if kind.startswith(("ring:", "icon:")) else -2
        out.append(_gfx({"a": "p", "i": gid, "c": cw, "r": rh, "z": zed,
                         "p": len(out), "q": 2}))
    return "".join(out)


def _animated_cat():
    """Load ~/animated-cat.py (the reference tabby) if present."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "animated_cat", os.path.expanduser("~/animated-cat.py"))
        m = importlib.util.module_from_spec(spec)
        sys.modules["animated_cat"] = m
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None


def _png_rgba(raw, w, h):
    rows = b"".join(b"\x00" + raw[y * w * 4:(y + 1) * w * 4] for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _flip_rgba(raw, w, h):
    out = bytearray(len(raw))
    for y in range(h):
        base = y * w * 4
        for x in range(w):
            out[base + x * 4: base + x * 4 + 4] = \
                raw[base + (w - 1 - x) * 4: base + (w - 1 - x) * 4 + 4]
    return bytes(out)


def sprite_frames():
    """Canonical frames walk0-3 / sit0-1 / sleep0 / alert0-1, facing RIGHT,
    plus 'L' mirrors. Prefers the reference tabby from ~/animated-cat.py;
    falls back to the built-in pixel maps."""
    global _frames
    if _frames is not None:
        return _frames
    reg = {}
    ac = _animated_cat()
    if ac:
        try:
            poses = {"walk0": ac.draw_cat(0), "walk1": ac.draw_cat(1),
                     "walk2": ac.draw_cat(2), "walk3": ac.draw_cat(3),
                     "sit0": ac.draw_cat_sit(), "sit1": ac.draw_cat_sit(blink=True),
                     "sleep0": ac.draw_cat_sleep(),
                     "alert0": ac.draw_cat_crouch(), "alert1": ac.draw_cat_lookup()}
            w, h = ac.BASE_W, ac.BASE_H
            for n, raw in poses.items():
                reg[n] = _png_rgba(ac.upscale(raw, w, h, 3), w * 3, h * 3)
                reg[n + "L"] = _png_rgba(
                    ac.upscale(_flip_rgba(raw, w, h), w, h, 3), w * 3, h * 3)
        except Exception:
            reg = {}
    if not reg:  # fallback: built-in chibi maps (they face LEFT, so R = base)
        alias = {"walk0": "walk1R", "walk1": "walk2R", "walk2": "walk1R", "walk3": "walk2R",
                 "walk0L": "walk1", "walk1L": "walk2", "walk2L": "walk1", "walk3L": "walk2",
                 "sit0": "sit1", "sit1": "sit2", "sleep0": "sleep1",
                 "alert0": "alert1", "alert1": "alert2"}
        for n, src in alias.items():
            if src in SPRITE_MAPS:
                reg[n] = _png(SPRITE_MAPS[src])
        for n in ("sit0", "sit1", "sleep0", "alert0", "alert1"):
            if n in reg:
                reg[n + "L"] = reg[n]
    _frames = reg
    return reg


def _png(pixmap, scale=6):
    h, w = len(pixmap), max(len(r) for r in pixmap)
    rows = []
    for y in range(h * scale):
        src = pixmap[y // scale].ljust(w, ".")
        row = bytearray([0])
        for x in range(w * scale):
            row += bytes(PAL.get(src[x // scale], (0, 0, 0, 0)))
        rows.append(bytes(row))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    ihdr = struct.pack(">IIBBBBB", w * scale, h * scale, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def _gfx(keys, data=b""):
    b = base64.standard_b64encode(data).decode() if data else ""
    chunks = [b[i:i + 4000] for i in range(0, len(b), 4000)] or [""]
    out = []
    for idx, ch in enumerate(chunks):
        k = dict(keys) if idx == 0 else {}
        k["m"] = 1 if idx < len(chunks) - 1 else 0
        ks = ",".join(f"{a}={v}" for a, v in k.items())
        out.append(f"\033_G{ks};{ch}\033\\")
    return "".join(out)


def cat_mode():
    try:
        return open(CAT_MODE_FILE).read().strip() or "ascii"
    except OSError:
        return "ascii"


def sprite_patch(cards, geo, frame):
    """Position the pixel cat in the yard via kitty graphics protocol."""
    global _prev_sprite
    top, col, width, height = geo
    if height < 8:
        return ""
    mode, mood, mc = fleet_mode(cards)
    reg = sprite_frames()
    t = frame
    x = max(2, (width - 20) // 2)
    if mode == "walk":
        phase = t % 140
        if phase >= 100:
            name = "sit1" if t % 30 < 3 else "sit0"
        else:
            name = f"walk{(t // 2) % 4}"
            span = max(4, width - 22)
            p = (t // 2) % (2 * span)
            x = p if p < span else 2 * span - p
            if p >= span:  # heading left: mirrored frames
                name += "L"
    elif mode == "sit":
        name = "sit1" if t % 30 < 3 else "sit0"
    elif mode == "sleep":
        name = "sleep0"
    else:
        name = f"alert{t // 5 % 2}"
    if frame < _pet_until:
        name, mood, mc = "sit1", "purring ♥", MAG
    if name not in reg:
        return ""
    out = []
    hrow = ""
    if frame < _pet_until:
        hrow = " " * (x + 5) + MAG + ["♥  ♥", " ♥ ♥", "  ♥  "][t // 2 % 3] + RST
    out.append(f"\033[{top + max(0, height - 10)};{col}H" + pad(hrow, width) + "\033[K")
    sid = 4200 + sorted(reg).index(name)
    if name not in _transmitted:
        out.append(_gfx({"a": "t", "f": 100, "i": sid, "q": 2}, reg[name]))
        _transmitted.add(name)
    out.append(f"\033[{top + max(1, height - 9)};{col + x}H")
    out.append(_gfx({"a": "p", "i": sid, "c": 18, "r": 6, "q": 2}))
    if _prev_sprite is not None and _prev_sprite != sid:
        out.append(_gfx({"a": "d", "d": "i", "i": _prev_sprite, "q": 2}))
    _prev_sprite = sid
    out.append(f"\033[{top + 7};{col}H" + pad("", width) + "\033[K")
    out.append(f"\033[{top + max(8, height - 2)};{col}H"
               + pad("    " + mc + mood + RST, width) + "\033[K")
    return "".join(out)


def cat_art(mode, t):
    """4 rows of cat — pure ASCII, no combining characters, no demons."""
    blink = t % 37 == 0
    if mode == "walk":
        eyes = "-.-" if blink else "o.o"
        feet = ["  w w  ", " w   w ", "  w w  ", " w w   "][t % 4]
        tail = "~" if t % 4 < 2 else ","
        return [" /\\_/\\", f"( {eyes} )", f" (   ){tail}", feet]
    if mode == "sit":
        eyes = "-.-" if blink else "^.^"
        tail = ["~", ",", "~", "`"][t // 3 % 4]
        return [" /\\_/\\", f"( {eyes} )", f" )   ({tail}", "  \" \""]
    if mode == "sleep":
        z = ["z", "zZ", "zZz"][t // 5 % 3]
        return [f" /\\_/\\   {z}", "( -.- )", " (   )", " ~~~~~"]
    bang = "!" if t % 4 < 2 else " "
    return [f" /\\_/\\  {bang}", "( O.O )", " (   )", "  ! !"]


def vlen(s):
    return len(ANSI.sub("", s))


def pad(s, w):
    return s + " " * max(0, w - vlen(s))


def fmt_age(sec):
    if sec is None:
        return ""
    sec = int(sec)
    return f"{sec}s" if sec < 60 else f"{sec//60}m" if sec < 3600 else f"{sec//3600}h"


def human(n):
    return f"{n/1048576:.1f} MB" if n < 1073741824 else f"{n/1073741824:.1f} GB"


def entry_event(e):
    msg = e.get("message") or {}
    content = msg.get("content")
    if e.get("type") == "user" and isinstance(content, str) and content.strip():
        if content.lstrip().startswith("<"):
            return None
        return MAG + "❯ " + RST + FAINT + content.strip().replace("\n", " ")
    if e.get("type") == "assistant" and isinstance(content, list):
        for part in content:
            if part.get("type") == "tool_use":
                inp = part.get("input") or {}
                hint = str(inp.get("command") or inp.get("file_path")
                           or inp.get("description") or inp.get("prompt") or "").replace("\n", " ")
                return FAINT + f"⚙ {part.get('name','tool')}" + (f" · {hint}" if hint else "")
            if part.get("type") == "text" and part.get("text", "").strip():
                return FAINT + "✳ " + part["text"].strip().replace("\n", " ")
    return None


def last_events(transcript, n):
    out = []
    try:
        size = os.path.getsize(transcript)
        with open(transcript, "rb") as f:
            f.seek(max(0, size - 131072))
            lines = f.read().decode("utf-8", "replace").splitlines()
        for line in reversed(lines[-400:]):
            if len(out) >= n:
                break
            try:
                e = json.loads(line)
            except Exception:
                continue
            txt = entry_event(e)
            if not txt:
                continue
            epoch = None
            ts = e.get("timestamp")
            if ts:
                try:
                    epoch = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass
            out.append((epoch, txt))
    except Exception:
        pass
    return list(reversed(out))


def _tmux_claude(client_pid):
    try:
        r = subprocess.run([TMUX, "list-clients", "-F", "#{client_pid} #{session_name}"],
                           capture_output=True, text=True, timeout=3)
        sess = next((l.split(None, 1)[1] for l in r.stdout.splitlines()
                     if l.split(None, 1)[0] == str(client_pid)), None)
        if not sess:
            return None
        r = subprocess.run([TMUX, "list-panes", "-t", sess, "-F", "#{pane_pid}"],
                           capture_output=True, text=True, timeout=3)
        for pane_pid in r.stdout.split():
            r2 = subprocess.run(["/usr/bin/pgrep", "-P", pane_pid],
                                capture_output=True, text=True, timeout=3)
            for child in r2.stdout.split():
                if os.path.exists(f"{SESSIONS}/{child}.json"):
                    return int(child)
    except Exception:
        pass
    return None


def claude_meta(pid):
    try:
        with open(f"{SESSIONS}/{pid}.json") as f:
            d = json.load(f)
        sid, cwd = d.get("sessionId"), d.get("cwd") or ""
        tp = f"{PROJECTS}/{re.sub(r'[/_.]', '-', cwd)}/{sid}.jsonl"
        return sid, cwd, (tp if os.path.exists(tp) else None)
    except Exception:
        return None, None, None


def kitty_ls(sock):
    """`kitten @ ls`, diagnosing the control-socket wedge instead of a JSON error."""
    out = subprocess.run([KITTEN, "@", "--to", f"unix:{sock}", "ls"],
                         capture_output=True, text=True, timeout=5).stdout
    if not out.strip():
        pid = sock.rsplit("-", 1)[-1]
        try:
            conns = subprocess.run(["/usr/sbin/lsof", "-p", pid], capture_output=True,
                                   text=True, timeout=10).stdout.count("kitty-ctl")
        except Exception:
            conns = "?"
        raise SystemExit(f"kitty control socket is WEDGED ({conns} leaked connections, "
                         f"pid {pid}) — restart kitty to recover; sessions restore via "
                         f"claude-restore.session")
    return json.loads(out)


def gather(sock, kpid, feed_n):
    ls = kitty_ls(sock)
    cards = []
    for osw in ls:
        for tab in osw.get("tabs", []):
            all_wins = tab.get("windows", [])
            wins = [w for w in all_wins if not w.get("is_self")]
            if not wins:
                # our own window is the tab's ONLY window (--print from a
                # shell, or the board in its own tab) — keep the tab visible
                wins = all_wins
                if not wins:
                    continue
            title = tab.get("title") or ""
            if wins is not all_wins and len(wins) < len(all_wins):
                title = wins[0].get("title") or title  # see through our overlay
            state, sfile, cpid, cwd, ctx, scost, note = "neutral", None, None, "", None, None, ""
            for w in wins:
                pn = f"{STATE_DIR}/note-{kpid}-{w.get('id')}"
                if not note and os.path.exists(pn):
                    try:
                        note = open(pn).read().strip()[:80]
                    except OSError:
                        pass
                pc = f"{STATE_DIR}/ctx-{kpid}-{w.get('id')}"
                if ctx is None and os.path.exists(pc):
                    try:
                        ctx = int(open(pc).read().strip() or 0)
                    except ValueError:
                        ctx = None
                pu = f"{STATE_DIR}/usage-{kpid}-{w.get('id')}"
                if scost is None and os.path.exists(pu):
                    try:
                        scost = float(open(pu).read().strip() or 0)
                    except ValueError:
                        scost = None
                p = f"{STATE_DIR}/{kpid}-{w.get('id')}"
                if os.path.exists(p):
                    s = open(p).read().strip()
                    if sfile is None or s == "attention":
                        state, sfile = (s if s in ST else "neutral"), p
                for fp in w.get("foreground_processes", []) or []:
                    base = os.path.basename((fp.get("cmdline") or [""])[0])
                    if base == "claude":
                        cpid = fp.get("pid")
                    elif base == "tmux" and cpid is None:
                        cpid = _tmux_claude(fp.get("pid"))
                    cwd = cwd or fp.get("cwd") or ""
            sid, ccwd, transcript = claude_meta(cpid) if cpid else (None, None, None)
            cwd = ccwd or cwd
            meta, events, tsize, agents = "", [], 0, 0
            if transcript:
                st_ = os.stat(transcript)
                tsize = st_.st_size
                born = time.strftime("%b %-d", time.localtime(getattr(st_, "st_birthtime", st_.st_mtime)))
                meta = f"{human(tsize)} · since {born}"
                idle_d = int((time.time() - st_.st_mtime) // 86400)
                if idle_d >= 1:
                    meta += f" · stale {idle_d}d — close?"
                events = last_events(transcript, feed_n)
                try:  # live agent teammates/subagents: recently-written sidecars
                    adir = transcript[:-6] + "/subagents"
                    now_ = time.time()
                    agents = sum(1 for f in os.scandir(adir)
                                 if f.name.endswith(".jsonl") and now_ - f.stat().st_mtime < 120)
                except OSError:
                    pass
                if agents:
                    meta += f" · ⚒ {agents} agent{'s' if agents != 1 else ''}"
                    if state == "neutral":
                        state = "working"  # orchestrating counts as working
            s_epoch = None
            if sfile:
                try:
                    s_epoch = os.path.getmtime(sfile)
                except OSError:
                    pass
            cards.append({"sid": sid, "wid": wins[0].get("id"), "title": title[:80], "state": state, "s_epoch": s_epoch, "size": tsize,
                          "repo": next((r for r in REPO_HUE if r in cwd), None),
                          "meta": (meta + f" · ${scost:.2f}" if scost is not None and meta
                                   else (f"${scost:.2f}" if scost is not None else meta)),
                          "events": events, "ctx": ctx, "note": note,
                          "focused": bool(tab.get("is_focused") and osw.get("is_focused"))})
    return cards


def vitals():
    v = {}
    try:
        out = subprocess.run([MEMP, "-Q"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"(\d+)%", out)
        v["mem"] = int(m.group(1)) if m else None
    except Exception:
        v["mem"] = None
    try:
        v["disk"] = shutil.disk_usage("/").free // 1073741824
        v["load"] = os.getloadavg()[0]
    except Exception:
        pass
    try:
        r = subprocess.run(["ps", "-axo", "rss=,comm="], capture_output=True, text=True, timeout=3)
        rss = cnt = 0
        for ln in r.stdout.splitlines():
            parts = ln.split(None, 1)
            if len(parts) == 2 and (parts[1].endswith("/claude") or parts[1] == "claude"
                                    or re.fullmatch(r"[\d.]+", parts[1])):
                rss += int(parts[0]); cnt += 1
        v["claudes"], v["crss"] = cnt, rss * 1024
    except Exception:
        v["claudes"] = v["crss"] = None
    try:
        socks = [s for s in glob.glob("/tmp/kitty-ctl-*")]
        if socks:
            kp = socks[0].rsplit("-", 1)[-1]
            r = subprocess.run(["ps", "-o", "rss=", "-p", kp], capture_output=True, text=True, timeout=3)
            krss = int(r.stdout.strip() or 0) * 1024
            r = subprocess.run(["/usr/sbin/lsof", socks[0]], capture_output=True, text=True, timeout=3)
            conns = max(0, len(r.stdout.splitlines()) - 1)
            v["kitty"] = (krss, conns)
    except Exception:
        pass
    try:
        r = subprocess.run([TMUX, "ls"], capture_output=True, text=True, timeout=3)
        tl = r.stdout.strip().splitlines() if r.returncode == 0 else []
        v["tmux"] = (sum(1 for l in tl if "attached" in l), len(tl))
    except Exception:
        v["tmux"] = None
    try:
        with open(f"{STATE_DIR}/usage-limits") as f:
            v["limits"] = json.load(f)
    except Exception:
        v["limits"] = None
    try:  # today's spend curve from the statusline cost ledger
        today = datetime.date.today().isoformat()
        first, latest = {}, {}
        bins = [0.0] * 48
        for line in open(os.path.expanduser("~/.claude/cost-ledger.tsv")):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4 or not parts[0].startswith(today):
                continue
            hh, mm = parts[0][11:13], parts[0][14:16]
            b = min(47, int(hh) * 2 + int(mm) // 30)
            sid, cost = parts[1], float(parts[2])
            if sid not in first:
                first[sid] = cost
            delta = max(0.0, cost - first[sid])
            latest[sid] = (b, delta)
            spent = sum(d for _, d in latest.values())
            bins[b] = max(bins[b], spent)
        peak = 0.0
        for i in range(48):
            peak = max(peak, bins[i])
            bins[i] = peak
        v["spend"] = bins
        v["spend_total"] = peak
    except Exception:
        v["spend"] = None
    return v


def ops_column(cards, v, width, tall, frame):
    """Right column as raised panels. Returns (lines, gauges, gauge_rel_idx)."""
    now = time.time()
    n = {s: sum(1 for c in cards if c["state"] == s) for s in ST}
    sp = SPIN[frame % len(SPIN)]
    L = []
    P = lambda content, bg=PANEL: panel_row(content, width, bg)

    L.append(P(""))
    L.append(P(" " + pill(f" {sp if n['working'] else '⠿'} {n['working']} working ", PILL_BG["working"])
               + "  " + pill(f" ● {n['attention']} need you ",
                             PILL_BG["attention"] if n["attention"] else PILL_BG["neutral"])))
    L.append(P(" " + pill(f" ✓ {n['done']} done ", PILL_BG["done"])
               + "  " + pill(f" ● {n['neutral']} idle ", PILL_BG["neutral"])))
    L.append(P(""))
    L.append("")

    tl = sorted(((ci, e, t) for ci, c in enumerate(cards, 1)
                 for (e, t) in c["events"] if e is not None), key=lambda x: -x[1])[:9 if tall else 5]
    if tl:
        L.append(P(f" {FAINT}timeline{RST}"))
        for ci, e, t in tl:
            L.append(P(f" {DIM}{fmt_age(now - e):>4}{RST} {INK}▸{ci}{RST} {FAINT}{ANSI.sub('', t)[:width - 14]}{RST}"))
        L.append(P(""))
        L.append("")

    L.append(P(f" {FAINT}vitals{RST}"))
    gauges = []
    if v.get("mem") is not None:
        gauges.append((v["mem"], "good" if v["mem"] > 30 else "bad", "mem free"))
    lim = v.get("limits") or {}
    for key, lbl in (("five_hour", "5h used"), ("seven_day", "wk used")):
        b = lim.get(key) if isinstance(lim, dict) else None
        if isinstance(b, dict) and b.get("used_percentage") is not None:
            pv = int(b["used_percentage"])
            gauges.append((pv, "good" if pv < 70 else ("warn" if pv < 88 else "bad"), lbl))
    gauge_rel = None
    if gauges:
        gauge_rel = len(L)
        for _ in range(3):
            L.append(P(""))
        L.append(P("  " + "".join(f"{DIM}{g[2]:<9}{RST}" for g in gauges)))
        cmap = {"good": 0x4CC38A, "warn": 0xFFB65C, "bad": 0xF0803C}
        L.append(P("  " + "".join(_fg(cmap[g[1]]) + f"{g[0]}%".ljust(9) + RST for g in gauges)))
        resets = []
        for key in ("five_hour", "seven_day"):
            b = lim.get(key) if isinstance(lim, dict) else None
            if isinstance(b, dict) and b.get("resets_at"):
                dt = max(0, int(b["resets_at"] - now))
                resets.append(f"{dt // 86400}d" if dt >= 86400 else f"{dt // 3600}h" if dt >= 3600 else f"{dt // 60}m")
        if resets:
            L.append(P(f"  {FAINT}resets {' · '.join(resets)}{RST}"))
    chart_rel = None
    if v.get("spend") and v.get("spend_total", 0) > 0.5:
        L.append(P(""))
        L.append(P(f" {FAINT}spend today{RST}   {INK}${v['spend_total']:.2f}{RST}"))
        chart_rel = len(L)
        for _ in range(3):
            L.append(P(""))
    info = []
    if v.get("disk") is not None:
        info.append(f"{INK}{v['disk']}G{RST}{DIM} disk{RST}")
    if v.get("load") is not None:
        info.append(f"{INK}{v['load']:.1f}{RST}{DIM} load{RST}")
    if v.get("claudes") is not None:
        info.append(f"{INK}{v['claudes']}{RST}{DIM} claudes · {human(v['crss'])}{RST}")
    if info:
        L.append(P("  " + f"{DIM}  ·  {RST}".join(info)))
    if v.get("tmux") is not None:
        att, tot = v["tmux"]
        L.append(P(f"  {INK}{att}{RST}{DIM} tmux attached · {tot - att} detached{RST}"))
    if v.get("kitty") is not None:
        krss, conns = v["kitty"]
        cc = _fg(0x4CC38A) if conns < 60 else (_fg(0xFFB65C) if conns < 90 else _fg(0xF0803C))
        row = f"  {DIM}kitty {human(krss)} · {RST}{cc}{conns} conns{RST}"
        if conns >= 60:
            row += f" {AMBER}· restart soon{RST}" if conns < 90 else f" {ST['attention'][0]}· RESTART{RST}"
        L.append(P(row))
    L.append(P(""))
    L.append("")

    repos = {}
    for c in cards:
        if c["repo"]:
            r_ = repos.setdefault(c["repo"], [0, 0])
            r_[0] += 1
            r_[1] += c["size"]
    if repos:
        L.append(P(f" {FAINT}repos{RST}"))
        for r_, (cnt, sz) in sorted(repos.items()):
            L.append(P(f" {REPO_HUE[r_]}▎{RST}{INK}{r_:<15}{RST} {DIM}{cnt} session{'s' if cnt != 1 else ''}"
                       f"{' · ' + human(sz) if sz else ''}{RST}"))
        L.append(P(""))
        L.append("")

    L.append(P(f" {DIM}1-9 jump · ⌘⇧A attention · ⌘⇧B broadcast{RST}"))
    L.append(P(f" {DIM}rt-click / m# min \u00b7 M sweep quiet{RST}"))
    L.append(P(f" {DIM}/ filter · : palette · d density{RST}"))
    L.append(P(f" {DIM}s cat · c pet · ⌘⇧K keys · other exits{RST}"))
    return L, gauges, gauge_rel, chart_rel


def fleet_mode(cards):
    n = {s: sum(1 for c in cards if c["state"] == s) for s in ST}
    if n["attention"]:
        return "alert", f"!! {n['attention']} need{'s' if n['attention'] == 1 else ''} you — ⌘⇧A", ST["attention"][0]
    if n["working"]:
        return "walk", f"hunting · {n['working']} working", ST["working"][0]
    if n["done"]:
        return "sit", "satisfied — all quiet", ST["done"][0]
    return "sleep", "napping", DIM


def cat_yard(cards, width, height, frame, sprite=False):
    """The cat's yard: `height` rows, `width` wide."""
    if sprite:  # sprite_patch paints the cat + floor + mood over these rows
        return [pad("", width) for _ in range(height)] if height > 0 else []
    mode, mood, mc = fleet_mode(cards)
    if frame < _pet_until:
        mode, mood, mc = "sit", "purring ♥", MAG
    t = frame
    if mode == "walk":
        # 100-tick stroll, 40-tick sit, with a beat of stillness at each edge
        phase = t % 140
        if phase >= 100:
            art, x = cat_art("sit", t), None
        else:
            art = cat_art("walk", t // 2)
            span = max(4, width - 16)
            p = (t // 2) % (2 * span)
            x = p if p < span else 2 * span - p
    else:
        art, x = cat_art(mode, t), None
    if x is None:
        x = max(2, (width - 14) // 2)

    hearts = ""
    if frame < _pet_until:
        hearts = " " * (x + 3) + MAG + ["♥  ♥", " ♥ ♥", "  ♥  "][frame // 2 % 3] + RST
    lead = max(0, height - 7)  # sink the cat: feet on the beach band
    rows = [""] * lead
    rows.append(hearts)
    rows += [" " * x + AMBER + row + RST for row in art]
    rows += [""] * max(0, height - 1 - len(rows))
    rows = rows[:height - 1]
    rows.insert(height - 2, "    " + mc + mood + RST)
    rows += [""] * max(0, height - len(rows))
    return [pad(r, width) for r in rows[:height]] if height > 0 else []


_WM_STOPS = [(95, 233, 223), (79, 142, 247), (255, 95, 168), (79, 142, 247)]
_WM_BITS = {  # 5-row letterforms, one bit per cell column
    "N": (7, [0b1100011, 0b1110011, 0b1101011, 0b1100111, 0b1100011]),
    "E": (6, [0b111111, 0b110000, 0b111110, 0b110000, 0b111111]),
    "K": (6, [0b110011, 0b110110, 0b111100, 0b110110, 0b110011]),
    "O": (6, [0b111111, 0b110011, 0b110011, 0b110011, 0b111111]),
    "T": (6, [0b111111, 0b001100, 0b001100, 0b001100, 0b001100]),
    "R": (6, [0b111110, 0b110011, 0b111110, 0b110110, 0b110011]),
}


def _wm_grad(t):
    t = t % 1.0
    seg = t * (len(_WM_STOPS) - 1)
    i = int(seg)
    f = seg - i
    a, b = _WM_STOPS[i], _WM_STOPS[min(i + 1, len(_WM_STOPS) - 1)]
    return tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))


def _wm_fg(t):
    r, g, b = _wm_grad(t)
    return f"\033[38;2;{r};{g};{b}m"


def _wm_hex(t):
    r, g, b = _wm_grad(t)
    return (r << 16) | (g << 8) | b


def _wordmark_rows(phase, word="NEKOTRON", stretch_idx=6, extra=4):
    """crush-style letterform wordmark, per-letter gradient, one stretched O."""
    rows = ["", "", "", "", ""]
    for i, chl in enumerate(word):
        w, bits = _WM_BITS[chl]
        col = _wm_fg(phase + i * 0.09)
        for r in range(5):
            row = "".join("\u2588" if bits[r] >> (w - 1 - b) & 1 else " " for b in range(w))
            if i == stretch_idx:
                mid = w // 2
                row = row[:mid] + row[mid] * extra + row[mid:]
            rows[r] += col + row + RST + " "
    return rows


_hit = {"cards": [], "left_w": 0, "yard": None}  # mouse hit-map, rebuilt per full frame


def _tag(cards):
    for j, c in enumerate(cards, 1):
        c["idx"] = j
    return cards


def _match(filt, c):
    if not filt:
        return True
    hay = f"{c.get('title', '')} {c.get('repo') or ''} {c.get('meta') or ''}".lower()
    if filt.lower() in hay:
        return True
    it = iter(hay)
    return all(ch in it for ch in filt.lower())  # fzf-style subsequence


def build_frame(cards, v, cols, rows, tall, frame, mode="ascii", filt=None, peek=None,
                compact=False, pal=None):
    """Full frame string + the cat yard geometry for partial repaints."""
    right_w = 46
    hdr_f = (f"{AMBER}/{filt}\u258e{RST}  {DIM}{len(cards)} match \u00b7 enter jumps \u00b7 esc clears{RST}"
             if filt is not None else None)
    left_w = max(50, min(cols - right_w - 8, 150))
    left = [""]
    if tall:
        wm = _wordmark_rows(frame * 0.045)
        clock_rows = ["", "", "", "", ""]
        for ch in time.strftime("%H:%M"):
            g = DIGITS.get(ch)
            for i in range(5):
                clock_rows[i] += g[i] + "  "
        for r in range(5):
            left.append("  " + wm[r] + "    " + DKCYAN + clock_rows[r] + RST)
        left.append("")
        left.append("  " + (hdr_f or f"{AMBER}\u14da\u160f\u15e2{RST}   {DIM}{time.strftime('%A %b %-d')} \u00b7 fleet board{RST}"))
        left.append("")
    else:
        left.append(f"  {AMBER}ᓚᘏᗢ{RST}  {BOLD}{CYAN}FLEET BOARD{RST}   {hdr_f or DIM + time.strftime('%a %H:%M') + RST}")
        left.append("")
    now = time.time()
    card_spans = []
    card_marks = []
    for i, c in enumerate(cards, 1):
        color, glyph, label = ST[c["state"]]
        if c["state"] == "working":
            glyph = SPIN[frame % len(SPIN)]
            color = _wm_fg(frame * 0.02)
        hue = REPO_HUE.get(c["repo"], FAINT)
        bg = PANEL_HI if c["focused"] else PANEL
        card_start = len(left)
        Pc = lambda content: panel_row(content, left_w, bg)
        c_min = c.get("min") and c["state"] != "attention"  # attention re-expands
        if compact or c_min:  # one row per session
            b = BOLD if c["focused"] else ""
            row_idx = len(left)
            ctxs, ring_kind = "", None
            if c.get("ctx") is not None:
                cc = DIM if c["ctx"] < 70 else (AMBER if c["ctx"] < 88 else ST["attention"][0])
                ring_kind = f"ring:{5 * round(c['ctx'] / 5)},{'good' if c['ctx'] < 70 else ('warn' if c['ctx'] < 88 else 'bad')}"
                ctxs = f"{cc}{c['ctx']:>2}%{RST}    "
            age = fmt_age(now - c["s_epoch"]) if c["s_epoch"] else ""
            lead = f"  {DIM}\u25b8{RST} " if c_min and not compact else "    "
            head = f"{lead}{b}{INK}{c.get('idx', i)}{RST} {hue}\u258e{RST}{color}{glyph}{RST} {b}{INK}{c['title'][:left_w - 52]}{RST}"
            tail = ctxs + pill(f" {label} ", PILL_BG[c["state"]],
                           fg=(_wm_hex(frame * 0.02) if c["state"] == "working" else 0xE8ECFF),
                           panel=bg) + (f" {DIM}{age:<4}{RST}" if age else "")
            gap = left_w - 2 - vlen(head) - vlen(tail)
            if ring_kind:
                card_marks.append((row_idx, left_w - vlen(tail) - 2, ring_kind))
            left.append(Pc(head + " " * max(1, gap) + tail))
            card_spans.append((card_start, 0, c["focused"], c.get("idx", i)))
            left.append("")
            continue
        age = fmt_age(now - c["s_epoch"]) if c["s_epoch"] else ""
        ctxs, ring_kind = "", None
        if c.get("ctx") is not None:
            cc = DIM if c["ctx"] < 70 else (AMBER if c["ctx"] < 88 else ST["attention"][0])
            ring_color = "good" if c["ctx"] < 70 else ("warn" if c["ctx"] < 88 else "bad")
            ring_kind = f"ring:{5 * round(c['ctx'] / 5)},{ring_color}"
            ctxs = f"{cc}{c['ctx']:>2}%{RST}    "
        if c.get("sid"):
            card_marks.append((len(left) + 1, 2, f"icon:{c['sid']}|{c['repo'] or ''}"))
        b = BOLD if c["focused"] else ""
        head = f"    {b}{INK}{c.get('idx', i)}{RST} {hue}▎{RST}{color}{glyph}{RST} {b}{INK}{c['title'][:left_w - 48]}{RST}"
        tail = ctxs + pill(f" {label} ", PILL_BG[c["state"]],
                           fg=(_wm_hex(frame * 0.02) if c["state"] == "working" else 0xE8ECFF),
                           panel=bg) + (f" {DIM}{age:<4}{RST}" if age else "")
        gap = left_w - 2 - vlen(head) - vlen(tail)
        if ring_kind:
            card_marks.append((len(left) + 1, left_w - vlen(tail) - 2, ring_kind))
        left.append(Pc(""))
        left.append(Pc(head + " " * max(1, gap) + tail))
        if c["repo"] or c["meta"]:
            rep = f"{hue}{c['repo']}{RST}" if c["repo"] else ""
            joiner = f"{DIM} · {RST}" if c["repo"] and c["meta"] else ""
            left.append(Pc(f"      {rep}{joiner}{DIM}{c['meta']}{RST}"))
        if c.get("note"):
            left.append(Pc(f"      {AMBER}✎ {c['note']}{RST}"))
        for e, t in c["events"]:
            txt = t
            if vlen(txt) > left_w - 16:
                txt = txt[: len(txt) - (vlen(txt) - (left_w - 17))] + "…"
            left.append(Pc(f"      {DIM}{fmt_age(now - e) if e else '':>4}{RST} {txt}{RST}"))
        left.append(Pc(""))
        card_spans.append((card_start, len(left) - card_start, c["focused"], c.get("idx", i)))
        left.append("")

    if pal is not None:  # command palette owns the right column
        gauges, gauge_rel, chart_rel = None, None, None
        q, acts = pal
        right = ["", ""]
        right.append(f"   {CYAN}\u2318{RST} {BOLD}{INK}palette{RST}   {DIM}enter runs top \u00b7 esc closes{RST}")
        right.append(f"   {AMBER}: {q}\u258e{RST}")
        right.append("   " + FAINT + "\u2500" * (right_w - 8) + RST)
        for j, lbl in enumerate(acts[: rows - 12]):
            mk = f"{MAG}\u25b8{RST} " if j == 0 else "  "
            cl = INK if j == 0 else DIM
            right.append(f"   {mk}{cl}{lbl}{RST}")
        if not acts:
            right.append(f"   {DIM}(no matching action){RST}")
        ops_lines = right[2:]
        yard_top, yard_col, yard_h = len(right) + 2, left_w + 6, 0
    elif peek:  # hover-peek: the right column becomes a live glimpse of that tab
        gauges, gauge_rel, chart_rel = None, None, None
        right = ["", ""]
        right.append(f"   {CYAN}\u2316{RST} {BOLD}{INK}{vtrunc(peek['title'], right_w - 12)}{RST}")
        right.append(f"   {DIM}live \u00b7 click the card to jump{RST}")
        right.append("   " + FAINT + "\u2500" * (right_w - 8) + RST)
        for ln in peek["lines"][: rows - 8]:
            right.append("   " + vtrunc(ln, right_w - 8))
        ops_lines = right[2:]
        yard_top, yard_col, yard_h = len(right) + 2, left_w + 6, 0
    else:
        ops_lines, gauges, gauge_rel, chart_rel = ops_column(cards, v, right_w - 4, tall, frame)
        right = [""] * (4 if not tall else 3) + ops_lines
        yard_top = len(right) + 2          # 1-indexed row where the yard begins
        yard_col = left_w + 6              # 1-indexed column of the right block
        yard_h = max(0, min(10, rows - yard_top))  # perch under the keys, not the horizon
        right += [""]
        right += cat_yard(cards, right_w - 2, yard_h, frame, sprite=(mode == "sprite"))
        _hit["yard"] = (yard_top, yard_top + yard_h, yard_col)

    n_rows = max(len(left), len(right))
    left += [""] * (n_rows - len(left))
    right += [""] * (n_rows - len(right))
    lines = [pad(l, left_w + 5) + r for l, r in zip(left, right)]
    buf = []
    for i, line in enumerate(lines[:rows]):
        buf.append(f"\033[{i + 1};1H{line}\033[K")
    frame_str = "".join(buf) + "\033[J"
    prefix = 4 if not tall else 3
    if gauges and gauge_rel is not None:
        g_row = prefix + gauge_rel + 1
        if g_row + 2 < rows:
            frame_str += gauge_escapes(g_row, left_w + 8, gauges)
    placements = []
    if tall:
        placements.append((1, 1, min(cols, left_w + 5), 9, "aurora"))
    _hit["cards"] = [(s + 1, s + h + 1, ix) for s, h, _f, ix in card_spans]
    _hit["left_w"] = left_w
    for start, h, focused, _ix in card_spans:
        if start + h + 1 < rows:
            placements.append((start + 1, 1, left_w, h + 1, "card_hi" if focused else "card"))
    for row, col, kind in card_marks:
        if row < rows:
            placements.append((row + 1, col, 2, 1, kind))
    ops_h = len(ops_lines)
    if prefix + ops_h + 1 < rows:
        placements.append((prefix + 1, left_w + 6, right_w - 2, ops_h + 1, "card"))
    if chart_rel is not None and v.get("spend"):
        ck = str(hash(tuple(round(x, 2) for x in v["spend"])) & 0xFFFFFF)
        _chart_series[ck] = v["spend"]
        placements.append((prefix + chart_rel + 1, left_w + 8, right_w - 10, 3, f"chart:{ck}"))
    if yard_h >= 6:
        now_t = time.localtime()
        pb = (now_t.tm_hour * 3600 + now_t.tm_min * 60) * 144 // 86400
        mood_cells = len(fleet_mode(cards)[1]) + 2
        placements.append((yard_top, yard_col, right_w - 2, yard_h, f"dio:{pb}:{mood_cells}"))
    if peek or pal is not None:  # right column repurposed: evict ring + cat images
        for gid in sorted(_gauge_placed):
            frame_str += _gfx({"a": "d", "d": "i", "i": gid, "q": 2})
        _gauge_placed.clear()
        if _prev_sprite is not None:
            frame_str += _gfx({"a": "d", "d": "i", "i": _prev_sprite, "q": 2})
    frame_str += underlay_escapes(placements)
    return frame_str, (yard_top, yard_col, right_w - 2, yard_h)


def yard_patch(cards, geo, frame):
    """Repaint only the cat's yard between data refreshes."""
    top, col, width, height = geo
    if height <= 0:
        return ""
    rows = cat_yard(cards, width, height, frame)
    return "".join(f"\033[{top + i};{col}H{row}\033[K" for i, row in enumerate(rows))


def _sock_answers(s):
    """A socket that accepts but never replies (starved/wedged kitty) is useless."""
    try:
        r = subprocess.run([KITTEN, "@", "--to", f"unix:{s}", "ls"],
                           capture_output=True, text=True, timeout=3)
        return bool(r.stdout.strip())
    except Exception:
        return False


def _live_sock():
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


def main():
    sock = _live_sock()
    if not sock:
        print("no live kitty remote-control socket"); return
    kpid = sock.rsplit("-", 1)[-1]

    once = "--print" in sys.argv
    watch = "--watch" in sys.argv
    test_frames = 0
    if "--frames" in sys.argv:
        test_frames = int(sys.argv[sys.argv.index("--frames") + 1])

    ts = shutil.get_terminal_size((140, 40))
    feed_n = max(1, min(4, (ts.lines - 14) // 6 - 3))
    cards = _tag(gather(sock, kpid, feed_n))
    v = vitals()

    mode = cat_mode()
    if os.environ.get("FLEET_PET"):
        globals()["_pet_until"] = 1 << 30

    if once:
        tall = ts.lines >= 42 and ts.columns >= 160
        frame_str, geo = build_frame(cards, v, ts.columns, ts.lines, tall, 0, mode)
        sys.stdout.write(frame_str)
        if mode == "sprite":
            sys.stdout.write(sprite_patch(cards, geo, 0))
        sys.stdout.write("\n")
        return

    interactive = sys.stdin.isatty() and not test_frames and not watch
    old = None
    if interactive:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setraw(fd)
    sys.stdout.write("\033[?25l\033[2J")
    if interactive:
        sys.stdout.write("\033[?1002h\033[?1006h")  # SGR button-event mouse tracking (hover shelved)
    choice = None
    peek_on = False
    filt = None
    pal = None
    compact = os.path.exists(DENSITY_FILE)
    minset = _load_min()
    pend_min = False
    hover_idx = None
    hover_since = 0
    peek = None
    frame = 0
    geo = None
    last_size = None
    fails = 0
    try:
        while True:
            ts = shutil.get_terminal_size((140, 40))
            size = (ts.columns, ts.lines)
            tall = ts.lines >= 42 and ts.columns >= 160
            full = frame % 20 == 0 or size != last_size or geo is None
            try:  # transient kitten/tmux stalls must not kill a live dashboard
                every = 20 if fails < 2 else 150  # back off hard when kitty is slow
                if frame and frame % every == 0:
                    feed_n = max(1, min(4, (ts.lines - 14) // max(1, len(cards) or 1) - 3))
                    cards = _tag(gather(sock, kpid, feed_n))
                    fails = 0
                if frame and frame % 60 == 0:  # vitals every ~6s
                    v = vitals()
            except Exception:
                fails += 1  # keep showing the previous data; retry later
            for c in cards:
                c["min"] = _min_key(c) in minset
            vis = cards if filt is None else [c for c in cards if _match(filt, c)]
            pal_view = None
            if pal is not None:
                pal_view = (pal, [l for l, _k, _a in PALETTE if _match(pal, {"title": l})])
            if interactive and (bool(peek) or pal is not None) != peek_on:
                peek_on = bool(peek) or pal is not None
                sys.stdout.write("\033[2J")
                geo = None
                full = True
            if full:
                frame_str, geo = build_frame(vis, v, ts.columns, ts.lines, tall, frame, mode, filt, peek,
                                             compact, pal_view)
                sys.stdout.write(frame_str)
            elif mode == "ascii" and peek is None:
                sys.stdout.write(yard_patch(vis, geo, frame))
            if mode == "sprite" and peek is None:
                sys.stdout.write(sprite_patch(vis, geo, frame))
            if interactive and tall and not full:
                wmp = _wordmark_rows(frame * 0.045)
                sys.stdout.write("".join(f"\033[{2 + r};3H" + wmp[r] for r in range(5)))
            sys.stdout.flush()
            last_size = size
            if test_frames and frame >= test_frames:
                break
            if interactive:
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if r:
                    data = os.read(fd, 64).decode("utf-8", "replace")
                    while select.select([sys.stdin], [], [], 0.004)[0]:
                        more = os.read(fd, 512)
                        if not more:
                            break
                        data += more.decode("utf-8", "replace")
                    mouse = re.findall(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])", data)
                    keys = re.sub(r"\x1b\[<\d+;\d+;\d+[Mm]", "", data)
                    quit_ = False
                    for mb_, mx_, my_, kind in mouse:
                        mb_, mx_, my_ = int(mb_), int(mx_), int(my_)
                        if kind == "M" and mb_ == 2:  # right click: (un)minimize card
                            hitc = next((ix for r0, r1, ix in _hit["cards"]
                                         if r0 <= my_ <= r1 and mx_ <= _hit["left_w"] + 2), None)
                            if hitc:
                                mc_ = next((c for c in cards if c.get("idx") == hitc), None)
                                if mc_:
                                    minset ^= {_min_key(mc_)}
                                    _save_min(minset)
                                    geo = None
                        if kind == "M" and mb_ == 0:  # left click
                            hitc = next((ix for r0, r1, ix in _hit["cards"]
                                         if r0 <= my_ <= r1 and mx_ <= _hit["left_w"] + 2), None)
                            if hitc:
                                choice = hitc
                            elif (_hit["yard"] and peek is None and mx_ >= _hit["yard"][2]
                                  and _hit["yard"][0] <= my_ <= _hit["yard"][1]):
                                globals()["_pet_until"] = frame + 30  # click the yard = pet
                                try:
                                    subprocess.Popen(["/usr/bin/afplay", "/System/Library/Sounds/Purr.aiff"],
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                except Exception:
                                    pass
                    for ch in keys:
                        was_pend, pend_min = pend_min, False
                        if pal is not None:  # palette mode: typing filters actions
                            if ch == "\x1b":
                                pal, geo = None, None
                            elif ch in ("\r", "\n"):
                                acts = [(l, k, a) for l, k, a in PALETTE if _match(pal, {"title": l})]
                                pal, geo = None, None
                                if acts:
                                    _lbl, kind, arg = acts[0]
                                    if kind == "pet":
                                        globals()["_pet_until"] = frame + 30
                                    elif kind == "sprite":
                                        mode = "sprite" if mode == "ascii" else "ascii"
                                        try:
                                            with open(CAT_MODE_FILE, "w") as f:
                                                f.write(mode)
                                        except OSError:
                                            pass
                                        sys.stdout.write(_gfx({"a": "d", "d": "A", "q": 2}))
                                        _transmitted.clear()
                                        globals()["_prev_sprite"] = None
                                    elif kind == "minsweep":
                                        quiet = {_min_key(c) for c in cards
                                                 if c["state"] in ("done", "neutral")} - {""}
                                        minset = minset - quiet if quiet <= minset else minset | quiet
                                        _save_min(minset)
                                    elif kind == "density":
                                        compact = not compact
                                        try:
                                            open(DENSITY_FILE, "w").close() if compact else os.unlink(DENSITY_FILE)
                                        except OSError:
                                            pass
                                    elif kind == "run":
                                        subprocess.Popen([arg], stdout=subprocess.DEVNULL,
                                                         stderr=subprocess.DEVNULL)
                                    elif kind in ("overlay", "run_quit"):
                                        if kind == "overlay":
                                            subprocess.Popen([KITTEN, "@", "--to", f"unix:{sock}", "launch",
                                                              "--type=overlay", arg],
                                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                        else:
                                            subprocess.Popen([arg], stdout=subprocess.DEVNULL,
                                                             stderr=subprocess.DEVNULL)
                                        quit_ = True
                            elif ch in ("\x7f", "\x08"):
                                pal, geo = (pal[:-1] if pal else None), None
                            elif ch.isprintable():
                                pal += ch
                                geo = None
                        elif filt is not None:  # filter mode: typing edits the query
                            if ch == "\x1b":
                                filt, geo = None, None
                            elif ch in ("\r", "\n"):
                                vis0 = [c for c in cards if _match(filt, c)]
                                if vis0:
                                    choice = vis0[0]["idx"]
                            elif ch in ("\x7f", "\x08"):
                                filt, geo = (filt[:-1] if filt else None), None
                            elif ch.isprintable():
                                filt += ch
                                geo = None
                        elif ch == "/":
                            filt, geo = "", None
                        elif ch == ":":
                            pal, geo = "", None
                        elif ch == "m":
                            pend_min = True
                        elif ch == "M":  # sweep: minimize every quiet session (or restore)
                            quiet = {_min_key(c) for c in cards
                                     if c["state"] in ("done", "neutral")} - {""}
                            minset = minset - quiet if quiet <= minset else minset | quiet
                            _save_min(minset)
                            geo = None
                        elif ch == "d":
                            compact = not compact
                            try:
                                open(DENSITY_FILE, "w").close() if compact else os.unlink(DENSITY_FILE)
                            except OSError:
                                pass
                            geo = None
                        elif ch == "c":
                            globals()["_pet_until"] = frame + 30
                            try:
                                subprocess.Popen(["/usr/bin/afplay", "/System/Library/Sounds/Purr.aiff"],
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            except Exception:
                                pass
                        elif ch == "s":
                            mode = "sprite" if mode == "ascii" else "ascii"
                            try:
                                with open(CAT_MODE_FILE, "w") as f:
                                    f.write(mode)
                            except OSError:
                                pass
                            sys.stdout.write(_gfx({"a": "d", "d": "A", "q": 2}))
                            _transmitted.clear()
                            globals()["_prev_sprite"] = None
                            geo = None  # force full redraw next tick
                        elif ch.isdigit():
                            sel = 10 if ch == "0" else int(ch)
                            if not 0 < sel <= len(cards):
                                pass
                            elif was_pend:  # m+digit: toggle that card
                                minset ^= {_min_key(cards[sel - 1])}
                                _save_min(minset)
                                geo = None
                            else:
                                choice = sel
                        elif ch == "\x1b" and (peek is not None or hover_idx is not None):
                            hover_idx, peek, geo = None, None, None
                        else:
                            quit_ = True
                    if choice is not None or quit_:
                        break
            else:
                time.sleep(0.1 if watch else 0.02)
            frame += 1
    finally:
        sys.stdout.write(_gfx({"a": "d", "d": "A", "q": 2}))  # clear our sprites
        sys.stdout.write("\033[?1002l\033[?1003l\033[?1006l\033[?25h\033[0m")
        if old is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
    if choice:
        subprocess.run([KITTEN, "@", "--to", f"unix:{sock}", "focus-tab",
                        "--match", f"index:{choice-1}"], capture_output=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:  # deliberate diagnosis (e.g. wedged control socket)
        if e.code and not isinstance(e.code, int):
            print(f"\033[38;2;240;128;60m{e.code}\033[0m")
            time.sleep(6)
    except Exception as e:
        print(f"fleet board error: {e}")
        time.sleep(2)

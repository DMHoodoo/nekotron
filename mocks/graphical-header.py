#!/usr/bin/env python3
"""Graphical fleet-board header v2: rounded PANEL card (matches board cards),
glowing segment clock, bitmap wordmark, ASCII cat stamped in pixels."""
import math
import os
import struct
import time
import zlib

W, H = 880, 132
RAD = 18
PANEL_TOP = (23, 31, 56)
PANEL_BOT = (16, 22, 42)
CYAN = (95, 233, 223)
AMBER = (255, 182, 92)
DIM = (107, 115, 148)
INK = (232, 236, 255)

buf = bytearray(W * H * 4)  # starts fully transparent
glow = bytearray(W * H)


def inside_panel(x, y):
    """Distance-based rounded-rect mask. >=1 inside, 0..1 edge, <0 outside."""
    dx = max(RAD - x, 0, x - (W - 1 - RAD))
    dy = max(RAD - y, 0, y - (H - 1 - RAD))
    return RAD + 1.0 - math.hypot(dx, dy)


def px(x, y, c, a=255):
    if 0 <= x < W and 0 <= y < H:
        i = (y * W + x) * 4
        sa = a / 255
        buf[i] = int(buf[i] * (1 - sa) + c[0] * sa)
        buf[i + 1] = int(buf[i + 1] * (1 - sa) + c[1] * sa)
        buf[i + 2] = int(buf[i + 2] * (1 - sa) + c[2] * sa)
        buf[i + 3] = max(buf[i + 3], int(255 * sa))


# rounded panel with a soft top-to-bottom sheen; transparent outside
for y in range(H):
    t = y / H
    base = tuple(int(PANEL_TOP[j] + (PANEL_BOT[j] - PANEL_TOP[j]) * t) for j in range(3))
    for x in range(W):
        m = inside_panel(x, y)
        if m > 0:
            a = 255 if m >= 1.5 else int(255 * max(0.0, m / 1.5))
            i = (y * W + x) * 4
            buf[i:i + 3] = bytes(base)
            buf[i + 3] = a

def capsule(x0, y0, x1, y1, rad, color):
    for y in range(int(y0 - rad - 2), int(y1 + rad + 3)):
        for x in range(int(x0 - rad - 2), int(x1 + rad + 3)):
            dx = max(x0 - x, 0, x - x1)
            dy = max(y0 - y, 0, y - y1)
            d = math.hypot(dx, dy)
            if d <= rad + 1.2:
                a = 255 if d <= rad - 0.6 else int(255 * max(0, (rad + 1.2 - d) / 1.8))
                px(x, y, color, a)
                if 0 <= x < W and 0 <= y < H and a > 40:
                    glow[y * W + x] = max(glow[y * W + x], 140)


SEGS = {"a": (True, 1, 0), "b": (False, 9, 1), "c": (False, 9, 10), "d": (True, 1, 17),
        "e": (False, 0, 10), "f": (False, 0, 1), "g": (True, 1, 9)}
DIG = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
       "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abfgcd"}


def seg_digit(ch, ox, oy, s=3.4, color=CYAN):
    for name in DIG.get(ch, ""):
        horiz, gx, gy = SEGS[name]
        if horiz:
            capsule(ox + (gx + 1) * s, oy + gy * s, ox + (gx + 7) * s, oy + gy * s, s * 0.85, color)
        else:
            capsule(ox + gx * s, oy + (gy + 1) * s, ox + gx * s, oy + (gy + 6) * s, s * 0.85, color)


clock = time.strftime("%H:%M")
cx = 40
for ch in clock:
    if ch == ":":
        capsule(cx + 5, 52, cx + 5, 52, 4.5, CYAN)
        capsule(cx + 5, 82, cx + 5, 82, 4.5, CYAN)
        cx += 24
    else:
        seg_digit(ch, cx, 34)
        cx += 50

for _ in range(3):
    nxt = bytearray(W * H)
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            i = y * W + x
            nxt[i] = (glow[i] + glow[i - 1] + glow[i + 1] + glow[i - W] + glow[i + W]) // 5
    glow = nxt
for y in range(H):
    for x in range(W):
        g = glow[y * W + x]
        if g > 4 and inside_panel(x, y) > 0:
            i = (y * W + x) * 4
            buf[i] = min(255, buf[i] + g * CYAN[0] // 900)
            buf[i + 1] = min(255, buf[i + 1] + g * CYAN[1] // 700)
            buf[i + 2] = min(255, buf[i + 2] + g * CYAN[2] // 700)

F = {
    "F": ["#####", "#....", "####.", "#....", "#....", "#....", "#...."],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "E": ["#####", "#....", "####.", "#....", "#....", "#....", "#####"],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "I": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
    "J": ["#####", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    " ": ["....."] * 7,
    "/": ["....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."],
    "\\": ["#....", ".#...", ".#...", "..#..", "...#.", "...#.", "....#"],
    "_": ["....."] * 6 + ["#####"],
    "(": ["..#..", ".#...", "#....", "#....", "#....", ".#...", "..#.."],
    ")": ["..#..", "...#.", "....#", "....#", "....#", "...#.", "..#.."],
    "^": ["..#..", ".#.#.", "#...#", ".....", ".....", ".....", "....."],
    ".": [".....", ".....", ".....", ".....", ".....", ".##..", ".##.."],
    "~": [".....", ".....", ".##.#", "#..#.", ".....", ".....", "....."],
    '"': [".#.#.", ".#.#.", ".....", ".....", ".....", ".....", "....."],
}


def word(text, ox, oy, s, color):
    cx_ = ox
    for ch in text:
        gl = F.get(ch.upper() if ch.isalpha() else ch)
        if gl:
            for gy in range(7):
                for gx in range(5):
                    if gl[gy][gx] == "#":
                        for dy in range(s):
                            for dx in range(s):
                                px(cx_ + gx * s + dx, oy + gy * s + dy, color)
        cx_ += 6 * s
    return cx_


word("FLEET BOARD", 296, 36, 4, INK)
word("FRIDAY JUL 10", 298, 76, 2, DIM)
for x in range(296, 700):
    fade = max(0, 1 - (x - 296) / 404)
    px(x, 96, CYAN, int(120 * fade))

rows = b"".join(b"\x00" + bytes(buf[y * W * 4:(y + 1) * W * 4]) for y in range(H))
def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graphical-header.png")
open(out, "wb").write(png)
print(out)

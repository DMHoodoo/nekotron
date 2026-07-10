#!/usr/bin/env python3
"""Render draft cat sprite maps to a montage PNG for visual review."""
import struct
import zlib

PAL = {"D": (60, 42, 20, 255), "O": (255, 182, 92, 255), "S": (214, 138, 52, 255),
       "W": (240, 236, 255, 255), "P": (255, 95, 168, 255), "B": (24, 26, 40, 255),
       ".": (10, 13, 24, 255), "|": (30, 35, 56, 255)}

MAPS = {
    # walking, side view facing left: round head, filled ears, eye forward,
    # arched back, rising tail, alternating legs
    "walk1": [
        "..DD.....DD.........",
        "..DOD...DOD.........",
        "..DOODDDOOD.........",
        ".DOOOOOOOOD.........",
        ".DOBOOOOOOD.........",
        ".DOOOOOOOODDDD......",
        ".DWWOOOOOOOOOODD.DD.",
        "..DOOOOOOOOOOOODDOD.",
        "...DOOOOOOOOOOOOOD..",
        "...DOSOOOSOOOSOOD...",
        "...DOD....DOD.......",
        "...DOD.....DOD......",
        "...DDD.....DDD......",
    ],
    "walk2": [
        "..DD.....DD.........",
        "..DOD...DOD.........",
        "..DOODDDOOD.........",
        ".DOOOOOOOOD.........",
        ".DOBOOOOOOD.........",
        ".DOOOOOOOODDDD......",
        ".DWWOOOOOOOOOODD.DD.",
        "..DOOOOOOOOOOOODDOD.",
        "...DOOOOOOOOOOOOOD..",
        "...DOSOOOSOOOSOOD...",
        "....DOD...DOD.......",
        "...DOD......DOD.....",
        "...DDD......DDD.....",
    ],
    # sitting, front 3/4: two eyes, pink nose, white muzzle, tail curled front
    "sit1": [
        "..DD....DD..........",
        "..DOD..DOD..........",
        "..DOODDOOD..........",
        ".DOOOOOOOOD.........",
        ".DOBOOOOBOD.........",
        ".DOOOPOOOOD.........",
        "..DWWWWWOD..........",
        "..DOOOOOOOD.........",
        ".DOOOOOOOOOD........",
        ".DOOOOOOOOOOD.......",
        ".DOSOOSOOSOODDDD....",
        ".DOOOOOOOOOODOOOD...",
        "..DDDDDDDDDD.DDD....",
    ],
    "sit2": [
        "..DD....DD..........",
        "..DOD..DOD..........",
        "..DOODDOOD..........",
        ".DOOOOOOOOD.........",
        ".DOBOOOOBOD.........",
        ".DOOOPOOOOD.........",
        "..DWWWWWOD.....DD...",
        "..DOOOOOOOD...DOD...",
        ".DOOOOOOOOOD..DOD...",
        ".DOOOOOOOOOOD.DOD...",
        ".DOSOOSOOSOODDOD....",
        ".DOOOOOOOOOODDD.....",
        "..DDDDDDDDDD........",
    ],
    # sleeping loaf: ear nubs, closed eyes, tucked tail, gentle stripes
    "sleep1": [
        "....................",
        "....................",
        "....................",
        "...DD..DD...........",
        "..DOODDOODDDDD......",
        ".DOOOOOOOOOOOODD....",
        ".DODDOOOOOOOOOOOD...",
        ".DOOOOOOOOOOOOOOD...",
        ".DOSOOOSOOOSOOOOD...",
        ".DOOOOOOOOOOOOOOD...",
        "..DDDDDDDDDDDDDD....",
        "....................",
        "....................",
    ],
    "sleep2": [
        "....................",
        "....................",
        "....................",
        "...DD..DD...........",
        "..DOODDOODDDDD......",
        ".DOOOOOOOOOOOODD....",
        ".DODDOOOOOOOOOOOD...",
        ".DOOOOOOOOOOOOOOOD..",
        ".DOSOOOSOOOSOOOOOD..",
        ".DOOOOOOOOOOOOOOD...",
        "..DDDDDDDDDDDDDD....",
        "....................",
        "....................",
    ],
    # alert, front-facing: ears pricked, wide eyes, tail straight up, pink !
    "alert1": [
        ".DD....DD.....P.....",
        ".DOD..DOD.....P.....",
        ".DOODDOOD...........",
        "DOOOOOOOOD....P.....",
        "DOBBOOBBOD..........",
        "DOOOPOOOOD.....DD...",
        ".DWWWWWOD......DOD..",
        ".DOOOOOOOD.....DOD..",
        "DOOOOOOOOOD....DOD..",
        "DOOOOOOOOOOD..DOD...",
        "DOSOOSOOSOODDDOD....",
        "DOOOOOOOOOODDDD.....",
        ".DDDDDDDDDD.........",
    ],
    "alert2": [
        ".DD....DD...........",
        ".DOD..DOD...........",
        ".DOODDOOD...........",
        "DOOOOOOOOD..........",
        "DOBBOOBBOD..........",
        "DOOOPOOOOD.....DD...",
        ".DWWWWWOD......DOD..",
        ".DOOOOOOOD.....DOD..",
        "DOOOOOOOOOD....DOD..",
        "DOOOOOOOOOOD..DOD...",
        "DOSOOSOOSOODDDOD....",
        "DOOOOOOOOOODDDD.....",
        ".DDDDDDDDDD.........",
    ],
}


def png(pixmap, scale=8):
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


# montage: all frames side by side with separators
names = ["walk1", "walk2", "sit1", "sit2", "sleep1", "sleep2", "alert1", "alert2"]
H = 13
rows = []
for r in range(H):
    parts = [MAPS[n][r].ljust(20, ".") for n in names]
    rows.append("|".join(parts))
out = "/private/tmp/claude-504/-Users-hassankhan-Documents-GlowDevelopment-glow-platform/fd5f17ac-d945-4a77-8556-6590eb79fcd1/scratchpad/cat-montage.png"
with open(out, "wb") as f:
    f.write(png(rows, scale=8))
print(out)

#!/usr/bin/env python3
"""Preview: NEKOTRON wordmark (crush-style letterforms, one stretched letter)
shown against the current board header. Run it, look, decide.
"""
import time

CYAN = (95, 233, 223)
MAG = (255, 95, 168)
AMBER = "\033[38;2;255;182;92m"
DKCYAN = "\033[38;2;38;98;110m"
DIM = "\033[38;2;107;115;148m"
INK = "\033[38;2;232;236;255m"
BOLD, RST = "\033[1m", "\033[0m"

L = {
    "N": ["██   ██", "███  ██", "██ █ ██", "██  ███", "██   ██"],
    "E": ["██████", "██    ", "█████ ", "██    ", "██████"],
    "K": ["██  ██", "██ ██ ", "████  ", "██ ██ ", "██  ██"],
    "O": ["██████", "██  ██", "██  ██", "██  ██", "██████"],
    "T": ["██████", "  ██  ", "  ██  ", "  ██  ", "  ██  "],
    "R": ["█████ ", "██  ██", "█████ ", "██ ██ ", "██  ██"],
}


def stretch(glyph, extra):
    """Widen a letter crush-style: repeat its middle column."""
    out = []
    for row in glyph:
        mid = len(row) // 2
        out.append(row[:mid] + row[mid] * extra + row[mid:])
    return out


def wordmark(word="NEKOTRON", stretch_idx=6, extra=4):
    glyphs = [stretch(L[c], extra) if i == stretch_idx else L[c]
              for i, c in enumerate(word)]
    n = len(glyphs)
    rows = []
    for r in range(5):
        row = ""
        for i, g in enumerate(glyphs):
            t = i / max(1, n - 1)
            c = tuple(int(CYAN[k] + (MAG[k] - CYAN[k]) * t) for k in range(3))
            row += f"\033[38;2;{c[0]};{c[1]};{c[2]}m{g[r]}\033[0m "
        rows.append("  " + row)
    return rows


def main():
    print()
    print(f"  {DIM}── current header ─────────────────────────────────────────{RST}")
    print()
    print(f"  {AMBER}ᓚᘏᗢ{RST}  {BOLD}\033[38;2;95;233;223mFLEET BOARD{RST}   {DIM}{time.strftime('%A %b %-d')}{RST}")
    print()
    print(f"  {DIM}── wordmark option (gradient, stretched O) ────────────────{RST}")
    print()
    for row in wordmark():
        print(row)
    print()
    print(f"  {AMBER}ᓚᘏᗢ{RST}   {DIM}{time.strftime('%A %b %-d')}   ·   the cat keeps his spot{RST}")
    print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Preview: crush-style gradient shimmer, applied to the things it would
touch on the board — the working pill and the wordmark. Animates ~8s.
"""
import math
import sys
import time

INK = "\033[38;2;232;236;255m"
DIM = "\033[38;2;107;115;148m"
RST = "\033[0m"
PILL_BG = (30, 58, 95)

# gradient stops the shimmer sweeps through (cyan → blue → magenta)
STOPS = [(95, 233, 223), (79, 142, 247), (255, 95, 168), (79, 142, 247)]


def grad(t):
    t = t % 1.0
    seg = t * (len(STOPS) - 1)
    i = int(seg)
    f = seg - i
    a, b = STOPS[i], STOPS[min(i + 1, len(STOPS) - 1)]
    return tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))


def fg(c):
    return f"\033[38;2;{c[0]};{c[1]};{c[2]}m"


def bg(c):
    return f"\033[48;2;{c[0]};{c[1]};{c[2]}m"


def shimmer_text(text, phase, spread=0.06):
    out = ""
    for i, ch in enumerate(text):
        out += fg(grad(phase + i * spread)) + ch
    return out + RST


def shimmer_pill(text, phase):
    c = grad(phase)
    return (fg(PILL_BG) + "" + RST + bg(PILL_BG) + fg(c) + text + RST
            + fg(PILL_BG) + "" + RST)


def main():
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    sys.stdout.write("\033[?25l\n\n\n\n\n\n")
    try:
        t0 = time.time()
        while time.time() - t0 < 8:
            ph = (time.time() - t0) * 0.35
            sp = spin[int((time.time() - t0) * 10) % len(spin)]
            sys.stdout.write("\033[6A")
            sys.stdout.write(f"\r\033[K  {DIM}working pill, today:{RST}      "
                             f"{fg(PILL_BG)}{RST}{bg(PILL_BG)}\033[38;2;79;142;247m {sp} working {RST}{fg(PILL_BG)}{RST}\n")
            sys.stdout.write(f"\r\033[K  {DIM}with shimmer:{RST}             "
                             f"{shimmer_pill(f' {sp} working ', ph)}\n\n")
            sys.stdout.write(f"\r\033[K  {DIM}wordmark, static gradient:{RST} {INK}N E K O T R O N{RST}\n")
            sys.stdout.write(f"\r\033[K  {DIM}with shimmer:{RST}             "
                             f"{shimmer_text('N E K O T R O N', ph, 0.045)}\n\n")
            sys.stdout.flush()
            time.sleep(0.066)
    finally:
        sys.stdout.write("\033[?25h" + RST)
        print(f"  {DIM}(that's the effect — 15fps, costs one redraw of those cells per tick){RST}\n")


if __name__ == "__main__":
    main()

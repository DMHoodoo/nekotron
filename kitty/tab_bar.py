# "Signal" kitty tab bar for Claude Code sessions.
# Monochrome tabs, one LED per tab carrying the status; active tab is
# reverse-video. Right corner: fleet minimap (one block per tab, colored by
# status), attention counter, clock.
#
# State files are written by ~/.claude/hooks/kitty-tab-status.sh to
# /tmp/claude-kitty-status/<kitty_pid>-<window_id>:
#   working   -> blue braille spinner
#   attention -> orange LED, pulsing
#   done      -> green LED
#   (no file) -> dim neutral LED
#
# NOTE: kitty caches this module; edits require a kitty restart (config
# reload does NOT re-import it). Every draw path falls back to the stock
# powerline renderer so a bug here can never blank the bar.

import os
import time

from kitty.boss import get_boss
from kitty.fast_data_types import add_timer
from kitty.tab_bar import (
    DrawData,
    ExtraData,
    TabBarData,
    as_rgb,
    draw_tab_with_powerline,
)
from kitty.utils import color_as_int

STATE_DIR = "/tmp/claude-kitty-status"

LED = {  # status -> LED color
    "neutral":   0x5A5A64,
    "working":   0x4F8EF7,
    "done":      0x4CC38A,
    "attention": 0xF0803C,
}
ATTN_DIM = 0x81421B          # attention LED, off-phase of the pulse
TEXT_DIM = 0x8B8B96          # inactive tab text
CHIP_BG = 0xD6D6DC           # active tab: reverse-video chip
CHIP_FG = 0x18181C
CORNER_FG = 0x6D6D78
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Status also tints the title text (LED alone was too subtle).
TEXT_TINT = {  # on dark bar (inactive tabs)
    "working":   0x7FA7F5,
    "done":      0x59C98F,
    "attention": 0xF0995C,
}
CHIP_TINT = {  # on the light active chip
    "working":   0x1D4ED8,
    "done":      0x15803D,
    "attention": 0x9A3412,
}

_timer = None
_statuses: dict = {}  # index -> state, rebuilt each draw pass for the minimap


def _redraw(timer_id=None) -> None:
    try:
        for tm in get_boss().all_tab_managers:
            tm.mark_tab_bar_dirty()
    except Exception:
        pass


REPO_HUE = {  # per-repo tab accent (left edge bar)
    "glow-platform": 0x5FE9DF,
    "glow-core": 0xFF5FA8,
    "glow-aws-sync": 0xFFB65C,
}
_hue_cache: dict = {}  # window id -> (monotonic ts, hue) — cwd lookups are not free


def _win_hue(w):
    e = _hue_cache.get(w.id)
    now = time.monotonic()
    if e and now - e[0] < 10:
        return e[1]
    hue = None
    try:
        cwd = w.cwd_of_child or ""
        for name, h in REPO_HUE.items():
            if name in cwd:
                hue = h
                break
    except Exception:
        pass
    _hue_cache[w.id] = (now, hue)
    return hue


def _tab_info(tab: TabBarData):
    """One boss pass -> (state, repo hue, context %)."""
    state, hue, ctx = "neutral", None, None
    try:
        tab_obj = get_boss().tab_for_id(tab.tab_id)
        pid = os.getpid()
        for w in tab_obj:
            if hue is None:
                hue = _win_hue(w)
            if ctx is None:
                try:
                    with open(f"{STATE_DIR}/ctx-{pid}-{w.id}") as f:
                        ctx = int(f.read().strip() or 0)
                except (OSError, ValueError):
                    pass
            try:
                with open(f"{STATE_DIR}/{pid}-{w.id}") as f:
                    s = f.read().strip()
            except OSError:
                continue
            if s == "attention":
                state = s
            elif s in ("done", "working") and state != "attention":
                state = s
        if tab.needs_attention:  # kitty's own bell flag
            state = "attention"
    except Exception:
        pass
    return state, hue, ctx


def _led(state: str, frame: int) -> tuple:
    if state == "working":
        return SPINNER[frame % len(SPINNER)], LED["working"]
    if state == "attention":
        return "●", (LED["attention"] if frame % 2 else ATTN_DIM)
    return "●", LED[state]


def _signal_tab(draw_data: DrawData, screen, tab: TabBarData, index: int,
                max_title_length: int, state: str, hue=None, ctx=None) -> int:
    frame = int(time.monotonic() * 2)
    bar_bg = as_rgb(color_as_int(draw_data.default_bg))
    glyph, glyph_color = _led(state, frame)

    title = tab.title
    budget = max(max_title_length - len(str(index)) - 6, 3)
    if len(title) > budget:
        title = title[: budget - 1] + "…"

    active = tab.is_active
    bg = as_rgb(CHIP_BG) if active else bar_bg
    tint = (CHIP_TINT if active else TEXT_TINT).get(state)
    if ctx is not None and ctx >= 85 and state != "attention":
        tint = 0xB45309 if active else 0xFFB65C  # context pressure: amber title
    fg = as_rgb(tint) if tint else (as_rgb(CHIP_FG) if active else as_rgb(TEXT_DIM))

    screen.cursor.bold = screen.cursor.italic = False
    screen.cursor.bg = bg
    if hue:
        screen.cursor.fg = as_rgb(hue)
        screen.draw("▎")
    else:
        screen.draw(" ")
    screen.cursor.fg = as_rgb(glyph_color)
    screen.draw(f"{glyph} ")
    pct = ""
    try:
        if state == "working" and tab.num_of_windows_with_progress > 0 and 0 < tab.total_progress < 100:
            pct = f" {tab.total_progress}%"
    except Exception:
        pct = ""

    screen.cursor.fg = fg
    screen.cursor.bold = active
    screen.draw(f"{index} {title}{pct} ")
    screen.cursor.bold = False
    screen.cursor.fg, screen.cursor.bg = 0, 0
    screen.draw(" ")
    return screen.cursor.x


def _right_status(draw_data: DrawData, screen) -> None:
    frame = int(time.monotonic() * 2)
    attn = sum(1 for s in _statuses.values() if s == "attention")
    clock = time.strftime("%H:%M")

    # (color, text) cells, minimap first
    cells = []
    for i in sorted(_statuses):
        s = _statuses[i]
        _, c = _led(s, frame)
        cells.append((c, "▮"))
    # prowler: patrols when the fleet is idle, points at alerts, sleeps when all done
    states = set(_statuses.values())
    if "attention" in states:
        cells.append((LED["attention"], "  ᓚᘏᗢ→"))
    elif "working" in states:
        cells.append((0x4A5578, "  ᓚᘏᗢ"))
    elif "done" in states:
        cells.append((0x3F5A4C, "  ᓚᘏᗢ zZ"))
    else:
        track = 8
        p = int(time.monotonic() * 1.5) % (2 * track)
        if p >= track:
            p = 2 * track - 1 - p
        cells.append((0x4A5578, " " * (p + 1) + "ᓚᘏᗢ" + " " * (track - p)))

    cells.append((CORNER_FG, "  "))
    if attn:
        cells.append((LED["attention"], f"● {attn} need you"))
        cells.append((CORNER_FG, " · "))
    cells.append((CORNER_FG, f"{clock} "))

    total = sum(len(t) for _, t in cells)
    free = screen.columns - screen.cursor.x - total
    if free < 0:
        return
    bar_bg = as_rgb(color_as_int(draw_data.default_bg))
    screen.cursor.fg, screen.cursor.bg = 0, 0
    screen.draw(" " * free)
    screen.cursor.bg = bar_bg
    for color, text in cells:
        screen.cursor.fg = as_rgb(color)
        screen.draw(text)


def draw_tab(draw_data: DrawData, screen, tab: TabBarData, before: int,
             max_title_length: int, index: int, is_last: bool,
             extra_data: ExtraData) -> int:
    global _timer
    if _timer is None:
        try:
            _timer = add_timer(_redraw, 0.5, True)
        except Exception:
            _timer = -1

    try:
        state, hue, ctx = _tab_info(tab)
        _statuses[index] = state
        end = _signal_tab(draw_data, screen, tab, index, max_title_length, state, hue, ctx)
    except Exception:
        end = draw_tab_with_powerline(
            draw_data, screen, tab, before, max_title_length, index, is_last, extra_data
        )
    if is_last:
        try:
            _right_status(draw_data, screen)
        except Exception:
            pass
        _statuses.clear()
    return end

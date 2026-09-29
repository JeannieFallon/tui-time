#!/usr/bin/env python3
"""Big-digit wall clock for an idle tmux pane. Run: python3 apps/ambient/clock/clock.py"""

import argparse
import math
import os
import random
import select
import signal
import sys
import time
from collections import namedtuple
from datetime import datetime

ENTER_ALT_SCREEN = "\033[?1049h"
LEAVE_ALT_SCREEN = "\033[?1049l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
HOME = "\033[H"
CLEAR = "\033[2J"
DEFAULT_FG = "\033[39m"

GAP = " "
BIG_FULL, BIG_SHORT, TEXT, BLANK = "big HH:MM:SS", "big HH:MM", "text", "blank"
DEFAULT_SIZE = (80, 24)

# Each glyph is a 10-row logical-pixel bitmap (twice the height that gets
# printed). Terminal cells are roughly twice as tall as wide, so packing
# two logical rows into one printed row (see pack_rows) undoes that and
# lets curved digits (0, 6, 8, 9) read as curved instead of blocky.
DIGIT_BITMAPS = {
    "0": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "1": (
        "  #  ",
        " ##  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        " ### ",
    ),
    "2": (
        " ### ",
        "#   #",
        "    #",
        "    #",
        "   # ",
        "  #  ",
        " #   ",
        "#    ",
        "#    ",
        "#####",
    ),
    "3": (
        " ### ",
        "#   #",
        "    #",
        "    #",
        "  ## ",
        "  ## ",
        "    #",
        "    #",
        "#   #",
        " ### ",
    ),
    "4": (
        "   # ",
        "  ## ",
        " # # ",
        "#  # ",
        "#  # ",
        "#####",
        "   # ",
        "   # ",
        "   # ",
        "   # ",
    ),
    "5": (
        "#####",
        "#    ",
        "#    ",
        "#    ",
        "#### ",
        "    #",
        "    #",
        "    #",
        "#   #",
        " ### ",
    ),
    "6": (
        " ### ",
        "#    ",
        "#    ",
        "#    ",
        "#### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "7": (
        "#####",
        "    #",
        "   # ",
        "   # ",
        "  #  ",
        "  #  ",
        " #   ",
        " #   ",
        " #   ",
        " #   ",
    ),
    "8": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "9": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        " ####",
        "    #",
        "    #",
        "    #",
        "    #",
        " ### ",
    ),
    ":": (
        "  ",
        "  ",
        "  ",
        "##",
        "##",
        "  ",
        "  ",
        "##",
        "##",
        "  ",
    ),
}


Caps = namedtuple("Caps", "color unicode")


def detect_caps():
    """Read terminal capabilities once, at startup."""
    return Caps(color=not os.environ.get("NO_COLOR"), unicode=unicode_ok())


def unicode_ok():
    """Whether stdout can encode every non-ASCII glyph: digits and effects."""
    glyphs = "█▀▄" + "".join(STAR_GLYPHS[True] + RAIN_GLYPHS[True])
    try:
        glyphs.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def pack_rows(rows):
    """Pack a 10-row logical bitmap into 5 printed rows via half-blocks."""
    packed = []
    for i in range(0, len(rows), 2):
        top, bottom = rows[i], rows[i + 1]
        line = []
        for t, b in zip(top, bottom):
            if t != " " and b != " ":
                line.append("█")  # full block
            elif t != " ":
                line.append("▀")  # upper half block
            elif b != " ":
                line.append("▄")  # lower half block
            else:
                line.append(" ")
        packed.append("".join(line))
    return tuple(packed)


BLOCK_GLYPHS = {ch: pack_rows(rows) for ch, rows in DIGIT_BITMAPS.items()}


def get_pane_size():
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return DEFAULT_SIZE


def big_text(time_str, caps):
    """Lines of time_str drawn in big digits."""
    glyphs = BLOCK_GLYPHS if caps.unicode else DIGIT_BITMAPS
    chars = [glyphs[ch] for ch in time_str]
    return [GAP.join(g[i] for g in chars) for i in range(len(chars[0]))]


def pick_tier(now, cols, rows, caps):
    """The largest size tier that fits the pane, and its lines of text.

    Tiers, largest first: big HH:MM:SS, big HH:MM, plain HH:MM:SS, blank.
    """
    for tier, lines in (
        (BIG_FULL, big_text(now.strftime("%H:%M:%S"), caps)),
        (BIG_SHORT, big_text(now.strftime("%H:%M"), caps)),
        (TEXT, [now.strftime("%H:%M:%S")]),
    ):
        if len(lines[0]) <= cols and len(lines) <= rows:
            return tier, lines
    return BLANK, []


def build_frame(now, cols, rows, theme, caps, effect_state=None):
    """One complete frame for the pane: cursor-home, then every cell.

    Pure: the time, pane size, theme, capabilities and effect state are all
    inputs. The effect shows only in the big HH:MM:SS tier, and never inside
    the digits' bounding box plus a 1-cell margin.
    """
    tier, lines = pick_tier(now, cols, rows, caps)
    effect = showing_effect(theme, tier, caps)
    t = now.timestamp()
    # Each cell is (character, 256-color index or None).
    cells = [[(" ", None)] * cols for _ in range(rows)]
    if not lines:
        return join_frame(cells, caps)

    top = (rows - len(lines)) // 2
    left = (cols - len(lines[0])) // 2
    bottom, right = top + len(lines) - 1, left + len(lines[0]) - 1

    if effect and effect.glyphs and effect_state is not None:
        for r, c, ch, color in effect.glyphs(effect_state, t, cols, rows, caps.unicode):
            in_margin = top - 1 <= r <= bottom + 1 and left - 1 <= c <= right + 1
            if 0 <= r < rows and 0 <= c < cols and not in_margin:
                cells[r][c] = (ch, color)

    for i, line in enumerate(lines):
        for j, ch in enumerate(line):
            if ch != " ":
                c = left + j
                color = effect.tint(t, c) if effect and effect.tint else theme.color
                cells[top + i][c] = (ch, color)
    return join_frame(cells, caps)


def showing_effect(theme, tier, caps):
    """The theme's effect if it shows at this tier, else None.

    Effects show only in the big HH:MM:SS tier. A color-only effect (one with
    no glyphs) doesn't show without color.
    """
    effect = theme.effect
    if effect is None or tier != BIG_FULL or not (effect.glyphs or caps.color):
        return None
    return effect


def join_frame(cells, caps):
    return HOME + "\r\n".join(paint(row, caps) for row in cells)


def paint(row, caps):
    """One row of cells as text, with foreground escapes only if color is on."""
    out = []
    current = None
    for ch, color in row:
        if caps.color and color != current:
            out.append(DEFAULT_FG if color is None else f"\033[38;5;{color}m")
            current = color
        out.append(ch)
    if current is not None:
        out.append(DEFAULT_FG)
    return "".join(out)


def frame_rate(now, cols, rows, theme, caps):
    """Frames per second: the theme's rate while its effect is showing, else 1."""
    tier, _ = pick_tier(now, cols, rows, caps)
    return theme.fps if showing_effect(theme, tier, caps) else 1


# An effect is the time-varying part of a theme, with three optional parts:
# seed(cols, rows, rng) returns its state as plain data; glyphs(state, t,
# cols, rows, unicode) yields (row, col, char, color) to draw around the
# digits; tint(t, col) returns the color of a digit cell.
Effect = namedtuple("Effect", "seed glyphs tint")

# night: sparse stars that fade in and out, each reappearing somewhere new.
# Tuning constants, chosen by eye.
STAR_CELLS = 60  # one star per this many cells
STAR_PERIOD = (4.0, 11.0)  # seconds per fade-in, fade-out and rest
STAR_LIT = 0.6  # fraction of each period a star is visible
STAR_GLYPHS = {True: ("·", "✦"), False: (".", "+", "*")}  # dim to bright
STAR_COLORS = range(236, 256)  # grayscale ramp, dim to bright
Star = namedtuple("Star", "salt period phase")


def seed_stars(cols, rows, rng):
    count = max(1, cols * rows // STAR_CELLS)
    return [
        Star(rng.getrandbits(32), rng.uniform(*STAR_PERIOD), rng.random())
        for _ in range(count)
    ]


def star_glyphs(stars, t, cols, rows, unicode):
    glyphs = STAR_GLYPHS[unicode]
    for star in stars:
        cycle, phase = divmod(t / star.period + star.phase, 1)
        if phase >= STAR_LIT:
            continue
        brightness = math.sin(math.pi * phase / STAR_LIT)
        # A prime multiplier keeps (salt, cycle) pairs from colliding, so each
        # star gets its own sequence of places.
        place = random.Random(star.salt * 1_000_003 + int(cycle))
        row, col = place.randrange(rows), place.randrange(cols)
        yield (
            row,
            col,
            glyphs[min(len(glyphs) - 1, int(brightness * len(glyphs)))],
            STAR_COLORS[min(len(STAR_COLORS) - 1, int(brightness * len(STAR_COLORS)))],
        )


# rain: drops falling slowly down some columns, each column with its own
# speed, length and gap between drops. Tuning constants, chosen by eye.
RAIN_COLUMNS = 0.3  # fraction of columns with rain
RAIN_SPEED = (2.0, 6.0)  # rows a second
RAIN_LENGTH = (2, 6)  # rows, including the leading glyph
RAIN_GAP = (0.5, 2.0)  # rows between drops, as a multiple of pane height
RAIN_GLYPHS = {True: ("│", "╎", "·"), False: ("|", ":", ".")}  # lead to tail
RAIN_COLORS = (153, 110, 67, 60)  # lead to tail
Drop = namedtuple("Drop", "speed length span offset")


def seed_rain(cols, rows, rng):
    """One Drop, or None, per column."""
    columns = []
    for _ in range(cols):
        if rng.random() >= RAIN_COLUMNS:
            columns.append(None)
            continue
        length = rng.randint(*RAIN_LENGTH)
        span = rows + length + round(rows * rng.uniform(*RAIN_GAP))
        columns.append(Drop(rng.uniform(*RAIN_SPEED), length, span, rng.uniform(0, span)))
    return columns


def rain_glyphs(columns, t, cols, rows, unicode):
    glyphs = RAIN_GLYPHS[unicode]
    for col, drop in enumerate(columns):
        if drop is None:
            continue
        lead = int((drop.offset + t * drop.speed) % drop.span)
        for k in range(drop.length):
            shade = k / drop.length
            yield (
                lead - k,
                col,
                glyphs[int(shade * len(glyphs))],
                RAIN_COLORS[int(shade * len(RAIN_COLORS))],
            )


# wave: a color gradient moving horizontally across the digits. It draws no
# glyphs of its own. Tuning constants, chosen by eye.
WAVE_COLORS = (51, 45, 39, 33, 63, 99, 135, 171, 207, 171, 135, 99, 63, 33, 39, 45)
WAVE_WIDTH = 3  # columns per color
WAVE_SPEED = 6.0  # columns a second, left to right


def wave_tint(t, col):
    return WAVE_COLORS[int((col - t * WAVE_SPEED) // WAVE_WIDTH) % len(WAVE_COLORS)]


# A theme bundles a palette (color: the 256-color index for the digits, or
# None for the terminal default, plus whatever colors its effect uses), an
# optional effect, and a frame rate. Themes only ever set the foreground.
Theme = namedtuple("Theme", "name color effect fps")

PLAIN = Theme("plain", color=None, effect=None, fps=1)
NIGHT = Theme("night", color=153, effect=Effect(seed_stars, star_glyphs, None), fps=4)
RAIN = Theme("rain", color=110, effect=Effect(seed_rain, rain_glyphs, None), fps=8)
WAVE = Theme("wave", color=45, effect=Effect(None, None, wave_tint), fps=8)
THEMES = {t.name: t for t in (PLAIN, NIGHT, RAIN, WAVE)}


def seed_effect(theme, cols, rows, rng):
    """Fresh effect state for a pane of this size, or None if there's none."""
    if theme.effect is None or theme.effect.seed is None:
        return None
    return theme.effect.seed(cols, rows, rng)


def parse_args(argv):
    """The theme selected on the command line."""
    parser = argparse.ArgumentParser(
        description="Big-digit wall clock for an idle pane.",
    )
    parser.add_argument(
        "--theme",
        choices=list(THEMES),
        default=PLAIN.name,
        help="palette and effect (default: %(default)s)",
    )
    return THEMES[parser.parse_args(argv).theme]


def next_boundary(now, fps):
    """The first frame boundary strictly after now, at fps frames a second.

    Boundaries are k / fps, so with an integer fps every whole second is one.
    """
    k = math.floor(now * fps) + 1
    while k / fps <= now:
        k += 1
    return k / fps


def wait_until(deadline, wake_fd):
    """Sleep until deadline, or until a resize arrives."""
    while not resized:
        timeout = deadline - time.time()
        if timeout <= 0:
            return
        ready, _, _ = select.select([wake_fd], [], [], timeout)
        if ready:
            try:
                os.read(wake_fd, 4096)
            except BlockingIOError:
                pass


def write_out(text):
    """Write text to stdout in one write, bypassing Python's buffering."""
    data = text.encode(sys.stdout.encoding or "utf-8")
    while data:
        data = data[os.write(1, data) :]


def teardown(caps):
    reset = DEFAULT_FG if caps.color else ""
    try:
        write_out(reset + SHOW_CURSOR + LEAVE_ALT_SCREEN)
    except OSError:
        pass


resized = False


def handle_signal(signum, frame):
    sys.exit(0)


def handle_winch(signum, frame):
    global resized
    resized = True


def main():
    global resized
    theme = parse_args(sys.argv[1:])
    if not sys.stdout.isatty():
        print(time.strftime("%H:%M:%S"))
        return

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)
    signal.signal(signal.SIGWINCH, handle_winch)
    wake_fd, wake_write_fd = os.pipe()
    os.set_blocking(wake_fd, False)
    os.set_blocking(wake_write_fd, False)
    signal.set_wakeup_fd(wake_write_fd)

    caps = detect_caps()
    rng = random.Random()
    seeded_size = None
    try:
        write_out(ENTER_ALT_SCREEN + HIDE_CURSOR)
        while True:
            # Take the flag before reading the size, so a resize that lands
            # mid-frame is still seen, and cleared for, next time round.
            was_resized, resized = resized, False
            now = time.time()
            cols, rows = get_pane_size()
            if was_resized or (cols, rows) != seeded_size:
                effect_state = seed_effect(theme, cols, rows, rng)
                seeded_size = (cols, rows)
            local = datetime.fromtimestamp(now)
            frame = build_frame(local, cols, rows, theme, caps, effect_state)
            if was_resized:
                frame = CLEAR + frame
            try:
                write_out(frame)
            except OSError:
                return  # the pty is gone
            fps = frame_rate(local, cols, rows, theme, caps)
            wait_until(next_boundary(now, fps), wake_fd)
    finally:
        teardown(caps)


if __name__ == "__main__":
    main()

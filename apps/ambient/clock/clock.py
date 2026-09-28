#!/usr/bin/env python3
"""Big-digit wall clock for an idle tmux pane. Run: python3 apps/clock/clock.py"""

import os
import signal
import sys
import time

ENTER_ALT_SCREEN = "\033[?1049h"
LEAVE_ALT_SCREEN = "\033[?1049l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

GAP = " "
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


def unicode_ok():
    try:
        "█▀▄".encode(sys.stdout.encoding or "ascii")
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


if unicode_ok():
    GLYPHS = {ch: pack_rows(rows) for ch, rows in DIGIT_BITMAPS.items()}
else:
    GLYPHS = DIGIT_BITMAPS

GLYPH_HEIGHT = len(next(iter(GLYPHS.values())))


def get_pane_size():
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return DEFAULT_SIZE


def render_frame(time_str, cols, rows):
    glyphs = [GLYPHS[ch] for ch in time_str]
    total_w = sum(len(g[0]) for g in glyphs) + (len(glyphs) - 1)
    row_offset = max(0, (rows - GLYPH_HEIGHT) // 2)
    col_offset = max(0, (cols - total_w) // 2)

    lines = []
    for i in range(GLYPH_HEIGHT):
        row_text = GAP.join(g[i] for g in glyphs)
        lines.append(f"\033[{row_offset + 1 + i};{col_offset + 1}H{row_text}")
    return "".join(lines)


def teardown():
    try:
        os.write(1, (SHOW_CURSOR + LEAVE_ALT_SCREEN).encode())
    except OSError:
        pass


def handle_signal(signum, frame):
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)

    sys.stdout.write(ENTER_ALT_SCREEN)
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()

    try:
        while True:
            now = time.strftime("%H:%M:%S")
            cols, rows = get_pane_size()
            sys.stdout.write(render_frame(now, cols, rows))
            sys.stdout.flush()
            time.sleep(1)
    finally:
        teardown()


if __name__ == "__main__":
    main()

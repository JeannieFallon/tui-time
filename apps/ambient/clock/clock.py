#!/usr/bin/env python3
"""Big-digit wall clock for an idle tmux pane. Run: python3 apps/ambient/clock/clock.py"""

import os
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


Caps = namedtuple("Caps", "color unicode")


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


def build_frame(now, cols, rows, caps):
    """One complete frame for the pane: cursor-home, then every cell."""
    lines = big_text(now.strftime("%H:%M:%S"), caps)
    top = max(0, (rows - len(lines)) // 2)
    left = max(0, (cols - len(lines[0])) // 2)

    cells = [[" "] * cols for _ in range(rows)]
    for i, line in enumerate(lines):
        for j, ch in enumerate(line):
            if top + i < rows and left + j < cols:
                cells[top + i][left + j] = ch
    return HOME + "\r\n".join("".join(row) for row in cells)


def teardown():
    try:
        os.write(1, (SHOW_CURSOR + LEAVE_ALT_SCREEN).encode())
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
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)
    signal.signal(signal.SIGWINCH, handle_winch)

    caps = Caps(color=True, unicode=unicode_ok())
    sys.stdout.write(ENTER_ALT_SCREEN)
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()

    try:
        while True:
            cols, rows = get_pane_size()
            frame = build_frame(datetime.now(), cols, rows, caps)
            if resized:
                resized = False
                frame = CLEAR + frame
            sys.stdout.write(frame)
            sys.stdout.flush()
            time.sleep(1)
    finally:
        teardown()


if __name__ == "__main__":
    main()

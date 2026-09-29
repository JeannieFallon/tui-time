#!/usr/bin/env python3
"""Big-digit wall clock for an idle tmux pane. Run: python3 apps/ambient/clock/clock.py"""

import math
import os
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


def build_frame(now, cols, rows, caps):
    """One complete frame for the pane: cursor-home, then every cell."""
    _, lines = pick_tier(now, cols, rows, caps)
    cells = [[" "] * cols for _ in range(rows)]
    if lines:
        top = (rows - len(lines)) // 2
        left = (cols - len(lines[0])) // 2
        for i, line in enumerate(lines):
            cells[top + i][left : left + len(line)] = line
    return HOME + "\r\n".join("".join(row) for row in cells)


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
    sys.stdout.write(ENTER_ALT_SCREEN)
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()

    try:
        fps = 1
        while True:
            now = time.time()
            cols, rows = get_pane_size()
            frame = build_frame(datetime.fromtimestamp(now), cols, rows, caps)
            if resized:
                resized = False
                frame = CLEAR + frame
            sys.stdout.write(frame)
            sys.stdout.flush()
            wait_until(next_boundary(now, fps), wake_fd)
    finally:
        teardown()


if __name__ == "__main__":
    main()

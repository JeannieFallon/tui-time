"""Tests for clock.py. Run: python3 -m unittest apps/ambient/clock/test_clock.py"""

import os
import re
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clock  # noqa: E402

CSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")
SGR = re.compile(r"\033\[[0-9;]*m")

NOON = datetime(2026, 9, 29, 12, 34, 56)
# Its first and last digits (2 and 0, or 8 for HH:MM) are inked edge to edge,
# so the drawn bounding box is the full tier width.
EDGE_TO_EDGE = datetime(2026, 9, 29, 20, 8, 0)
UNICODE = clock.Caps(color=True, unicode=True)
ASCII = clock.Caps(color=True, unicode=False)


def grid(frame):
    """Strip escape codes and return the frame as a list of rows."""
    assert frame.startswith("\033[H"), "frame must start with cursor-home"
    return CSI.sub("", frame).split("\r\n")


class FrameBuildingTest(unittest.TestCase):
    def test_frame_covers_every_cell_of_the_pane(self):
        for cols, rows in [(80, 24), (120, 40), (41, 5), (30, 7), (10, 3), (1, 1)]:
            with self.subTest(cols=cols, rows=rows):
                cells = grid(clock.build_frame(NOON, cols, rows, caps=UNICODE))
                self.assertEqual(len(cells), rows)
                for line in cells:
                    self.assertEqual(len(line), cols)

    def test_ascii_frame_is_pure_ascii(self):
        frame = clock.build_frame(NOON, 80, 24, caps=ASCII)
        self.assertTrue(frame.isascii())
        self.assertIn("#", frame)


def drawn_box(cells):
    """(width, height) of the bounding box of non-blank cells."""
    points = [(r, c) for r, line in enumerate(cells) for c, ch in enumerate(line) if ch != " "]
    if not points:
        return (0, 0)
    rs = [r for r, _ in points]
    cs = [c for _, c in points]
    return (max(cs) - min(cs) + 1, max(rs) - min(rs) + 1)


# Drawn size of each tier. Big digits are 5 wide, colons 2, with 1-cell gaps;
# block glyphs are 5 rows tall, ASCII glyphs 10.
BIG_FULL = {True: (41, 5), False: (41, 10)}
BIG_SHORT = {True: (26, 5), False: (26, 10)}
TEXT = (8, 1)
BLANK = (0, 0)


class SizeTierTest(unittest.TestCase):
    def assertTier(self, caps, cols, rows, expected):
        cells = grid(clock.build_frame(EDGE_TO_EDGE, cols, rows, caps=caps))
        self.assertEqual(drawn_box(cells), expected)
        if expected == TEXT:
            self.assertIn("20:08:00", "".join(cells))
        return cells

    def test_largest_tier_that_fits_is_drawn(self):
        cases = [
            (UNICODE, 41, 5, BIG_FULL[True]),
            (UNICODE, 40, 5, BIG_SHORT[True]),
            (UNICODE, 41, 4, TEXT),
            (UNICODE, 26, 5, BIG_SHORT[True]),
            (UNICODE, 25, 5, TEXT),
            (UNICODE, 8, 1, TEXT),
            (UNICODE, 7, 1, BLANK),
            (UNICODE, 8, 0, BLANK),
            (ASCII, 41, 10, BIG_FULL[False]),
            (ASCII, 40, 10, BIG_SHORT[False]),
            (ASCII, 41, 9, TEXT),
            (ASCII, 26, 10, BIG_SHORT[False]),
            (ASCII, 25, 10, TEXT),
        ]
        for caps, cols, rows, expected in cases:
            with self.subTest(unicode=caps.unicode, cols=cols, rows=rows):
                self.assertTier(caps, cols, rows, expected)

    def test_no_tier_is_ever_clipped(self):
        for caps in (UNICODE, ASCII):
            whole = {BIG_FULL[caps.unicode], BIG_SHORT[caps.unicode], TEXT, BLANK}
            for cols in range(1, 50):
                for rows in range(1, 13):
                    with self.subTest(unicode=caps.unicode, cols=cols, rows=rows):
                        cells = grid(clock.build_frame(EDGE_TO_EDGE, cols, rows, caps=caps))
                        self.assertIn(drawn_box(cells), whole)

    def test_blank_tier_is_a_full_padded_frame(self):
        cells = self.assertTier(UNICODE, 7, 3, BLANK)
        self.assertEqual(cells, [" " * 7] * 3)


class FrameTimingTest(unittest.TestCase):
    EPOCH = 1790000000.0  # a whole second

    def test_boundary_is_in_the_future_and_within_one_period(self):
        for fps in (1, 4, 8, 12):
            period = 1 / fps
            for offset in (0.0, 1e-9, 0.1, 0.25, 0.4999, 0.5, 0.75, 0.999999):
                now = self.EPOCH + offset
                with self.subTest(fps=fps, now=now):
                    boundary = clock.next_boundary(now, fps)
                    self.assertGreater(boundary, now)
                    self.assertLessEqual(boundary - now, period + 1e-9)

    def test_boundaries_fall_on_every_whole_second(self):
        for fps in (1, 4, 12):
            with self.subTest(fps=fps):
                t = self.EPOCH - 0.001
                seen = []
                while t < self.EPOCH + 3:
                    t = clock.next_boundary(t, fps)
                    seen.append(t)
                for second in (1, 2, 3):
                    self.assertIn(self.EPOCH + second, seen)
                self.assertEqual(len(seen), 3 * fps + 1)


if __name__ == "__main__":
    unittest.main()

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

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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_grid.py -- grid.py 单元测试"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.grid import Grid, from_spec


class TestGrid(unittest.TestCase):
    def test_track_width_1920(self):
        g = Grid(width=1920, margin_left=144, margin_right=144, col_gap=24)
        # (1920-288-11*24)/12 = 1368/12
        self.assertAlmostEqual(g.track_w, 114.0)

    def test_cell_full_width(self):
        g = Grid(width=1920, margin_left=144, margin_right=144, col_gap=24)
        c = g.col_range(1, 12)
        self.assertAlmostEqual(c["x"], 144.0)
        self.assertAlmostEqual(c["x"] + c["w"], 1920 - 144)

    def test_cell_split(self):
        g = Grid()
        left = g.col_range(1, 5)
        right = g.col_range(6, 12)
        # 左右无缝衔接（含 gap）
        self.assertAlmostEqual(left["x"] + left["w"] + 24, right["x"])

    def test_cell_xy(self):
        g = Grid(width=1280, height=720, margin_left=96, margin_right=96,
                 margin_top=64, margin_bottom=64, col_gap=24, row_gap=24)
        c = g.cell(0, 0, 6, 6)
        self.assertAlmostEqual(c["x"], 96.0)
        self.assertAlmostEqual(c["y"], 64.0)
        self.assertGreater(c["w"], 0)
        self.assertGreater(c["h"], 0)

    def test_out_of_bounds(self):
        g = Grid()
        with self.assertRaises(ValueError):
            g.cell(12, 0)
        with self.assertRaises(ValueError):
            g.cell(10, 0, 3, 1)

    def test_from_spec(self):
        g = from_spec(1920, 1080, 144)
        self.assertEqual(g.width, 1920)
        self.assertEqual(g.margin_left, 144)
        c = g.col_range(1, 12)
        self.assertAlmostEqual(c["x"] + c["w"], 1920 - 144)


if __name__ == "__main__":
    unittest.main()

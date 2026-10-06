#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_grid.py -- grid.py 单元测试"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.grid import Grid, from_spec, from_spec_file, main


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

    def test_from_spec_file(self):
        with tempfile.TemporaryDirectory() as td:
            spec_file = Path(td) / "spec_lock.md"
            spec_file.write_text(
                "## canvas\n- viewBox: 0 0 1280 720\n- margin: 60px\n",
                encoding="utf-8",
            )
            g = from_spec_file(spec_file)
            self.assertEqual(g.width, 1280)
            self.assertEqual(g.height, 720)
            self.assertEqual(g.margin_left, 60)

    def test_from_spec_file_relative_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            spec_file = base / "spec_lock.md"
            spec_file.write_text(
                "## canvas\n- viewBox: 0 0 1920 1080\n- margin: 144px\n",
                encoding="utf-8",
            )
            g = from_spec_file("spec_lock.md", base_dir=base)
            self.assertEqual(g.width, 1920)
            self.assertEqual(g.margin_left, 144)

    def test_from_spec_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            from_spec_file("non_existent_spec_lock.md")

    def test_from_spec_file_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            spec_file = Path(td) / "invalid.md"
            spec_file.write_text("no canvas\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                from_spec_file(spec_file)


class TestGridMain(unittest.TestCase):
    def test_main_default(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([])
        self.assertEqual(rc, 0)
        self.assertIn("Grid: 1920x1080, 12 cols x 12 rows", buf.getvalue())

    def test_main_track_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--track", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["width"], 1920)
        self.assertIn("track_w", data)
        self.assertIn("track_h", data)

    def test_main_cell(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--col", "0", "--row", "0", "--col-span", "6", "--row-span", "6", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("cell", data)
        self.assertEqual(data["cell"]["col"], 0)
        self.assertEqual(data["cell"]["col_span"], 6)

    def test_main_col_range(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--col-range", "1-5", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("col_range", data)
        self.assertEqual(data["col_range"]["start"], 1)
        self.assertEqual(data["col_range"]["end"], 5)

    def test_main_spec(self):
        with tempfile.TemporaryDirectory() as td:
            spec_file = Path(td) / "spec_lock.md"
            spec_file.write_text(
                "## canvas\n- viewBox: 0 0 1280 720\n- margin: 60px\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--spec", str(spec_file), "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["width"], 1280)
            self.assertEqual(data["height"], 720)

    def test_main_spec_relative_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            spec_file = base / "spec_lock.md"
            spec_file.write_text(
                "## canvas\n- viewBox: 0 0 1280 720\n- margin: 60px\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--spec", "spec_lock.md", "--base-dir", str(base), "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["width"], 1280)
            self.assertEqual(data["height"], 720)

    def test_main_invalid_col_range(self):
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = main(["--col-range", "invalid"])
        self.assertEqual(rc, 2)

    def test_main_out_of_bounds_cell(self):
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = main(["--col", "15", "--row", "0"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

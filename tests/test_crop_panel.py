#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_crop_panel.py
========================
测试 crop_panel.py 的宽高比解析、主体包围盒计算、画幅裁切与 CLI 流程。
使用临时目录与标准库 unittest，不引入额外外部依赖。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 确保能加载项目内 .venv site-packages 中的 numpy 与 PIL
for site_pkg in REPO_ROOT.glob(".venv/lib/python*/site-packages"):
    if site_pkg.is_dir() and str(site_pkg) not in sys.path:
        sys.path.insert(0, str(site_pkg))

import numpy as np
from PIL import Image

from scripts.crop_panel import (
    parse_aspect,
    bbox_of,
    cover,
    calculate_crop,
    crop_image,
    main,
)


def create_test_image(
    path: Path,
    width: int = 400,
    height: int = 300,
    bright_box: tuple[int, int, int, int] | None = None,
) -> None:
    """创建一个黑底测试图片，并在指定区域填充高亮像素。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    if bright_box:
        x, y, w, h = bright_box
        arr[y : y + h, x : x + w] = 220
    im = Image.fromarray(arr, "RGB")
    im.save(path)


class TestParseAspect(unittest.TestCase):
    def test_colon_ratio(self):
        self.assertAlmostEqual(parse_aspect("16:9"), 16.0 / 9.0)
        self.assertAlmostEqual(parse_aspect("580:385"), 580.0 / 385.0)

    def test_slash_ratio(self):
        self.assertAlmostEqual(parse_aspect("16/9"), 16.0 / 9.0)
        self.assertAlmostEqual(parse_aspect("4/3"), 4.0 / 3.0)

    def test_float_string_and_number(self):
        self.assertAlmostEqual(parse_aspect("1.5"), 1.5)
        self.assertAlmostEqual(parse_aspect(1.777), 1.777)

    def test_invalid_aspect(self):
        with self.assertRaises(ValueError):
            parse_aspect("")
        with self.assertRaises(ValueError):
            parse_aspect("invalid")
        with self.assertRaises(ValueError):
            parse_aspect("-1:2")
        with self.assertRaises(ValueError):
            parse_aspect("16:0")
        with self.assertRaises(ValueError):
            parse_aspect(-0.5)


class TestBboxAndCover(unittest.TestCase):
    def test_empty_image_returns_none(self):
        arr = np.zeros((100, 100, 3), dtype=np.float64)
        self.assertIsNone(bbox_of(arr))

    def test_sparse_noise_returns_none(self):
        arr = np.zeros((100, 100, 3), dtype=np.float64)
        arr[10:15, 10:15] = 255  # 25 个像素，少于阈值 50
        self.assertIsNone(bbox_of(arr))

    def test_bright_box_detection(self):
        arr = np.zeros((200, 200, 3), dtype=np.float64)
        arr[50:150, 60:140] = 200  # 100x80 = 8000 个高亮像素
        bb = bbox_of(arr)
        self.assertIsNotNone(bb)
        x0, y0, x1, y1 = bb
        self.assertTrue(55 <= x0 <= 65)
        self.assertTrue(135 <= x1 <= 145)
        self.assertTrue(45 <= y0 <= 55)
        self.assertTrue(145 <= y1 <= 155)

    def test_cover_calculation(self):
        arr = np.zeros((100, 100, 3), dtype=np.float64)
        arr[20:80, 20:80] = 200  # 60x60
        cov_full = cover(arr, (20, 20, 60, 60))
        self.assertAlmostEqual(cov_full, 100.0)
        cov_zero = cover(arr, (0, 0, 10, 10))
        self.assertAlmostEqual(cov_zero, 0.0)


class TestCalculateCrop(unittest.TestCase):
    def test_aspect_ratio_preservation(self):
        w, h = 1000, 800
        bbox = (300.0, 200.0, 500.0, 400.0)  # 200x200
        tgt_aspect = 16.0 / 9.0
        left, top, bw, bh = calculate_crop(w, h, bbox, tgt_aspect, pad=1.0)
        self.assertAlmostEqual(bw / bh, tgt_aspect, places=4)
        self.assertGreaterEqual(left, 0.0)
        self.assertGreaterEqual(top, 0.0)
        self.assertLessEqual(left + bw, float(w))
        self.assertLessEqual(top + bh, float(h))

    def test_aspect_ratio_preservation_when_exceeding_canvas(self):
        w, h = 600, 400
        bbox = (50.0, 50.0, 550.0, 350.0)  # 500x300
        tgt_aspect = 2.0  # 宽长型
        left, top, bw, bh = calculate_crop(w, h, bbox, tgt_aspect, pad=1.2)
        self.assertAlmostEqual(bw / bh, tgt_aspect, places=4)
        self.assertLessEqual(bw, float(w))
        self.assertLessEqual(bh, float(h))


class TestCropImage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            crop_image(self.tmp_path / "not_found.png")

    def test_no_subject_raises_value_error(self):
        img_path = self.tmp_path / "dark.png"
        create_test_image(img_path, 200, 200)
        with self.assertRaises(ValueError):
            crop_image(img_path)

    def test_dry_run_does_not_save(self):
        img_path = self.tmp_path / "test.png"
        create_test_image(img_path, 400, 300, (100, 100, 100, 80))
        out_path = self.tmp_path / "out.png"
        res = crop_image(img_path, out_path, aspect="16:9", apply=False)
        self.assertFalse(out_path.exists())
        self.assertFalse(res["applied"])
        self.assertAlmostEqual(res["target_aspect"], 16.0 / 9.0)

    def test_apply_saves_cropped_file(self):
        img_path = self.tmp_path / "test.png"
        create_test_image(img_path, 400, 300, (100, 100, 100, 80))
        out_path = self.tmp_path / "out.png"
        res = crop_image(img_path, out_path, aspect="4:3", apply=True)
        self.assertTrue(out_path.exists())
        self.assertTrue(res["applied"])
        with Image.open(out_path) as saved:
            self.assertAlmostEqual(saved.width / saved.height, 4.0 / 3.0, delta=0.05)


class TestCropPanelCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_missing_file_returns_1(self):
        ret = main([str(self.tmp_path / "missing.png")])
        self.assertEqual(ret, 1)

    def test_cli_space_separated_arguments(self):
        img_path = self.tmp_path / "sample.png"
        create_test_image(img_path, 600, 400, (200, 150, 150, 100))
        out_path = self.tmp_path / "sample_cropped.png"

        ret = main([
            str(img_path),
            "--aspect", "16:9",
            "--pad", "1.15",
            "--out", str(out_path),
            "--apply",
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(out_path.exists())

    def test_cli_equals_arguments(self):
        img_path = self.tmp_path / "sample2.png"
        create_test_image(img_path, 600, 400, (200, 150, 150, 100))
        out_path = self.tmp_path / "sample2_cropped.png"

        ret = main([
            str(img_path),
            "--aspect=580:385",
            "--pad=1.10",
            f"--out={out_path}",
            "--apply",
        ])
        self.assertEqual(ret, 0)
        self.assertTrue(out_path.exists())

    def test_cli_dark_image_returns_1(self):
        img_path = self.tmp_path / "dark.png"
        create_test_image(img_path, 400, 300)
        ret = main([str(img_path)])
        self.assertEqual(ret, 1)


if __name__ == "__main__":
    unittest.main()

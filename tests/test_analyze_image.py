#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_analyze_image.py
===========================
测试 analyze_image.py 的清晰度、主体清晰度、墨迹分布、报告提取、目标路径解析与 CLI 流程。
使用临时目录与标准库 unittest，不引入额外外部依赖。
"""

import io
import json
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

from scripts.analyze_image import (
    _lap_var,
    laplacian_variance,
    subject_sharp,
    ink_map,
    report,
    resolve_image_targets,
    main,
)


def create_test_image(
    path: Path,
    width: int = 120,
    height: int = 120,
    bg_val: int = 0,
    box: tuple[int, int, int, int] | None = None,
    box_val: int = 220,
) -> None:
    """创建合成测试图像。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.full((height, width, 3), bg_val, dtype=np.uint8)
    if box:
        x, y, w, h = box
        arr[y : y + h, x : x + w] = box_val
    im = Image.fromarray(arr, "RGB")
    im.save(path)


class TestImageMetrics(unittest.TestCase):
    def test_lap_var_flat_and_small(self):
        # 纯平图像方差为 0
        flat = np.full((50, 50), 100.0, dtype=np.float64)
        self.assertEqual(_lap_var(flat), 0.0)

        # 尺寸太小的图像返回 0.0
        tiny = np.full((2, 2), 100.0, dtype=np.float64)
        self.assertEqual(_lap_var(tiny), 0.0)

    def test_laplacian_variance_sharp(self):
        im_flat = Image.new("RGB", (60, 60), (10, 10, 10))
        self.assertEqual(laplacian_variance(im_flat), 0.0)

        # 创建交替黑白线条，方差应远大于 0
        arr = np.zeros((60, 60, 3), dtype=np.uint8)
        arr[:, ::2] = 255
        im_sharp = Image.fromarray(arr, "RGB")
        self.assertGreater(laplacian_variance(im_sharp), 100.0)

    def test_subject_sharp(self):
        # 亮像素极少 (< 50) 时返回 0.0
        arr = np.zeros((100, 100, 3), dtype=np.uint8)
        arr[10:15, 10:15] = 255  # 25 个像素
        im_sparse = Image.fromarray(arr, "RGB")
        self.assertEqual(subject_sharp(im_sparse), 0.0)

        # 主体区域有强烈对比和线条
        arr2 = np.zeros((120, 120, 3), dtype=np.uint8)
        arr2[40:80, 40:80:2] = 250  # 40x20 = 800 个亮像素且带条纹
        im_subject = Image.fromarray(arr2, "RGB")
        self.assertGreater(subject_sharp(im_subject), 50.0)

    def test_ink_map_distribution(self):
        # 中心九宫格 (第 1 行第 1 列，从 0 开始计数) 放置高亮
        arr = np.zeros((90, 90, 3), dtype=np.uint8)
        arr[30:60, 30:60] = 220
        im = Image.fromarray(arr, "RGB")

        m = ink_map(im)
        self.assertEqual(m.shape, (3, 3))
        self.assertAlmostEqual(float(m.sum()), 1.0, places=4)
        # 中心格应占据绝大部分墨量
        self.assertGreater(m[1, 1], 0.8)

    def test_ink_map_tiny_image(self):
        tiny = Image.new("RGB", (2, 2), (200, 200, 200))
        m = ink_map(tiny)
        self.assertEqual(m.shape, (3, 3))
        self.assertFalse(np.isnan(m).any())
        self.assertAlmostEqual(float(m.sum()), 1.0, places=4)

    def test_ink_map_zero_image(self):
        zero_im = Image.new("RGB", (0, 0), (0, 0, 0))
        m = ink_map(zero_im)
        self.assertEqual(m.shape, (3, 3))
        self.assertEqual(float(m.sum()), 0.0)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img_path = self.dir_path / "sample.png"
        create_test_image(self.img_path, width=90, height=90, box=(30, 30, 30, 30), box_val=240)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_report_success(self):
        rep = report(self.img_path)
        self.assertEqual(rep["name"], "sample.png")
        self.assertEqual(rep["size"], "90x90")
        self.assertEqual(rep["width"], 90)
        self.assertEqual(rep["height"], 90)
        self.assertIn("sharp", rep)
        self.assertIn("ssharp", rep)
        self.assertIn("mean", rep)
        self.assertIn("p99", rep)
        self.assertIn("ink", rep)
        self.assertIn("seam", rep)
        self.assertEqual(rep["colhead"], "左  中  右")
        self.assertGreater(rep["p99"], 100.0)

    def test_report_missing_file_raises_not_found(self):
        with self.assertRaises(FileNotFoundError):
            report(self.dir_path / "not_found.png")


class TestResolveImageTargets(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_single_file(self):
        p = self.dir_path / "a.png"
        create_test_image(p)
        res = resolve_image_targets([str(p)])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].resolve(), p.resolve())

    def test_resolve_directory_filtering_backups(self):
        p1 = self.dir_path / "normal1.png"
        p2 = self.dir_path / "normal2.png"
        p_pre = self.dir_path / "_pre_normal1.png"
        p_raw = self.dir_path / "_raw_normal2.png"
        for f in (p1, p2, p_pre, p_raw):
            create_test_image(f)

        res = resolve_image_targets(str(self.dir_path))
        names = [f.name for f in res]
        self.assertIn("normal1.png", names)
        self.assertIn("normal2.png", names)
        self.assertNotIn("_pre_normal1.png", names)
        self.assertNotIn("_raw_normal2.png", names)

    def test_resolve_project_root_with_images_subdir(self):
        proj = self.dir_path / "proj"
        img_dir = proj / "images"
        create_test_image(img_dir / "cover.png")
        create_test_image(img_dir / "detail.png")

        res = resolve_image_targets(proj)
        self.assertEqual(len(res), 2)
        names = [f.name for f in res]
        self.assertIn("cover.png", names)
        self.assertIn("detail.png", names)

    def test_resolve_non_existent_path(self):
        with self.assertRaises(FileNotFoundError):
            resolve_image_targets([self.dir_path / "missing"])

    def test_resolve_empty_dir_raises_value_error(self):
        empty_dir = self.dir_path / "empty_dir"
        empty_dir.mkdir()
        with self.assertRaises(ValueError):
            resolve_image_targets([str(empty_dir)])


class TestAnalyzeImageCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img1 = self.dir_path / "img1.png"
        self.img2 = self.dir_path / "img2.png"
        create_test_image(self.img1, 90, 90, box=(30, 30, 30, 30), box_val=220)
        create_test_image(self.img2, 90, 90, box=(10, 10, 40, 40), box_val=200)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_missing_file_returns_1(self):
        ret = main([str(self.dir_path / "not_existing.png")])
        self.assertEqual(ret, 1)

    def test_cli_single_and_multiple_files(self):
        ret = main([str(self.img1)])
        self.assertEqual(ret, 0)

        ret2 = main([str(self.img1), str(self.img2)])
        self.assertEqual(ret2, 0)

    def test_cli_directory_argument(self):
        ret = main([str(self.dir_path)])
        self.assertEqual(ret, 0)

    def test_cli_json_output(self):
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            ret = main([str(self.img1), "--json"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(ret, 0)
        parsed = json.loads(output)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "img1.png")
        self.assertIsInstance(parsed[0]["ink"], list)
        self.assertEqual(len(parsed[0]["ink"]), 3)

    def test_cli_check_flag(self):
        # 正常图像应通过 check
        ret_ok = main([str(self.img1), "--check"])
        self.assertEqual(ret_ok, 0)

        # 纯黑图像主体锐为 0，应被 check 拦下
        dark_img = self.dir_path / "dark.png"
        create_test_image(dark_img, 90, 90, bg_val=0)
        ret_fail = main([str(dark_img), "--check"])
        self.assertEqual(ret_fail, 1)


if __name__ == "__main__":
    unittest.main()

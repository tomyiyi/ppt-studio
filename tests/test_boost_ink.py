#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_boost_ink.py
=======================
测试 boost_ink.py 的黑点保持增益算法、透明通道保持、指标计算、目标路径解析、文件备份与 CLI 流程。
"""

import os
import shutil
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

from scripts.boost_ink import (
    metrics,
    boost_image,
    boost_file,
    resolve_image_targets,
    main,
    TARGET,
    BLACK_PCT,
    TOP_PCT,
)


def create_test_image(
    path: Path,
    width: int = 100,
    height: int = 100,
    mode: str = "RGB",
    bg_val: int = 10,
    stroke_val: int = 100,
    stroke_box: tuple[int, int, int, int] | None = (30, 30, 40, 40),
) -> None:
    """创建合成暗底测试图像。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "RGB":
        arr = np.full((height, width, 3), bg_val, dtype=np.uint8)
        if stroke_box:
            x, y, w, h = stroke_box
            arr[y : y + h, x : x + w] = stroke_val
        im = Image.fromarray(arr, "RGB")
    elif mode == "RGBA":
        arr = np.full((height, width, 4), [bg_val, bg_val, bg_val, 255], dtype=np.uint8)
        if stroke_box:
            x, y, w, h = stroke_box
            arr[y : y + h, x : x + w] = [stroke_val, stroke_val, stroke_val, 180]
        im = Image.fromarray(arr, "RGBA")
    elif mode == "LA":
        arr = np.full((height, width, 2), [bg_val, 255], dtype=np.uint8)
        if stroke_box:
            x, y, w, h = stroke_box
            arr[y : y + h, x : x + w] = [stroke_val, 180]
        im = Image.fromarray(arr, "LA")
    elif mode == "L":
        arr = np.full((height, width), bg_val, dtype=np.uint8)
        if stroke_box:
            x, y, w, h = stroke_box
            arr[y : y + h, x : x + w] = stroke_val
        im = Image.fromarray(arr, "L")
    else:
        raise ValueError(f"不支持的测试模式: {mode}")

    im.save(path)


class TestMetrics(unittest.TestCase):
    def test_empty_array(self):
        m = metrics(np.array([], dtype=np.float64))
        self.assertEqual(m["max"], 0.0)
        self.assertEqual(m["p999"], 0.0)
        self.assertEqual(m["ink60"], 0.0)

    def test_uniform_array(self):
        a = np.full((50, 50), 120.0, dtype=np.float64)
        m = metrics(a)
        self.assertEqual(m["max"], 120.0)
        self.assertEqual(m["p99"], 120.0)
        self.assertEqual(m["ink60"], 100.0)
        self.assertEqual(m["gt150"], 0.0)


class TestBoostImage(unittest.TestCase):
    def test_boost_stroke_preserves_black(self):
        # 100x100 图像，背景 10，中心 40x40 笔画 100
        arr = np.full((100, 100, 3), 10, dtype=np.uint8)
        arr[30:70, 30:70] = 100
        im = Image.fromarray(arr, "RGB")

        boosted, gain, before, after, skip = boost_image(
            im, target=200.0, black_pct=5.0, top_pct=99.0
        )
        self.assertIsNone(skip)
        self.assertGreater(gain, 1.0)
        self.assertEqual(before["max"], 100.0)

        boosted_arr = np.asarray(boosted)
        # 背景像素 (0, 0) 应严格保持原黑点 10
        self.assertEqual(int(boosted_arr[0, 0, 0]), 10)
        # 笔画中心像素应提亮接近 200
        self.assertGreater(int(boosted_arr[50, 50, 0]), 180)

    def test_rgba_preserves_alpha(self):
        arr = np.full((100, 100, 4), [10, 10, 10, 200], dtype=np.uint8)
        arr[30:70, 30:70] = [100, 100, 100, 150]
        im = Image.fromarray(arr, "RGBA")

        boosted, gain, before, after, skip = boost_image(im, target=220.0)
        self.assertIsNone(skip)
        self.assertEqual(boosted.mode, "RGBA")

        boosted_arr = np.asarray(boosted)
        self.assertEqual(int(boosted_arr[0, 0, 3]), 200)
        self.assertEqual(int(boosted_arr[50, 50, 3]), 150)

    def test_la_preserves_alpha(self):
        arr = np.full((100, 100, 2), [10, 210], dtype=np.uint8)
        arr[30:70, 30:70] = [100, 120]
        im = Image.fromarray(arr, "LA")

        boosted, gain, before, after, skip = boost_image(im, target=220.0)
        self.assertIsNone(skip)
        self.assertEqual(boosted.mode, "LA")

        boosted_arr = np.asarray(boosted)
        self.assertEqual(int(boosted_arr[0, 0, 1]), 210)
        self.assertEqual(int(boosted_arr[50, 50, 1]), 120)

    def test_no_highlight_skipped(self):
        # 纯黑图像
        im = Image.new("RGB", (100, 100), (0, 0, 0))
        boosted, gain, before, after, skip = boost_image(im, target=230.0)
        self.assertEqual(skip, "无高光")
        self.assertEqual(gain, 1.0)

    def test_target_lower_than_black_skipped(self):
        # 背景 100，高光 200，但目标只有 80 (小于黑点)
        arr = np.full((100, 100, 3), 100, dtype=np.uint8)
        arr[30:70, 30:70] = 200
        im = Image.fromarray(arr, "RGB")
        boosted, gain, before, after, skip = boost_image(im, target=80.0)
        self.assertEqual(skip, "目标低于底色")
        self.assertEqual(gain, 1.0)

    def test_invalid_parameters_raise_value_error(self):
        im = Image.new("RGB", (10, 10), (10, 10, 10))
        with self.assertRaises(ValueError):
            boost_image(im, target=0.0)
        with self.assertRaises(ValueError):
            boost_image(im, target=300.0)
        with self.assertRaises(ValueError):
            boost_image(im, black_pct=-1.0)
        with self.assertRaises(ValueError):
            boost_image(im, black_pct=99.0, top_pct=95.0)
        with self.assertRaises(ValueError):
            boost_image(im, top_pct=101.0)


class TestResolveImageTargets(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_single_file(self):
        f = self.dir_path / "sample.png"
        create_test_image(f)
        targets = resolve_image_targets(str(f))
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].resolve(), f.resolve())

    def test_resolve_directory_with_pngs(self):
        f1 = self.dir_path / "img1.png"
        f2 = self.dir_path / "img2.png"
        f_pre = self.dir_path / "_pre_img1.png"
        f_raw = self.dir_path / "_raw_img2.png"
        for p in (f1, f2, f_pre, f_raw):
            create_test_image(p)

        targets = resolve_image_targets(str(self.dir_path))
        target_names = [p.name for p in targets]
        self.assertIn("img1.png", target_names)
        self.assertIn("img2.png", target_names)
        self.assertNotIn("_pre_img1.png", target_names)
        self.assertNotIn("_raw_img2.png", target_names)

    def test_resolve_project_root_with_images_subdir(self):
        proj = self.dir_path / "my_project"
        img_dir = proj / "images"
        create_test_image(img_dir / "cover.png")
        create_test_image(img_dir / "bus.png")

        targets = resolve_image_targets(str(proj))
        self.assertEqual(len(targets), 2)
        names = [p.name for p in targets]
        self.assertIn("cover.png", names)
        self.assertIn("bus.png", names)

    def test_resolve_non_existent_path(self):
        with self.assertRaises(FileNotFoundError):
            resolve_image_targets(str(self.dir_path / "non_existent"))

    def test_resolve_empty_dir_raises_value_error(self):
        empty_dir = self.dir_path / "empty"
        empty_dir.mkdir()
        with self.assertRaises(ValueError):
            resolve_image_targets(str(empty_dir))


class TestBoostFileAndCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.test_img = self.dir_path / "test.png"
        create_test_image(self.test_img, bg_val=10, stroke_val=100)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_boost_file_dry_run_does_not_modify_disk(self):
        mtime_before = self.test_img.stat().st_mtime
        res = boost_file(self.test_img, target=220.0, apply=False)
        self.assertFalse(res["applied"])
        self.assertIsNone(res["backup_path"])
        self.assertFalse((self.dir_path / "_pre_test.png").exists())
        self.assertEqual(self.test_img.stat().st_mtime, mtime_before)

    def test_boost_file_apply_creates_backup_and_modifies_disk(self):
        res = boost_file(self.test_img, target=220.0, apply=True, backup=True)
        self.assertTrue(res["applied"])
        bak_file = self.dir_path / "_pre_test.png"
        self.assertTrue(bak_file.exists())

        # 验证备份内容为原始图像
        orig_im = Image.open(bak_file)
        self.assertEqual(int(np.asarray(orig_im).max()), 100)

        # 验证修改后文件已被拉亮
        new_im = Image.open(self.test_img)
        self.assertGreater(int(np.asarray(new_im).max()), 180)

    def test_cli_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_invalid_path(self):
        code = main([str(self.dir_path / "no_such_file")])
        self.assertEqual(code, 1)

    def test_cli_dry_run_and_apply(self):
        # 预演
        code = main([str(self.dir_path), "--target", "200.0"])
        self.assertEqual(code, 0)
        self.assertFalse((self.dir_path / "_pre_test.png").exists())

        # 写盘
        code = main([str(self.dir_path), "--target", "210.0", "--black-pct", "4.0", "--apply"])
        self.assertEqual(code, 0)
        self.assertTrue((self.dir_path / "_pre_test.png").exists())


if __name__ == "__main__":
    unittest.main()

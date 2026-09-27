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
    crop_panel,
    resolve_crop_targets,
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

    def test_crop_image_check_passed(self):
        img_path = self.tmp_path / "test_check.png"
        create_test_image(img_path, 400, 300, (100, 100, 100, 80))
        res = crop_image(img_path, check=True, min_ink=3.0)
        self.assertTrue(res["check_passed"])
        self.assertEqual(len(res["issues"]), 0)

    def test_crop_image_check_failed_raises_value_error(self):
        sparse = self.tmp_path / "sparse.png"
        arr = np.zeros((400, 500, 3), dtype=np.uint8)
        arr[100:104, 100:104] = 220
        arr[100:104, 396:400] = 220
        arr[296:300, 100:104] = 220
        arr[296:300, 396:400] = 220
        Image.fromarray(arr, "RGB").save(sparse)

        with self.assertRaises(ValueError) as ctx:
            crop_image(sparse, check=True, min_ink=3.0)
        self.assertIn("门禁未通过", str(ctx.exception))

    def test_crop_image_custom_min_ink(self):
        img_path = self.tmp_path / "mid.png"
        create_test_image(img_path, 400, 300, (100, 100, 60, 50))
        # 当阈值要求极高（如 90%）时应判定不达标
        res = crop_image(img_path, check=False, min_ink=90.0)
        self.assertFalse(res["check_passed"])
        self.assertIn("主体墨量不足", res["issues"][0])


class TestCropPanelBatch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_crop_panel_batch_dry_run(self):
        img1 = self.tmp_path / "i1.png"
        img2 = self.tmp_path / "i2.png"
        create_test_image(img1, 400, 300, (80, 80, 120, 90))
        create_test_image(img2, 400, 300, (100, 100, 100, 80))

        results = crop_panel([img1, img2], apply=False)
        self.assertEqual(len(results), 2)
        self.assertFalse((self.tmp_path / "i1_panel.png").exists())
        self.assertFalse((self.tmp_path / "i2_panel.png").exists())

    def test_crop_panel_batch_apply_with_out_dir(self):
        img1 = self.tmp_path / "i1.png"
        img2 = self.tmp_path / "i2.png"
        create_test_image(img1, 400, 300, (80, 80, 120, 90))
        create_test_image(img2, 400, 300, (100, 100, 100, 80))

        out_dir = self.tmp_path / "panels"
        results = crop_panel([img1, img2], out_dir=out_dir, apply=True, check=True)
        self.assertEqual(len(results), 2)
        self.assertTrue((out_dir / "i1_panel.png").exists())
        self.assertTrue((out_dir / "i2_panel.png").exists())

    def test_crop_panel_check_failure_raises(self):
        sparse = self.tmp_path / "sparse.png"
        arr = np.zeros((400, 500, 3), dtype=np.uint8)
        arr[100:104, 100:104] = 220
        arr[100:104, 396:400] = 220
        arr[296:300, 100:104] = 220
        arr[296:300, 396:400] = 220
        Image.fromarray(arr, "RGB").save(sparse)

        with self.assertRaises(ValueError) as ctx:
            crop_panel([sparse], check=True, min_ink=3.0)
        self.assertIn("裁切客观质量门禁未通过", str(ctx.exception))


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

    def test_cli_multiple_images_batch(self):
        img1 = self.tmp_path / "img1.png"
        img2 = self.tmp_path / "img2.png"
        create_test_image(img1, 500, 400, (100, 100, 150, 100))
        create_test_image(img2, 500, 400, (120, 120, 150, 100))

        ret = main([str(img1), str(img2), "--apply"])
        self.assertEqual(ret, 0)
        self.assertTrue((self.tmp_path / "img1_panel.png").exists())
        self.assertTrue((self.tmp_path / "img2_panel.png").exists())

    def test_cli_multiple_images_with_out_returns_1(self):
        img1 = self.tmp_path / "img1.png"
        img2 = self.tmp_path / "img2.png"
        create_test_image(img1, 500, 400, (100, 100, 150, 100))
        create_test_image(img2, 500, 400, (120, 120, 150, 100))

        ret = main([str(img1), str(img2), "--out", str(self.tmp_path / "clash.png")])
        self.assertEqual(ret, 1)

    def test_cli_check_flag(self):
        good = self.tmp_path / "good.png"
        create_test_image(good, 500, 400, (100, 100, 200, 150))
        ret = main([str(good), "--check"])
        self.assertEqual(ret, 0)

        # 构造一个包围盒很大但内部极度稀疏、墨量 < 3.0% 的图片
        sparse = self.tmp_path / "sparse.png"
        arr = np.zeros((400, 500, 3), dtype=np.uint8)
        # 在 300x200 矩形四个角散落共 60 个点（> 50 触发有效 bbox）
        arr[100:104, 100:104] = 220
        arr[100:104, 396:400] = 220
        arr[296:300, 100:104] = 220
        arr[296:300, 396:400] = 220
        Image.fromarray(arr, "RGB").save(sparse)
        ret_sparse = main([str(sparse), "--check"])
        self.assertEqual(ret_sparse, 1)

    def test_cli_min_ink_custom_thresholds(self):
        good = self.tmp_path / "good.png"
        create_test_image(good, 500, 400, (100, 100, 200, 150))
        # 极高阈值 95% 应返回 1 (失败)
        ret_fail = main([str(good), "--check", "--min-ink", "95.0"])
        self.assertEqual(ret_fail, 1)

        # 稀疏图在极低阈值 0.05% 时应能通过
        sparse = self.tmp_path / "sparse_pass.png"
        arr = np.zeros((400, 500, 3), dtype=np.uint8)
        arr[100:104, 100:104] = 220
        arr[100:104, 396:400] = 220
        arr[296:300, 100:104] = 220
        arr[296:300, 396:400] = 220
        Image.fromarray(arr, "RGB").save(sparse)
        ret_pass = main([str(sparse), "--check", "--min-ink=0.05"])
        self.assertEqual(ret_pass, 0)


class TestResolveCropTargets(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_direct_file(self):
        img = self.tmp_path / "test.png"
        create_test_image(img, 200, 200, (20, 20, 50, 50))
        targets = resolve_crop_targets(img)
        self.assertEqual(targets, [img.resolve()])

    def test_directory_targets(self):
        img_dir = self.tmp_path / "images"
        create_test_image(img_dir / "a.png", 200, 200, (20, 20, 50, 50))
        create_test_image(img_dir / "b.png", 200, 200, (20, 20, 50, 50))
        create_test_image(img_dir / "b_panel.png", 200, 200, (20, 20, 50, 50))
        create_test_image(img_dir / "_raw_c.png", 200, 200, (20, 20, 50, 50))

        targets = resolve_crop_targets(self.tmp_path)
        names = [p.name for p in targets]
        self.assertIn("a.png", names)
        self.assertIn("b.png", names)
        self.assertNotIn("b_panel.png", names)
        self.assertNotIn("_raw_c.png", names)

    def test_nonexistent_target_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            resolve_crop_targets(self.tmp_path / "no_such_file.png")

    def test_ambiguous_project_target_raises_value_error(self):
        fake_repo = self.tmp_path / "mock_repo"
        fake_projects = fake_repo / "projects"
        p1 = fake_projects / "proj1" / "images"
        p2 = fake_projects / "proj2" / "images"
        create_test_image(p1 / "dup.png", 100, 100, (10, 10, 20, 20))
        create_test_image(p2 / "dup.png", 100, 100, (10, 10, 20, 20))

        base_dir = self.tmp_path / "work"
        base_dir.mkdir(parents=True, exist_ok=True)

        with self.assertRaises(ValueError) as ctx:
            resolve_crop_targets("dup.png", base_dir=base_dir, repo_root_override=fake_repo)
        self.assertIn("多个项目", str(ctx.exception))

    def test_single_project_bare_name_discovery(self):
        # 验证在当前 repo_root 下查找已有图片 heal_bg.png 能成功定位到 agentflow-os-launch/images/heal_bg.png
        targets = resolve_crop_targets("heal_bg.png")
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].name, "heal_bg.png")


if __name__ == "__main__":
    unittest.main()

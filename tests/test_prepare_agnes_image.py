#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prepare_agnes_image.py
=================================
测试 prepare_agnes_image.py 的接缝检测、平滑对齐、尺寸裁切、亮度调整与 CLI 异常处理。
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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

from scripts.prepare_agnes_image import (
    parse_size,
    detect_seam,
    fix_seam,
    prepare,
    resolve_image_targets,
    resolve_manifest_target,
    parse_postprocess_cmd,
    check_images,
    main,
)


def create_test_image(
    path: Path,
    width: int = 100,
    height: int = 80,
    mode: str = "RGB",
    left_val: int = 20,
    right_val: int = 60,
    seam_x: int | None = None,
) -> None:
    """创建合成图像，可指定竖向接缝位置及两侧亮度。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "RGB":
        arr = np.full((height, width, 3), left_val, dtype=np.uint8)
        if seam_x is not None and 0 < seam_x < width:
            arr[:, seam_x:] = right_val
        im = Image.fromarray(arr, "RGB")
    elif mode == "RGBA":
        arr = np.full((height, width, 4), [left_val, left_val, left_val, 255], dtype=np.uint8)
        if seam_x is not None and 0 < seam_x < width:
            arr[:, seam_x:, :3] = right_val
        im = Image.fromarray(arr, "RGBA")
    elif mode == "L":
        arr = np.full((height, width), left_val, dtype=np.uint8)
        if seam_x is not None and 0 < seam_x < width:
            arr[:, seam_x:] = right_val
        im = Image.fromarray(arr, "L")
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    im.save(path, "PNG")


class TestParseSize(unittest.TestCase):
    def test_valid_sizes(self):
        self.assertEqual(parse_size("2560x1440"), (2560, 1440))
        self.assertEqual(parse_size("1920X1080"), (1920, 1080))
        self.assertEqual(parse_size(" 1280 x 720 "), (1280, 720))

    def test_invalid_formats(self):
        invalid_inputs = [
            "2560",
            "2560_1440",
            "100x200x300",
            "axb",
            "100x",
            "x100",
            "-10x100",
            "100x-50",
            "0x100",
            "100x0",
        ]
        for val in invalid_inputs:
            with self.subTest(val=val):
                with self.assertRaises(ValueError):
                    parse_size(val)


class TestDetectSeam(unittest.TestCase):
    def test_uniform_image_has_no_seam(self):
        arr = np.full((80, 100, 3), 30, dtype=np.uint8)
        im = Image.fromarray(arr, "RGB")
        self.assertIsNone(detect_seam(im))

    def test_narrow_image_returns_none(self):
        arr = np.full((50, 30, 3), 30, dtype=np.uint8)
        im = Image.fromarray(arr, "RGB")
        self.assertIsNone(detect_seam(im))

    def test_detect_significant_vertical_seam(self):
        # 宽 100 高 80，在 x=50 处存在由 20 到 60 的竖向突变台阶
        arr = np.full((80, 100, 3), 20, dtype=np.uint8)
        arr[:, 50:] = 60
        im = Image.fromarray(arr, "RGB")
        col = detect_seam(im)
        self.assertIsNotNone(col)
        self.assertIn(col, (49, 50, 51))

    def test_weak_step_ignored(self):
        # 突变幅度 2.0 < min_step(6.0)
        arr = np.full((80, 100, 3), 20, dtype=np.uint8)
        arr[:, 50:] = 22
        im = Image.fromarray(arr, "RGB")
        self.assertIsNone(detect_seam(im))


class TestFixSeam(unittest.TestCase):
    def test_fix_seam_rgb(self):
        arr = np.full((50, 100, 3), 20, dtype=np.uint8)
        arr[:, 50:] = 60
        im = Image.fromarray(arr, "RGB")
        fixed = fix_seam(im, 50)
        fixed_arr = np.asarray(fixed)
        # 修复后，左侧与右侧均值应基本对齐
        left_m = fixed_arr[:, :50].mean()
        right_m = fixed_arr[:, 50:].mean()
        self.assertAlmostEqual(left_m, right_m, delta=1.0)

    def test_fix_seam_grayscale(self):
        arr = np.full((50, 100), 20, dtype=np.uint8)
        arr[:, 50:] = 60
        im = Image.fromarray(arr, "L")
        fixed = fix_seam(im, 50)
        fixed_arr = np.asarray(fixed)
        left_m = fixed_arr[:, :50].mean()
        right_m = fixed_arr[:, 50:].mean()
        self.assertAlmostEqual(left_m, right_m, delta=1.0)

    def test_fix_seam_rgba_preserves_alpha(self):
        arr = np.full((50, 100, 4), [20, 20, 20, 200], dtype=np.uint8)
        arr[:, 50:, :3] = 60
        im = Image.fromarray(arr, "RGBA")
        fixed = fix_seam(im, 50)
        fixed_arr = np.asarray(fixed)
        self.assertEqual(fixed_arr.shape[2], 4)
        # alpha 通道应保持 200 不变
        self.assertEqual(fixed_arr[:, :, 3].min(), 200)
        self.assertEqual(fixed_arr[:, :, 3].max(), 200)

    def test_fix_seam_out_of_bounds_clip(self):
        arr = np.full((50, 100, 3), 20, dtype=np.uint8)
        im = Image.fromarray(arr, "RGB")
        # 不会因超界报错，会被 clip
        fixed = fix_seam(im, -10)
        self.assertEqual(fixed.size, (100, 50))
        fixed2 = fix_seam(im, 200)
        self.assertEqual(fixed2.size, (100, 50))


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.raw_path = self.dir_path / "raw.png"
        self.out_path = self.dir_path / "out.png"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_raw_file_raises_not_found(self):
        with self.assertRaises(FileNotFoundError):
            prepare(self.dir_path / "not_found.png", self.out_path)

    def test_invalid_size_raises_value_error(self):
        create_test_image(self.raw_path)
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, size=(0, 100))
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, size=(-10, 100))

    def test_invalid_brightness_raises_value_error(self):
        create_test_image(self.raw_path)
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, brightness=-0.5)

    def test_normal_resize_and_crop(self):
        # 尺寸 200x120 -> 目标 160x90
        create_test_image(self.raw_path, width=200, height=120)
        rep = prepare(self.raw_path, self.out_path, size=(160, 90), brightness=1.0, seam="off")
        self.assertTrue(self.out_path.exists())
        self.assertEqual(rep["src"], "200x120")
        self.assertEqual(rep["out"], "160x90")
        self.assertFalse(rep["fixed"])
        with Image.open(self.out_path) as out_im:
            self.assertEqual(out_im.size, (160, 90))

    def test_auto_seam_detection_and_fix(self):
        # 制作含接缝的图片 (x=60)
        create_test_image(self.raw_path, width=120, height=80, left_val=20, right_val=60, seam_x=60)
        rep = prepare(self.raw_path, self.out_path, size=(120, 80), seam="auto")
        self.assertTrue(rep["fixed"])
        self.assertIsNotNone(rep["seam"])

    def test_manual_seam_columns(self):
        create_test_image(self.raw_path, width=120, height=80, left_val=20, right_val=60)
        # 单列
        rep1 = prepare(self.raw_path, self.out_path, size=(120, 80), seam="50")
        self.assertTrue(rep1["fixed"])
        self.assertEqual(rep1["seam"], 50)

        # 多列
        rep2 = prepare(self.raw_path, self.out_path, size=(120, 80), seam="40, 70")
        self.assertTrue(rep2["fixed"])
        self.assertEqual(rep2["seam"], [40, 70])

    def test_invalid_seam_specification(self):
        create_test_image(self.raw_path, width=100, height=60)
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, seam="invalid_col")
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, seam="999")  # 999 >= width=100

    def test_brightness_adjustment(self):
        create_test_image(self.raw_path, width=100, height=60, left_val=50, right_val=50)
        prepare(self.raw_path, self.out_path, size=(100, 60), brightness=1.5, seam="off")
        with Image.open(self.out_path) as im_bright:
            mean_bright = np.asarray(im_bright).mean()

        out_dark = self.dir_path / "dark.png"
        prepare(self.raw_path, out_dark, size=(100, 60), brightness=0.5, seam="off")
        with Image.open(out_dark) as im_dark:
            mean_dark = np.asarray(im_dark).mean()

        self.assertGreater(mean_bright, mean_dark)


class TestMainCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.raw_path = self.dir_path / "raw.png"
        self.out_path = self.dir_path / "out.png"
        create_test_image(self.raw_path, width=120, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_success(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), str(self.out_path), "--size", "100x60"])
        self.assertEqual(ret, 0)
        self.assertTrue(self.out_path.exists())
        self.assertIn("120x80 → 100x60", buf.getvalue())

    def test_cli_missing_raw_file(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            ret = main([str(self.dir_path / "no_such.png"), str(self.out_path)])
        self.assertEqual(ret, 1)
        self.assertIn("源图片文件不存在", buf.getvalue())

    def test_cli_invalid_size(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            ret = main([str(self.raw_path), str(self.out_path), "--size", "invalid_size"])
        self.assertEqual(ret, 1)
        self.assertIn("尺寸格式无效", buf.getvalue())

    def test_cli_invalid_brightness(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            ret = main([str(self.raw_path), str(self.out_path), "--brightness", "-1"])
        self.assertEqual(ret, 1)
        self.assertIn("亮度系数必须 >= 0", buf.getvalue())

    def test_cli_invalid_seam(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            ret = main([str(self.raw_path), str(self.out_path), "--seam", "bad_col"])
        self.assertEqual(ret, 1)
        self.assertIn("无效的接缝列号", buf.getvalue())

    def test_cli_help(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()):
                main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_single_raw_dry_run(self):
        buf = io.StringIO()
        orig_mtime = self.raw_path.stat().st_mtime
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--size", "100x60"])
        self.assertEqual(ret, 0)
        self.assertIn("[预演]", buf.getvalue())
        self.assertIn("加 --apply 执行写盘", buf.getvalue())
        # 文件未被修改
        self.assertEqual(self.raw_path.stat().st_mtime, orig_mtime)

    def test_cli_single_raw_apply_with_backup(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--apply", "--size", "100x60"])
        self.assertEqual(ret, 0)
        self.assertIn("(已写盘)", buf.getvalue())
        # 验证备份存在
        bak = self.raw_path.parent / f"_pre_{self.raw_path.name}"
        self.assertTrue(bak.exists())
        with Image.open(self.raw_path) as im:
            self.assertEqual(im.size, (100, 60))

    def test_cli_single_raw_apply_no_backup(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--apply", "--no-backup", "--size", "90x50"])
        self.assertEqual(ret, 0)
        with Image.open(self.raw_path) as im:
            self.assertEqual(im.size, (90, 50))

    def test_cli_check_success(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--check"])
        self.assertEqual(ret, 0)
        self.assertIn("ALL CLEAR ✅", buf.getvalue())

    def test_cli_check_failure_on_seam(self):
        seam_img = self.dir_path / "seam_img.png"
        create_test_image(seam_img, width=120, height=80, left_val=20, right_val=60, seam_x=60)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(seam_img), "--check"])
        self.assertEqual(ret, 1)
        self.assertIn("门禁未通过", buf.getvalue())
        self.assertIn("seam_img.png", buf.getvalue())

    def test_cli_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--json"])
        self.assertEqual(ret, 0)
        import json
        out_data = json.loads(buf.getvalue().strip())
        self.assertIsInstance(out_data, list)
        self.assertEqual(out_data[0]["name"], self.raw_path.name)


class TestTargetResolutionAndManifest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img_dir = self.dir_path / "images"
        self.img_dir.mkdir(parents=True)
        self.p1 = self.img_dir / "p1.png"
        self.p2 = self.img_dir / "p2.png"
        create_test_image(self.p1, width=120, height=80)
        create_test_image(self.p2, width=120, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_image_targets_directory(self):
        targets = resolve_image_targets(self.dir_path)
        self.assertEqual(len(targets), 2)
        self.assertEqual([t.name for t in targets], ["p1.png", "p2.png"])

    def test_resolve_image_targets_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            resolve_image_targets(self.dir_path / "not_exist")

    def test_parse_postprocess_cmd(self):
        cmd = "prepare_agnes_image.py --size 1308x736 --brightness 0.88 --seam auto"
        cfg = parse_postprocess_cmd(cmd)
        self.assertEqual(cfg["size"], (1308, 736))
        self.assertEqual(cfg["brightness"], 0.88)
        self.assertEqual(cfg["seam"], "auto")

    def test_resolve_manifest_target_and_execution(self):
        manifest_path = self.img_dir / "image_prompts.json"
        import json
        manifest_data = {
            "project": "test-proj",
            "items": [
                {
                    "filename": "p1.png",
                    "postprocess": "prepare_agnes_image.py --size 100x50 --brightness 0.9 --seam auto",
                },
                {
                    "filename": "p2.png",
                    "postprocess": "prepare_agnes_image.py --size 120x60 --brightness 1.1 --seam auto",
                },
            ],
        }
        manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False), encoding="utf-8")

        resolved_mf = resolve_manifest_target(self.dir_path)
        self.assertEqual(resolved_mf.resolve(), manifest_path.resolve())

        # 运行 CLI manifest 预演
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(["--manifest", str(manifest_path)])
        self.assertEqual(ret, 0)
        self.assertIn("100x50", buf.getvalue())
        self.assertIn("120x60", buf.getvalue())

        # 运行 CLI manifest --apply
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            ret2 = main(["--manifest", str(manifest_path), "--apply"])
        self.assertEqual(ret2, 0)
        with Image.open(self.p1) as im1:
            self.assertEqual(im1.size, (100, 50))
        with Image.open(self.p2) as im2:
            self.assertEqual(im2.size, (120, 60))


class TestCheckImagesGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.clean_img = self.dir_path / "clean.png"
        create_test_image(self.clean_img, width=120, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_check_images_clean(self):
        res = check_images([self.clean_img], size=(120, 80), verbose=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 1)
        self.assertEqual(len(res["failed_seams"]), 0)

    def test_check_images_detects_seam(self):
        seam_img = self.dir_path / "seam.png"
        create_test_image(seam_img, width=120, height=80, left_val=20, right_val=60, seam_x=60)
        res = check_images([seam_img], verbose=False)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["failed_seams"]), 1)

    def test_check_images_detects_dimension_mismatch(self):
        res = check_images([self.clean_img], size=(200, 100), verbose=False)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["dimension_mismatches"]), 1)


if __name__ == "__main__":
    unittest.main()

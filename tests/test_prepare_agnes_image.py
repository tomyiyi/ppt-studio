#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prepare_agnes_image.py
=================================
测试 prepare_agnes_image.py 的接缝检测、平滑对齐、尺寸裁切、亮度调整与 CLI 异常处理。
"""

import io
import json
import os
import shutil
import subprocess
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

PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
if not PYTHON_BIN.exists():
    PYTHON_BIN = Path(sys.executable)
SCRIPT_PATH = REPO_ROOT / "scripts" / "prepare_agnes_image.py"

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
    run_qa_prepared_images,
    qa_prepared_images,
    qa_single_prepared_image,
    run_qa_single_prepared_image,
    prepare_agnes_images,
    prepare_images,
    BatchResult,
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
        self.assertIsInstance(out_data, dict)
        self.assertEqual(out_data["total"], 1)
        self.assertEqual(out_data["success_count"], 1)
        self.assertEqual(out_data["failure_count"], 0)
        self.assertFalse(out_data["partial_success"])
        self.assertEqual(out_data["failures"], [])
        self.assertEqual(out_data["items"][0]["name"], self.raw_path.name)


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

    def test_check_images_flexible_inputs(self):
        # 单个 Path
        res_path = check_images(self.clean_img, size=(120, 80), verbose=False)
        self.assertTrue(res_path["ok"])

        # 字符串形式路径
        res_str = check_images(str(self.clean_img), size=(120, 80), verbose=False)
        self.assertTrue(res_str["ok"])

        # 目录路径
        res_dir = check_images(self.dir_path, size=(120, 80), verbose=False)
        self.assertTrue(res_dir["ok"])

        # 缺失或非法目标（优雅失败）
        res_missing = check_images(self.dir_path / "not_existing.png", verbose=False)
        self.assertFalse(res_missing["ok"])
        self.assertTrue(len(res_missing["unreadable"]) > 0)

    def test_run_qa_prepared_images_and_aliases(self):
        self.assertTrue(run_qa_prepared_images(self.clean_img, size=(120, 80), verbose=False))
        self.assertFalse(run_qa_prepared_images(self.clean_img, size=(999, 999), verbose=False))

        # 别名验证
        self.assertIs(qa_prepared_images, run_qa_prepared_images)
        self.assertIs(qa_single_prepared_image, check_images)
        self.assertIs(run_qa_single_prepared_image, check_images)

    def test_cli_quiet_and_verbose_flags(self):
        # --quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code_q = main([str(self.clean_img), "--check", "--quiet"])
        self.assertEqual(code_q, 0)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

        # --verbose
        buf_v = io.StringIO()
        with redirect_stdout(buf_v):
            code_v = main([str(self.clean_img), "--check", "--verbose"])
        self.assertEqual(code_v, 0)
        self.assertIn("[门禁] ✓ 配图客观后处理门禁通过", buf_v.getvalue())


class TestPrepareAgnesImagesAPI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img1 = self.dir_path / "img1.png"
        self.img2 = self.dir_path / "img2.png"
        create_test_image(self.img1, width=100, height=80)
        create_test_image(self.img2, width=100, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prepare_agnes_images_dry_run(self):
        reports = prepare_agnes_images(self.dir_path, size=(60, 40), apply=False)
        self.assertTrue(reports["ok"])
        self.assertEqual(reports["total"], 2)
        self.assertEqual(reports["success_count"], 2)
        self.assertEqual(reports["failure_count"], 0)
        self.assertFalse(reports["partial_success"])
        self.assertEqual(len(reports["items"]), 2)
        self.assertFalse(reports["items"][0]["applied"])
        self.assertFalse(reports[0]["applied"])
        # 原图尺寸不变
        with Image.open(self.img1) as im:
            self.assertEqual(im.size, (100, 80))

    def test_prepare_agnes_images_apply_mode(self):
        reports = prepare_agnes_images(
            self.dir_path,
            size="60x40",
            apply=True,
            no_backup=False,
            check=True,
        )
        self.assertTrue(reports["ok"])
        self.assertEqual(reports["total"], 2)
        self.assertEqual(reports["success_count"], 2)
        self.assertEqual(reports["failure_count"], 0)
        self.assertFalse(reports["partial_success"])
        self.assertEqual(len(reports["items"]), 2)
        self.assertTrue(reports["items"][0]["applied"])
        self.assertTrue(reports[0]["applied"])
        # 验证已裁切
        with Image.open(self.img1) as im:
            self.assertEqual(im.size, (60, 40))
        # 验证备份存在
        bak = self.dir_path / f"_pre_{self.img1.name}"
        self.assertTrue(bak.exists())

    def test_prepare_agnes_images_check_failure(self):
        seam_img = self.dir_path / "seam_bad.png"
        create_test_image(seam_img, width=120, height=80, left_val=10, right_val=80, seam_x=60)
        with self.assertRaises(RuntimeError):
            prepare_agnes_images(seam_img, seam="off", check=True)

    def test_prepare_images_alias(self):
        self.assertIs(prepare_images, prepare_agnes_images)


class TestBatchStructuredResultAndFailures(unittest.TestCase):
    """验证批量结果结构化契约、部分失败可定位性、重复目标去重与计数一致性。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img1 = self.dir_path / "img1.png"
        self.img2 = self.dir_path / "img2.png"
        create_test_image(self.img1, width=100, height=80)
        create_test_image(self.img2, width=100, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_batch_all_success(self):
        targets = [self.img1, self.img2]
        res_chk = check_images(targets, verbose=False)
        res_prep = prepare_images(targets, size=(50, 40), apply=False, verbose=False)

        # check_images 契约
        self.assertTrue(res_chk["ok"])
        self.assertEqual(res_chk["total"], 2)
        self.assertEqual(res_chk["success_count"], 2)
        self.assertEqual(res_chk["failure_count"], 0)
        self.assertFalse(res_chk["partial_success"])
        self.assertFalse(res_chk["is_partial_success"])
        self.assertEqual(res_chk["failures"], [])
        self.assertEqual(len(res_chk["items"]), 2)

        # prepare_images 契约
        self.assertTrue(res_prep["ok"])
        self.assertEqual(res_prep["total"], 2)
        self.assertEqual(res_prep["success_count"], 2)
        self.assertEqual(res_prep["failure_count"], 0)
        self.assertFalse(res_prep["partial_success"])
        self.assertFalse(res_prep["is_partial_success"])
        self.assertEqual(res_prep["failures"], [])
        self.assertEqual(len(res_prep["items"]), 2)

        # 计数严格一致
        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])
        self.assertEqual(res_chk["partial_success"], res_prep["partial_success"])

    def test_batch_single_failure(self):
        missing = self.dir_path / "non_existing.png"
        res_chk = check_images([missing], verbose=False)
        res_prep = prepare_images([missing], verbose=False)

        # check_images 契约
        self.assertFalse(res_chk["ok"])
        self.assertEqual(res_chk["total"], 1)
        self.assertEqual(res_chk["success_count"], 0)
        self.assertEqual(res_chk["failure_count"], 1)
        self.assertFalse(res_chk["partial_success"])
        self.assertEqual(len(res_chk["failures"]), 1)
        self.assertEqual(res_chk["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(res_chk["failures"][0]["name"], "non_existing.png")
        self.assertIn("non_existing.png", res_chk["failures"][0]["reason"])

        # prepare_images 契约
        self.assertFalse(res_prep["ok"])
        self.assertEqual(res_prep["total"], 1)
        self.assertEqual(res_prep["success_count"], 0)
        self.assertEqual(res_prep["failure_count"], 1)
        self.assertFalse(res_prep["partial_success"])
        self.assertEqual(len(res_prep["failures"]), 1)
        self.assertEqual(res_prep["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(res_prep["failures"][0]["name"], "non_existing.png")
        self.assertIn("non_existing.png", res_prep["failures"][0]["reason"])

        # 计数严格一致
        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])
        self.assertEqual(res_chk["partial_success"], res_prep["partial_success"])

    def test_batch_partial_failure(self):
        missing = self.dir_path / "not_found.png"
        targets = [self.img1, missing]

        res_chk = check_images(targets, verbose=False)
        res_prep = prepare_images(targets, size=(50, 40), apply=False, verbose=False)

        # 验证部分成功标记与可定位性
        self.assertFalse(res_chk["ok"])
        self.assertEqual(res_chk["total"], 2)
        self.assertEqual(res_chk["success_count"], 1)
        self.assertEqual(res_chk["failure_count"], 1)
        self.assertTrue(res_chk["partial_success"])
        self.assertTrue(res_chk["is_partial_success"])
        self.assertEqual(len(res_chk["failures"]), 1)
        self.assertEqual(res_chk["failures"][0]["name"], "not_found.png")
        self.assertEqual(res_chk["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(len(res_chk["items"]), 1)

        self.assertFalse(res_prep["ok"])
        self.assertEqual(res_prep["total"], 2)
        self.assertEqual(res_prep["success_count"], 1)
        self.assertEqual(res_prep["failure_count"], 1)
        self.assertTrue(res_prep["partial_success"])
        self.assertTrue(res_prep["is_partial_success"])
        self.assertEqual(len(res_prep["failures"]), 1)
        self.assertEqual(res_prep["failures"][0]["name"], "not_found.png")
        self.assertEqual(res_prep["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(len(res_prep["items"]), 1)

        # 计数严格一致
        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])
        self.assertEqual(res_chk["partial_success"], res_prep["partial_success"])

    def test_batch_all_failure(self):
        m1 = self.dir_path / "m1.png"
        m2 = self.dir_path / "m2.png"
        targets = [m1, m2]

        res_chk = check_images(targets, verbose=False)
        res_prep = prepare_images(targets, verbose=False)

        # 全失败断言
        self.assertFalse(res_chk["ok"])
        self.assertEqual(res_chk["total"], 2)
        self.assertEqual(res_chk["success_count"], 0)
        self.assertEqual(res_chk["failure_count"], 2)
        self.assertFalse(res_chk["partial_success"])
        self.assertEqual(len(res_chk["failures"]), 2)

        self.assertFalse(res_prep["ok"])
        self.assertEqual(res_prep["total"], 2)
        self.assertEqual(res_prep["success_count"], 0)
        self.assertEqual(res_prep["failure_count"], 2)
        self.assertFalse(res_prep["partial_success"])
        self.assertEqual(len(res_prep["failures"]), 2)

        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])
        self.assertEqual(res_chk["partial_success"], res_prep["partial_success"])

    def test_batch_deduplication(self):
        # 传递带有重复 Path 及等价字符串的目标列表
        targets = [self.img1, str(self.img1), self.img2, self.img1]

        res_chk = check_images(targets, verbose=False)
        res_prep = prepare_images(targets, size=(50, 40), apply=False, verbose=False)

        # 重复项被去重，有效总数应为 2
        self.assertEqual(res_chk["total"], 2)
        self.assertEqual(res_chk["success_count"], 2)
        self.assertEqual(res_chk["failure_count"], 0)
        self.assertFalse(res_chk["partial_success"])

        self.assertEqual(res_prep["total"], 2)
        self.assertEqual(res_prep["success_count"], 2)
        self.assertEqual(res_prep["failure_count"], 0)
        self.assertFalse(res_prep["partial_success"])

        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])

    def test_quiet_verbose_do_not_alter_structured_result(self):
        targets = [self.img1, self.dir_path / "missing.png"]

        # check_images quiet vs verbose
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            res_chk_v = check_images(targets, verbose=True)
        res_chk_q = check_images(targets, verbose=False)
        self.assertEqual(res_chk_v, res_chk_q)

        # prepare_images quiet vs verbose
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            res_prep_v = prepare_images(targets, size=(50, 40), apply=False, verbose=True)
        res_prep_q = prepare_images(targets, size=(50, 40), apply=False, verbose=False)
        self.assertEqual(res_prep_v, res_prep_q)

    def test_counts_consistency_across_scenarios(self):
        test_cases = [
            # 全成功
            [self.img1, self.img2],
            # 单失败
            [self.dir_path / "bad1.png"],
            # 部分失败
            [self.img1, self.dir_path / "bad2.png"],
            # 全失败
            [self.dir_path / "bad1.png", self.dir_path / "bad2.png"],
            # 重复目标去重
            [self.img1, self.img1, self.img2],
            # 空目标
            [],
        ]
        for idx, tc in enumerate(test_cases):
            with self.subTest(case_idx=idx):
                chk = check_images(tc, verbose=False)
                prep = prepare_images(tc, size=(50, 40), apply=False, verbose=False)
                self.assertEqual(chk["total"], prep["total"])
                self.assertEqual(chk["success_count"], prep["success_count"])
                self.assertEqual(chk["failure_count"], prep["failure_count"])
                self.assertEqual(chk["partial_success"], prep["partial_success"])
                self.assertEqual(chk["ok"], prep["ok"])


class TestCLIJsonAndExitCodes(unittest.TestCase):
    """测试配图处理与客观门禁 CLI 的 --json 机器可读模式与退出码语义。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 1. 全成功目录
        self.clean_dir = self.dir_path / "clean_dir"
        self.clean_dir.mkdir(parents=True)
        self.clean1 = self.clean_dir / "clean1.png"
        self.clean2 = self.clean_dir / "clean2.png"
        create_test_image(self.clean1, width=120, height=80)
        create_test_image(self.clean2, width=120, height=80)

        # 2. 部分失败目录 (1 正常 + 1 坏图: 空文件)
        self.partial_dir = self.dir_path / "partial_dir"
        self.partial_dir.mkdir(parents=True)
        self.p_good = self.partial_dir / "p_good.png"
        self.p_bad = self.partial_dir / "p_bad.png"
        create_test_image(self.p_good, width=120, height=80)
        self.p_bad.write_bytes(b"")

        # 3. 全失败目录 (2 坏图: 0 字节文件与非图片文本文件)
        self.fail_dir = self.dir_path / "fail_dir"
        self.fail_dir.mkdir(parents=True)
        self.f_bad1 = self.fail_dir / "f_bad1.png"
        self.f_bad2 = self.fail_dir / "f_bad2.png"
        self.f_bad1.write_bytes(b"")
        self.f_bad2.write_bytes(b"NOT_A_PNG_FILE_CONTENT")

        # 4. 门禁部分失败与全失败目录 (含接缝)
        self.seam_partial_dir = self.dir_path / "seam_partial_dir"
        self.seam_partial_dir.mkdir(parents=True)
        self.sp_clean = self.seam_partial_dir / "sp_clean.png"
        self.sp_seam = self.seam_partial_dir / "sp_seam.png"
        create_test_image(self.sp_clean, width=120, height=80)
        create_test_image(self.sp_seam, width=120, height=80, left_val=20, right_val=60, seam_x=60)

        self.seam_all_fail_dir = self.dir_path / "seam_all_fail_dir"
        self.seam_all_fail_dir.mkdir(parents=True)
        self.sa_seam1 = self.seam_all_fail_dir / "sa_seam1.png"
        self.sa_seam2 = self.seam_all_fail_dir / "sa_seam2.png"
        create_test_image(self.sa_seam1, width=120, height=80, left_val=20, right_val=60, seam_x=60)
        create_test_image(self.sa_seam2, width=120, height=80, left_val=20, right_val=60, seam_x=60)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prepare_cli_json_all_success(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.clean_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_err.getvalue(), "")

        # 标准 JSON 解析与字段契约
        data = json.loads(buf_out.getvalue())
        self.assertIsInstance(data, dict)
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 2)
        self.assertEqual(data["failure_count"], 0)
        self.assertFalse(data["partial_success"])
        self.assertEqual(data["failures"], [])
        self.assertEqual(len(data["items"]), 2)

        # stdout 纯净无人类日志混入
        self.assertTrue(buf_out.getvalue().strip().startswith("{"))
        self.assertTrue(buf_out.getvalue().strip().endswith("}"))
        self.assertNotIn("✓", buf_out.getvalue())
        self.assertNotIn("[预演]", buf_out.getvalue())

    def test_prepare_cli_json_partial_success(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.partial_dir), "--json", "--size", "100x60"])
        # 存在失败时必须返回非零退出码
        self.assertEqual(code, 1)

        data = json.loads(buf_out.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 1)
        self.assertTrue(data["partial_success"])
        self.assertEqual(len(data["failures"]), 1)

        fail = data["failures"][0]
        self.assertEqual(fail["name"], "p_bad.png")
        self.assertEqual(fail["code"], "EMPTY_FILE")
        self.assertIn("空图片文件", fail["reason"])

    def test_prepare_cli_json_all_failure(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.fail_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 1)

        data = json.loads(buf_out.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 0)
        self.assertEqual(data["failure_count"], 2)
        self.assertFalse(data["partial_success"])
        self.assertEqual(len(data["failures"]), 2)
        for fail in data["failures"]:
            self.assertIn("file", fail)
            self.assertIn("code", fail)
            self.assertIn("reason", fail)

    def test_prepare_cli_json_matches_python_api(self):
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = main([str(self.clean_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 0)
        cli_data = json.loads(buf_out.getvalue())

        api_res = prepare_images(self.clean_dir, size=(100, 60), apply=False, verbose=False)
        api_data = json.loads(json.dumps(api_res))
        self.assertEqual(cli_data, api_data)

    def test_check_cli_json_all_success(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.clean_dir), "--check", "--json", "--size", "120x80"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_err.getvalue(), "")

        data = json.loads(buf_out.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 2)
        self.assertEqual(data["failure_count"], 0)
        self.assertFalse(data["partial_success"])
        self.assertEqual(data["failures"], [])
        self.assertNotIn("ALL CLEAR", buf_out.getvalue())
        self.assertNotIn("🔍", buf_out.getvalue())

    def test_check_cli_json_partial_success(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.seam_partial_dir), "--check", "--json"])
        self.assertEqual(code, 1)

        data = json.loads(buf_out.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 1)
        self.assertTrue(data["partial_success"])
        self.assertEqual(len(data["failures"]), 1)
        self.assertEqual(data["failures"][0]["code"], "SEAM_DETECTED")
        self.assertIn("残留接缝", data["failures"][0]["reason"])

    def test_check_cli_json_all_failure(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.seam_all_fail_dir), "--check", "--json"])
        self.assertEqual(code, 1)

        data = json.loads(buf_out.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 0)
        self.assertEqual(data["failure_count"], 2)
        self.assertFalse(data["partial_success"])
        self.assertEqual(len(data["failures"]), 2)
        for fail in data["failures"]:
            self.assertEqual(fail["code"], "SEAM_DETECTED")

    def test_check_cli_json_matches_python_api(self):
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = main([str(self.clean_dir), "--check", "--json", "--size", "120x80"])
        self.assertEqual(code, 0)
        cli_data = json.loads(buf_out.getvalue())

        api_res = check_images(self.clean_dir, size=(120, 80), verbose=False)
        api_data = json.loads(json.dumps(api_res))
        self.assertEqual(cli_data, api_data)

    def test_cli_json_deterministic_structure_and_ordering(self):
        buf1 = io.StringIO()
        with redirect_stdout(buf1):
            code1 = main([str(self.clean_dir), "--json", "--size", "100x60"])
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            code2 = main([str(self.clean_dir), "--json", "--size", "100x60"])

        self.assertEqual(code1, code2)
        self.assertEqual(buf1.getvalue(), buf2.getvalue())

        data1 = json.loads(buf1.getvalue())
        data2 = json.loads(buf2.getvalue())
        self.assertEqual(
            [item["file"] for item in data1["items"]],
            [item["file"] for item in data2["items"]],
        )

    def test_cli_quiet_and_verbose_combinations_with_json(self):
        # 1. prepare --json + --quiet
        buf_out_q = io.StringIO()
        buf_err_q = io.StringIO()
        with redirect_stdout(buf_out_q), redirect_stderr(buf_err_q):
            code_q = main([str(self.clean_dir), "--json", "--quiet"])
        self.assertEqual(code_q, 0)
        self.assertEqual(buf_err_q.getvalue(), "")
        json.loads(buf_out_q.getvalue())

        # 2. prepare --json + --verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(self.clean_dir), "--json", "--verbose"])
        self.assertEqual(code_v, 0)
        self.assertEqual(buf_err_v.getvalue(), "")
        json.loads(buf_out_v.getvalue())

        # 3. check --json + --quiet
        buf_out_cq = io.StringIO()
        buf_err_cq = io.StringIO()
        with redirect_stdout(buf_out_cq), redirect_stderr(buf_err_cq):
            code_cq = main([str(self.clean_dir), "--check", "--json", "--quiet"])
        self.assertEqual(code_cq, 0)
        self.assertEqual(buf_err_cq.getvalue(), "")
        json.loads(buf_out_cq.getvalue())

        # 4. check --json + --verbose
        buf_out_cv = io.StringIO()
        buf_err_cv = io.StringIO()
        with redirect_stdout(buf_out_cv), redirect_stderr(buf_err_cv):
            code_cv = main([str(self.clean_dir), "--check", "--json", "--verbose"])
        self.assertEqual(code_cv, 0)
        self.assertEqual(buf_err_cv.getvalue(), "")
        json.loads(buf_out_cv.getvalue())

    def test_default_cli_output_and_batch_exit_codes_without_json(self):
        # 全成功: 退出码 0，保持人类可读输出与提示
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.clean_dir), "--size", "100x60"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_err.getvalue(), "")
        self.assertIn("[预演]", buf_out.getvalue())
        self.assertIn("clean1.png", buf_out.getvalue())
        self.assertIn("clean2.png", buf_out.getvalue())
        self.assertIn("加 --apply 执行写盘", buf_out.getvalue())

        # 包含失败项: 退出码为 1，诊断信息走 stderr，stdout 仍正常输出成功项预演
        buf_out_p = io.StringIO()
        buf_err_p = io.StringIO()
        with redirect_stdout(buf_out_p), redirect_stderr(buf_err_p):
            code_p = main([str(self.partial_dir), "--size", "100x60"])
        self.assertEqual(code_p, 1)
        self.assertIn("[预演] p_good.png", buf_out_p.getvalue())
        self.assertIn("[!] 处理图片 p_bad.png 失败", buf_err_p.getvalue())

    def test_invalid_cli_arguments_keep_contract(self):
        # 非法 size
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            ret = main([str(self.clean_dir), "--size", "invalid_size"])
        self.assertEqual(ret, 1)
        self.assertIn("尺寸格式无效", buf_err.getvalue())

        # 非法 brightness
        buf_err2 = io.StringIO()
        with redirect_stderr(buf_err2):
            ret2 = main([str(self.clean_dir), "--brightness", "-1"])
        self.assertEqual(ret2, 1)
        self.assertIn("亮度系数必须 >= 0", buf_err2.getvalue())

        # 非法 seam
        buf_err3 = io.StringIO()
        with redirect_stderr(buf_err3):
            ret3 = main([str(self.clean_dir), "--seam", "bad_col"])
        self.assertEqual(ret3, 1)
        self.assertIn("无效的接缝列号", buf_err3.getvalue())

        # 非法 argparse 参数抛出 SystemExit 且退出码为 2
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()):
                main([str(self.clean_dir), "--non-existent-option"])
        self.assertEqual(cm.exception.code, 2)


class TestRealCLIFailureContract(unittest.TestCase):
    """真实独立子进程 CLI 针对 --json 模式失败路径与契约一致性的定向测试。
    验证 stdout 纯 JSON、failure_count/partial_success、failures 明细与 Python API 完全一致、
    有失败时退出码非零、成功项不会因部分失败消失、stderr 诊断不污染 stdout、
    quiet/verbose 不改变 JSON 语义，且不泄漏任何敏感值。
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 1. 正常有效测试图
        self.clean1 = self.dir_path / "clean1.png"
        self.clean2 = self.dir_path / "clean2.png"
        create_test_image(self.clean1, width=120, height=80)
        create_test_image(self.clean2, width=120, height=80)

        # 2. 0 字节空文件 (无法读取/损坏图片)
        self.bad_empty = self.dir_path / "bad_empty.png"
        self.bad_empty.write_bytes(b"")

        # 3. 损坏的图片文件 (非图像二进制文本)
        self.bad_corrupt = self.dir_path / "bad_corrupt.png"
        self.bad_corrupt.write_bytes(b"CORRUPTED_NOT_AN_IMAGE_PAYLOAD\x00\xff\xfe")

        # 4. 截断的伪 PNG 文件
        self.bad_truncated = self.dir_path / "bad_truncated.png"
        self.bad_truncated.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR_TRUNCATED")

        # 5. 接缝质检失败图 (用于图片质量门禁失败)
        self.bad_seam = self.dir_path / "bad_seam.png"
        create_test_image(self.bad_seam, width=120, height=80, left_val=20, right_val=60, seam_x=60)

        # 6. 不存在的文件路径
        self.missing_file = self.dir_path / "non_existing_file_98765.png"

        # 7. 批量目录构建 (包含成功项与多种失败项)
        self.batch_dir = self.dir_path / "batch_mixed"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.clean1, self.batch_dir / "clean1.png")
        shutil.copy2(self.clean2, self.batch_dir / "clean2.png")
        (self.batch_dir / "bad_empty.png").write_bytes(b"")
        (self.batch_dir / "bad_corrupt.png").write_bytes(b"CORRUPTED_NOT_AN_IMAGE_PAYLOAD\x00\xff\xfe")
        create_test_image(self.batch_dir / "bad_seam.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_cli(self, args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
        full_env = os.environ.copy()
        full_env["PYTHONPATH"] = str(REPO_ROOT)
        if env:
            full_env.update(env)
        return subprocess.run(
            [str(PYTHON_BIN), str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            env=full_env,
        )

    def _assert_pure_json(self, stdout: str) -> dict:
        stripped = stdout.strip()
        self.assertTrue(stripped.startswith("{"), f"stdout 未以 '{{' 开头: {stripped[:80]}")
        self.assertTrue(stripped.endswith("}"), f"stdout 未以 '}}' 结尾: {stripped[-80:]}")
        # 人类日志标记不得混入机器可读 stdout
        for marker in ["[预演]", "✓", "ALL CLEAR", "❌", "🔍", "[!]", "[提示]"]:
            self.assertNotIn(marker, stdout)
        try:
            return json.loads(stdout)
        except Exception as e:
            self.fail(f"stdout 不是合规的 JSON: {e}\n完整 stdout:\n{stdout}")

    def _assert_no_sensitive_values(self, stdout: str, stderr: str, tokens: list[str]):
        combined = f"{stdout}\n{stderr}"
        for token in tokens:
            self.assertNotIn(token, combined)

    def test_real_cli_file_not_found(self):
        """覆盖 FILE_NOT_FOUND 失败路径：单文件、不存在目录与空目录。"""
        # 1. 单个不存在的文件 --check --json
        p_chk = self._run_cli([str(self.missing_file), "--check", "--json"])
        self.assertEqual(p_chk.returncode, 1)
        self.assertEqual(p_chk.stderr, "")
        cli_chk = self._assert_pure_json(p_chk.stdout)
        api_chk = json.loads(json.dumps(check_images(self.missing_file, verbose=False)))

        self.assertFalse(cli_chk["ok"])
        self.assertEqual(cli_chk["total"], 1)
        self.assertEqual(cli_chk["success_count"], 0)
        self.assertEqual(cli_chk["failure_count"], 1)
        self.assertFalse(cli_chk["partial_success"])
        self.assertEqual(len(cli_chk["failures"]), 1)
        self.assertEqual(cli_chk["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(cli_chk["failures"][0]["name"], self.missing_file.name)
        self.assertIn("源图片文件不存在", cli_chk["failures"][0]["reason"])
        self.assertEqual(cli_chk["failures"], api_chk["failures"])
        self.assertEqual(cli_chk, api_chk)

        # 2. 单个不存在的文件 prepare --json
        p_prep = self._run_cli([str(self.missing_file), "--json"])
        self.assertEqual(p_prep.returncode, 1)
        self.assertEqual(p_prep.stderr, "")
        cli_prep = self._assert_pure_json(p_prep.stdout)
        api_prep = json.loads(json.dumps(prepare_images(self.missing_file, verbose=False)))

        self.assertFalse(cli_prep["ok"])
        self.assertEqual(cli_prep["total"], 1)
        self.assertEqual(cli_prep["success_count"], 0)
        self.assertEqual(cli_prep["failure_count"], 1)
        self.assertFalse(cli_prep["partial_success"])
        self.assertEqual(len(cli_prep["failures"]), 1)
        self.assertEqual(cli_prep["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(cli_prep["failures"][0]["name"], self.missing_file.name)
        self.assertIn("源图片文件不存在", cli_prep["failures"][0]["reason"])
        self.assertEqual(cli_prep["failures"], api_prep["failures"])
        self.assertEqual(cli_prep, api_prep)

        # 3. 不存在的目录路径
        non_dir = self.dir_path / "non_existing_dir_404"
        p_dir_chk = self._run_cli([str(non_dir), "--check", "--json"])
        self.assertEqual(p_dir_chk.returncode, 1)
        cli_dir_chk = self._assert_pure_json(p_dir_chk.stdout)
        api_dir_chk = json.loads(json.dumps(check_images(non_dir, verbose=False)))
        self.assertEqual(cli_dir_chk["failures"], api_dir_chk["failures"])
        self.assertEqual(cli_dir_chk["failures"][0]["code"], "FILE_NOT_FOUND")

        # 4. 存在但为空的目录 (无 PNG 图片)
        empty_dir = self.dir_path / "empty_dir_no_images"
        empty_dir.mkdir(parents=True, exist_ok=True)
        p_empty_dir = self._run_cli([str(empty_dir), "--json"])
        self.assertEqual(p_empty_dir.returncode, 1)
        cli_empty_dir = self._assert_pure_json(p_empty_dir.stdout)
        api_empty_dir = json.loads(json.dumps(prepare_images(empty_dir, verbose=False)))
        self.assertEqual(cli_empty_dir["failures"][0]["code"], "TARGET_RESOLUTION_ERROR")
        self.assertEqual(cli_empty_dir["failures"], api_empty_dir["failures"])

    def test_real_cli_unreadable_and_corrupt_images(self):
        """覆盖无法读取/损坏图片失败路径：0 字节空文件与文件内容损坏。"""
        # 1. 0 字节文件
        # check --json -> EMPTY_FILE
        p_c_empty = self._run_cli([str(self.bad_empty), "--check", "--json"])
        self.assertEqual(p_c_empty.returncode, 1)
        self.assertEqual(p_c_empty.stderr, "")
        cli_c_empty = self._assert_pure_json(p_c_empty.stdout)
        api_c_empty = json.loads(json.dumps(check_images(self.bad_empty, verbose=False)))
        self.assertEqual(cli_c_empty["failures"][0]["code"], "EMPTY_FILE")
        self.assertEqual(cli_c_empty["failures"], api_c_empty["failures"])
        self.assertEqual(cli_c_empty, api_c_empty)

        # prepare --json -> EMPTY_FILE
        p_p_empty = self._run_cli([str(self.bad_empty), "--json"])
        self.assertEqual(p_p_empty.returncode, 1)
        self.assertEqual(p_p_empty.stderr, "")
        cli_p_empty = self._assert_pure_json(p_p_empty.stdout)
        api_p_empty = json.loads(json.dumps(prepare_images(self.bad_empty, verbose=False)))
        self.assertEqual(cli_p_empty["failures"][0]["code"], "EMPTY_FILE")
        self.assertEqual(cli_p_empty["failures"], api_p_empty["failures"])
        self.assertEqual(cli_p_empty, api_p_empty)

        # 2. 损坏文件 (bad_corrupt)
        # check --json -> UNREADABLE_IMAGE
        p_c_corrupt = self._run_cli([str(self.bad_corrupt), "--check", "--json"])
        self.assertEqual(p_c_corrupt.returncode, 1)
        self.assertEqual(p_c_corrupt.stderr, "")
        cli_c_corrupt = self._assert_pure_json(p_c_corrupt.stdout)
        api_c_corrupt = json.loads(json.dumps(check_images(self.bad_corrupt, verbose=False)))
        self.assertEqual(cli_c_corrupt["failures"][0]["code"], "UNREADABLE_IMAGE")
        self.assertEqual(cli_c_corrupt["failures"], api_c_corrupt["failures"])
        self.assertEqual(cli_c_corrupt, api_c_corrupt)

        # prepare --json -> PREPARE_ERROR
        p_p_corrupt = self._run_cli([str(self.bad_corrupt), "--json"])
        self.assertEqual(p_p_corrupt.returncode, 1)
        self.assertEqual(p_p_corrupt.stderr, "")
        cli_p_corrupt = self._assert_pure_json(p_p_corrupt.stdout)
        api_p_corrupt = json.loads(json.dumps(prepare_images(self.bad_corrupt, verbose=False)))
        self.assertEqual(cli_p_corrupt["failures"][0]["code"], "PREPARE_ERROR")
        self.assertEqual(cli_p_corrupt["failures"], api_p_corrupt["failures"])
        self.assertEqual(cli_p_corrupt, api_p_corrupt)

        # 3. 截断文件 (bad_truncated)
        p_c_trunc = self._run_cli([str(self.bad_truncated), "--check", "--json"])
        self.assertEqual(p_c_trunc.returncode, 1)
        cli_c_trunc = self._assert_pure_json(p_c_trunc.stdout)
        api_c_trunc = json.loads(json.dumps(check_images(self.bad_truncated, verbose=False)))
        self.assertEqual(cli_c_trunc["failures"][0]["code"], "UNREADABLE_IMAGE")
        self.assertEqual(cli_c_trunc["failures"], api_c_trunc["failures"])

        p_p_trunc = self._run_cli([str(self.bad_truncated), "--json"])
        self.assertEqual(p_p_trunc.returncode, 1)
        cli_p_trunc = self._assert_pure_json(p_p_trunc.stdout)
        api_p_trunc = json.loads(json.dumps(prepare_images(self.bad_truncated, verbose=False)))
        self.assertEqual(cli_p_trunc["failures"][0]["code"], "PREPARE_ERROR")
        self.assertEqual(cli_p_trunc["failures"], api_p_trunc["failures"])

    def test_real_cli_quality_gate_failures(self):
        """覆盖图片质量门禁失败路径：残留接缝、尺寸偏差及二者复合。"""
        # 1. 残留接缝 (SEAM_DETECTED)
        p_seam = self._run_cli([str(self.bad_seam), "--check", "--json"])
        self.assertEqual(p_seam.returncode, 1)
        self.assertEqual(p_seam.stderr, "")
        cli_seam = self._assert_pure_json(p_seam.stdout)
        api_seam = json.loads(json.dumps(check_images(self.bad_seam, verbose=False)))

        self.assertFalse(cli_seam["ok"])
        self.assertEqual(cli_seam["failure_count"], 1)
        self.assertEqual(cli_seam["failures"][0]["code"], "SEAM_DETECTED")
        self.assertIn("残留接缝", cli_seam["failures"][0]["reason"])
        self.assertEqual(cli_seam["failures"], api_seam["failures"])
        self.assertEqual(cli_seam, api_seam)

        # 2. 尺寸偏差 (DIMENSION_MISMATCH)
        p_dim = self._run_cli([str(self.clean1), "--check", "--json", "--size", "300x200"])
        self.assertEqual(p_dim.returncode, 1)
        self.assertEqual(p_dim.stderr, "")
        cli_dim = self._assert_pure_json(p_dim.stdout)
        api_dim = json.loads(json.dumps(check_images(self.clean1, size=(300, 200), verbose=False)))

        self.assertFalse(cli_dim["ok"])
        self.assertEqual(cli_dim["failure_count"], 1)
        self.assertEqual(cli_dim["failures"][0]["code"], "DIMENSION_MISMATCH")
        self.assertIn("尺寸不匹配", cli_dim["failures"][0]["reason"])
        self.assertEqual(cli_dim["failures"], api_dim["failures"])
        self.assertEqual(cli_dim, api_dim)

        # 3. 复合门禁失败 (SEAM_AND_DIMENSION_MISMATCH)
        p_both = self._run_cli([str(self.bad_seam), "--check", "--json", "--size", "300x200"])
        self.assertEqual(p_both.returncode, 1)
        self.assertEqual(p_both.stderr, "")
        cli_both = self._assert_pure_json(p_both.stdout)
        api_both = json.loads(json.dumps(check_images(self.bad_seam, size=(300, 200), verbose=False)))

        self.assertFalse(cli_both["ok"])
        self.assertEqual(cli_both["failure_count"], 1)
        self.assertEqual(cli_both["failures"][0]["code"], "SEAM_AND_DIMENSION_MISMATCH")
        self.assertIn("残留接缝", cli_both["failures"][0]["reason"])
        self.assertIn("尺寸不符合预期", cli_both["failures"][0]["reason"])
        self.assertEqual(cli_both["failures"], api_both["failures"])
        self.assertEqual(cli_both, api_both)

    def test_real_cli_batch_partial_failures_and_retention(self):
        """覆盖批量输入中的部分失败：确认 partial_success、成功项完整保留、明细与 API 严格一致。"""
        # 批量目录包含: clean1, clean2, bad_empty, bad_corrupt, bad_seam (共 5 项)

        # 1. prepare --json 预演模式
        p_prep = self._run_cli([str(self.batch_dir), "--json", "--size", "100x60"])
        self.assertEqual(p_prep.returncode, 1)  # 包含失败项，退出码非零
        self.assertEqual(p_prep.stderr, "")    # --json 纯净无 stderr 杂音
        cli_prep = self._assert_pure_json(p_prep.stdout)
        api_prep = json.loads(json.dumps(prepare_images(self.batch_dir, size=(100, 60), apply=False, verbose=False)))

        self.assertFalse(cli_prep["ok"])
        self.assertEqual(cli_prep["total"], 5)
        # clean1, clean2, bad_seam（seam 在 prepare 中成功抹平）为 3 成功；bad_empty, bad_corrupt 为 2 失败
        self.assertEqual(cli_prep["success_count"], 3)
        self.assertEqual(cli_prep["failure_count"], 2)
        self.assertTrue(cli_prep["partial_success"])
        self.assertTrue(cli_prep["is_partial_success"])

        # 成功项不会因部分失败消失
        self.assertEqual(len(cli_prep["items"]), 3)
        success_names = {item["name"] for item in cli_prep["items"]}
        self.assertEqual(success_names, {"clean1.png", "clean2.png", "bad_seam.png"})

        # 失败项定位与契约一致性
        self.assertEqual(len(cli_prep["failures"]), 2)
        fail_codes = {f["name"]: f["code"] for f in cli_prep["failures"]}
        self.assertEqual(fail_codes["bad_empty.png"], "EMPTY_FILE")
        self.assertEqual(fail_codes["bad_corrupt.png"], "PREPARE_ERROR")
        self.assertEqual(cli_prep["failures"], api_prep["failures"])
        self.assertEqual(cli_prep, api_prep)

        # 2. prepare --json --out <dir> 实际写盘模式：成功项正常落地，失败项记录
        out_batch_dir = self.dir_path / "out_batch_written"
        p_prep_out = self._run_cli([str(self.batch_dir), "--out", str(out_batch_dir), "--json", "--size", "100x60"])
        self.assertEqual(p_prep_out.returncode, 1)
        cli_prep_out = self._assert_pure_json(p_prep_out.stdout)
        self.assertTrue(cli_prep_out["partial_success"])
        # 成功项物理落地存在
        self.assertTrue((out_batch_dir / "clean1.png").is_file())
        self.assertTrue((out_batch_dir / "clean2.png").is_file())
        self.assertTrue((out_batch_dir / "bad_seam.png").is_file())
        # 失败项未落地
        self.assertFalse((out_batch_dir / "bad_empty.png").exists())
        self.assertFalse((out_batch_dir / "bad_corrupt.png").exists())

        # 3. check --check --json 门禁模式
        p_chk = self._run_cli([str(self.batch_dir), "--check", "--json"])
        self.assertEqual(p_chk.returncode, 1)
        self.assertEqual(p_chk.stderr, "")
        cli_chk = self._assert_pure_json(p_chk.stdout)
        api_chk = json.loads(json.dumps(check_images(self.batch_dir, verbose=False)))

        self.assertFalse(cli_chk["ok"])
        self.assertEqual(cli_chk["total"], 5)
        # clean1, clean2 为 2 成功；bad_empty, bad_corrupt, bad_seam 为 3 失败
        self.assertEqual(cli_chk["success_count"], 2)
        self.assertEqual(cli_chk["failure_count"], 3)
        self.assertTrue(cli_chk["partial_success"])
        self.assertTrue(cli_chk["is_partial_success"])

        # 成功项未丢失
        self.assertEqual(len(cli_chk["items"]), 2)
        chk_success_names = {item["name"] for item in cli_chk["items"]}
        self.assertEqual(chk_success_names, {"clean1.png", "clean2.png"})

        # 失败项定位与契约一致性
        self.assertEqual(len(cli_chk["failures"]), 3)
        chk_fail_codes = {f["name"]: f["code"] for f in cli_chk["failures"]}
        self.assertEqual(chk_fail_codes["bad_empty.png"], "EMPTY_FILE")
        self.assertEqual(chk_fail_codes["bad_corrupt.png"], "UNREADABLE_IMAGE")
        self.assertEqual(chk_fail_codes["bad_seam.png"], "SEAM_DETECTED")
        self.assertEqual(cli_chk["failures"], api_chk["failures"])
        self.assertEqual(cli_chk, api_chk)

    def test_real_cli_quiet_and_verbose_consistency(self):
        """确认 quiet 与 verbose 组合在 --json 模式下不改变 JSON 语义，且 stderr 不污染 stdout。"""
        # 1. prepare --json: 默认 vs --quiet vs -q vs --verbose vs -v
        p_def = self._run_cli([str(self.batch_dir), "--json", "--size", "100x60"])
        p_quiet = self._run_cli([str(self.batch_dir), "--json", "--quiet", "--size", "100x60"])
        p_q = self._run_cli([str(self.batch_dir), "--json", "-q", "--size", "100x60"])
        p_verb = self._run_cli([str(self.batch_dir), "--json", "--verbose", "--size", "100x60"])
        p_v = self._run_cli([str(self.batch_dir), "--json", "-v", "--size", "100x60"])

        data_def = self._assert_pure_json(p_def.stdout)
        for label, proc in [("quiet", p_quiet), ("-q", p_q), ("verbose", p_verb), ("-v", p_v)]:
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stderr, "", f"{label} 产生了非预期的 stderr 输出")
            data = self._assert_pure_json(proc.stdout)
            self.assertEqual(data, data_def, f"{label} 改变了 JSON 语义")

        # 2. check --check --json: 默认 vs --quiet vs -q vs --verbose vs -v
        p_c_def = self._run_cli([str(self.batch_dir), "--check", "--json"])
        p_c_quiet = self._run_cli([str(self.batch_dir), "--check", "--json", "--quiet"])
        p_c_q = self._run_cli([str(self.batch_dir), "--check", "--json", "-q"])
        p_c_verb = self._run_cli([str(self.batch_dir), "--check", "--json", "--verbose"])
        p_c_v = self._run_cli([str(self.batch_dir), "--check", "--json", "-v"])

        data_c_def = self._assert_pure_json(p_c_def.stdout)
        for label, proc in [("quiet", p_c_quiet), ("-q", p_c_q), ("verbose", p_c_verb), ("-v", p_c_v)]:
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stderr, "", f"{label} 产生了非预期的 stderr 输出")
            data = self._assert_pure_json(proc.stdout)
            self.assertEqual(data, data_c_def, f"{label} 改变了 JSON 语义")

    def test_real_cli_no_sensitive_values_leaked(self):
        """确认各种失败路径与异常状态下，不会向 stdout 或 stderr 泄漏敏感值。"""
        fake_secrets = [
            "SECRET_TOKEN_XYZ_1234567890",
            "PASSWORD_MY_SUPER_SECRET_KEY",
            "API_KEY_AI_AGENT_PLATFORM_ABC",
        ]
        secret_env = {
            "SECRET_TOKEN": fake_secrets[0],
            "API_PASSWORD": fake_secrets[1],
            "OPENAI_API_KEY": fake_secrets[2],
        }

        # 针对各类失败模式运行并验证无敏感值输出
        cases = [
            # FILE_NOT_FOUND
            [str(self.missing_file), "--json"],
            [str(self.missing_file), "--check", "--json"],
            # 坏图与空图
            [str(self.bad_empty), "--json"],
            [str(self.bad_corrupt), "--check", "--json"],
            # 接缝门禁失败
            [str(self.bad_seam), "--check", "--json"],
            # 批量部分失败
            [str(self.batch_dir), "--json", "--size", "100x60"],
            [str(self.batch_dir), "--check", "--json"],
            # 参数错误失败
            [str(self.clean1), "--json", "--size", "invalid_size"],
            [str(self.clean1), "--json", "--brightness", "-1"],
        ]

        for argv in cases:
            proc = self._run_cli(argv, env=secret_env)
            self._assert_no_sensitive_values(proc.stdout, proc.stderr, fake_secrets)

    def test_real_cli_invalid_arguments_keep_clean_output(self):
        """确认非法参数在 --json 下保持非零退出码，stdout 不被污染，stderr 包含合规诊断。"""
        # 1. 非法尺寸 --size
        p_size = self._run_cli([str(self.clean1), "--json", "--size", "invalid"])
        self.assertEqual(p_size.returncode, 1)
        self.assertEqual(p_size.stdout, "")
        self.assertIn("尺寸格式无效", p_size.stderr)

        # 2. 非法亮度 --brightness
        p_b = self._run_cli([str(self.clean1), "--json", "--brightness", "-0.5"])
        self.assertEqual(p_b.returncode, 1)
        self.assertEqual(p_b.stdout, "")
        self.assertIn("亮度系数必须 >= 0", p_b.stderr)

        # 3. 非法接缝 --seam
        p_seam = self._run_cli([str(self.clean1), "--json", "--seam", "bad_col"])
        self.assertEqual(p_seam.returncode, 1)
        self.assertEqual(p_seam.stdout, "")
        self.assertIn("无效的接缝列号", p_seam.stderr)

        # 4. quiet 模式下非法参数抑制 stderr
        p_size_q = self._run_cli([str(self.clean1), "--json", "--size", "invalid", "--quiet"])
        self.assertEqual(p_size_q.returncode, 1)
        self.assertEqual(p_size_q.stdout, "")
        self.assertEqual(p_size_q.stderr, "")


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

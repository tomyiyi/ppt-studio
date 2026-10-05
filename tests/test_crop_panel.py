#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_crop_panel.py
========================
测试 crop_panel.py 的宽高比解析、主体包围盒计算、画幅裁切与 CLI 流程。
使用临时目录与标准库 unittest，不引入额外外部依赖。
"""

import io
import os
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

import numpy as np
from PIL import Image

from scripts.crop_panel import (
    parse_aspect,
    bbox_of,
    cover,
    calculate_crop,
    crop_image,
    crop_panel,
    check_crop_panel,
    run_qa_crop_panel,
    qa_crop_panel,
    qa_single_crop_panel,
    run_qa_single_crop_panel,
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


PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python3"
if not PYTHON_BIN.exists():
    PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
if not PYTHON_BIN.exists():
    PYTHON_BIN = Path(sys.executable)

SCRIPT_PATH = REPO_ROOT / "scripts" / "crop_panel.py"


def run_cli_subprocess(
    args: list[str], cwd: Path | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    """以独立外部子进程方式执行 crop_panel.py，验证真实 OS 进程契约。"""
    full_env = os.environ.copy()
    full_env["PYTHONPATH"] = str(REPO_ROOT)
    if env:
        full_env.update(env)
    return subprocess.run(
        [str(PYTHON_BIN), str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=full_env,
    )


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


class TestCheckCropPanel(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.good_img = self.tmp_path / "good.png"
        create_test_image(self.good_img, 400, 300, (100, 100, 150, 100))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_check_crop_panel_valid_file(self):
        ok, res, issues = check_crop_panel(self.good_img)
        self.assertTrue(ok)
        self.assertEqual(issues, [])
        self.assertEqual(res["name"], "good.png")
        self.assertGreaterEqual(res["after_cover"], 3.0)
        self.assertTrue(res["check_passed"])

    def test_check_crop_panel_pil_image(self):
        im = Image.open(self.good_img)
        ok, res, issues = check_crop_panel(im)
        self.assertTrue(ok)
        self.assertEqual(issues, [])
        self.assertIn("crop_box", res)
        self.assertGreaterEqual(res["after_cover"], 3.0)

    def test_check_crop_panel_dark_image(self):
        dark_img = self.tmp_path / "dark.png"
        create_test_image(dark_img, 200, 200)
        ok, res, issues = check_crop_panel(dark_img)
        self.assertFalse(ok)
        self.assertTrue(any("没找到主体" in s for s in issues))

    def test_check_crop_panel_sparse_low_ink(self):
        sparse = self.tmp_path / "sparse.png"
        arr = np.zeros((400, 500, 3), dtype=np.uint8)
        arr[100:104, 100:104] = 220
        arr[100:104, 396:400] = 220
        arr[296:300, 100:104] = 220
        arr[296:300, 396:400] = 220
        Image.fromarray(arr, "RGB").save(sparse)

        ok, res, issues = check_crop_panel(sparse, min_ink=3.0)
        self.assertFalse(ok)
        self.assertTrue(any("主体墨量不足" in s for s in issues))

    def test_check_crop_panel_nonexistent_file(self):
        missing = self.tmp_path / "non_existing.png"
        ok, res, issues = check_crop_panel(missing)
        self.assertFalse(ok)
        self.assertTrue(len(issues) > 0)


class TestRunQaCropPanel(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.img1 = self.tmp_path / "img1.png"
        self.img2 = self.tmp_path / "img2.png"
        create_test_image(self.img1, 400, 300, (100, 100, 120, 80))
        create_test_image(self.img2, 400, 300, (80, 80, 140, 90))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_qa_crop_panel_success(self):
        self.assertTrue(run_qa_crop_panel(self.img1, verbose=False))
        self.assertTrue(run_qa_crop_panel([self.img1, self.img2], verbose=False))
        self.assertTrue(run_qa_crop_panel(self.tmp_path, verbose=False))

    def test_run_qa_crop_panel_failure(self):
        dark = self.tmp_path / "dark.png"
        create_test_image(dark, 200, 200)
        self.assertFalse(run_qa_crop_panel(dark, verbose=False))
        self.assertFalse(run_qa_crop_panel([self.img1, dark], verbose=False))

    def test_run_qa_crop_panel_missing_path(self):
        self.assertFalse(run_qa_crop_panel(self.tmp_path / "not_there.png", verbose=False))

    def test_run_qa_crop_panel_aliases(self):
        self.assertIs(qa_crop_panel, run_qa_crop_panel)
        self.assertIs(qa_single_crop_panel, check_crop_panel)
        self.assertIs(run_qa_single_crop_panel, check_crop_panel)


class TestCropPanelQuietVerbose(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.good_img = self.tmp_path / "good.png"
        create_test_image(self.good_img, 400, 300, (100, 100, 150, 100))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_quiet_success_silence(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.good_img), "--check", "--quiet"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

        # -q 短参数
        buf_out2 = io.StringIO()
        buf_err2 = io.StringIO()
        with redirect_stdout(buf_out2), redirect_stderr(buf_err2):
            code2 = main([str(self.good_img), "--check", "-q"])
        self.assertEqual(code2, 0)
        self.assertEqual(buf_out2.getvalue(), "")
        self.assertEqual(buf_err2.getvalue(), "")

    def test_cli_quiet_failure_silence(self):
        dark = self.tmp_path / "dark.png"
        create_test_image(dark, 200, 200)
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(dark), "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

    def test_cli_verbose_gate_pass_message(self):
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = main([str(self.good_img), "--check", "--verbose"])
        self.assertEqual(code, 0)
        out_str = buf_out.getvalue()
        self.assertIn("[门禁] ✓ 面板裁切客观质量门禁通过", out_str)

        # -v 短参数
        buf_out2 = io.StringIO()
        with redirect_stdout(buf_out2):
            code2 = main([str(self.good_img), "--check", "-v"])
        self.assertEqual(code2, 0)
        self.assertIn("[门禁] ✓ 面板裁切客观质量门禁通过", buf_out2.getvalue())

    def test_crop_panel_batch_verbose_param(self):
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            res = crop_panel([self.good_img], apply=False, verbose=True)
        self.assertEqual(len(res), 1)
        self.assertIn("[预演] good.png", buf_out.getvalue())


class TestCropPanelContract(unittest.TestCase):
    """收敛后的进程契约测试：聚焦 4 类关键风险与 OS 级子进程契约。

    覆盖范围（仅 9 个用例）：
    - 风险 1：缺失输入（CLI 退出码与 quiet/verbose 行为）
    - 风险 2：损坏或不可读图片（坏数据与暗图无主体，均不产生坏产物）
    - 风险 3：明确门禁失败（--check 墨量门禁未通过）
    - 风险 4：成功路径回归（dry-run 预演、--apply 写盘产物一致性、参数优先级）
    - 真实子进程：验证 OS 级退出码、标准流与文件生成契约（1 个失败，1 个成功）
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.good_img = self.tmp_path / "good.png"
        create_test_image(self.good_img, 400, 300, (100, 100, 150, 100))

    def tearDown(self):
        self.temp_dir.cleanup()

    # ---------------- 风险 1：缺失输入 ----------------

    def test_missing_input_contract(self):
        """缺失输入：quiet 保持 rc=1 且静默，verbose 增加诊断信息。"""
        missing = self.tmp_path / "non_existing.png"

        # quiet / -q: 保持失败退出码 1 且不输出任何信息
        for flags in [["--quiet"], ["-q"]]:
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                code = main([str(missing), *flags])
            self.assertEqual(code, 1)
            self.assertEqual(buf_out.getvalue(), "")
            self.assertEqual(buf_err.getvalue(), "")

        # verbose: 退出码 1 且 stderr 明确指出缺失文件
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(missing), "--verbose"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertIn("源图片文件不存在", buf_err.getvalue())

    # ---------------- 风险 2：损坏或不可读图片 ----------------

    def test_corrupted_image_contract(self):
        """损坏图片：quiet 保持 rc=1 且静默，verbose 诊断异常，均不落盘产物。"""
        broken = self.tmp_path / "broken.png"
        broken.write_bytes(b"INVALID_HEADER_GARBAGE_BYTES")
        out_panel = broken.with_name("broken_panel.png")

        # quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(broken), "--apply", "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")
        self.assertFalse(out_panel.exists())

        # verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(broken), "--apply", "--verbose"])
        self.assertEqual(code_v, 1)
        self.assertEqual(buf_out_v.getvalue(), "")
        self.assertIn("裁切发生异常", buf_err_v.getvalue())
        self.assertFalse(out_panel.exists())

    def test_unreadable_dark_image_contract(self):
        """暗图/无主体不可读：quiet 保持 rc=1 且静默，verbose 诊断无主体，均不写盘。"""
        dark = self.tmp_path / "dark.png"
        create_test_image(dark, 300, 200)
        out_panel = dark.with_name("dark_panel.png")

        # quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(dark), "--apply", "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")
        self.assertFalse(out_panel.exists())

        # verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(dark), "--apply", "--verbose"])
        self.assertEqual(code_v, 1)
        self.assertEqual(buf_out_v.getvalue(), "")
        self.assertIn("没找到主体（亮像素太少）", buf_err_v.getvalue())
        self.assertFalse(out_panel.exists())

    # ---------------- 风险 3：明确门禁失败 ----------------

    def test_explicit_gate_failure_contract(self):
        """明确门禁失败（主体墨量不足）：quiet 保持 rc=1 且静默，verbose 诊断不足。"""
        sparse = self.tmp_path / "sparse.png"
        arr = np.zeros((400, 500, 3), dtype=np.uint8)
        arr[100:104, 100:104] = 220
        arr[100:104, 396:400] = 220
        arr[296:300, 100:104] = 220
        arr[296:300, 396:400] = 220
        Image.fromarray(arr, "RGB").save(sparse)

        # quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(sparse), "--check", "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

        # verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(sparse), "--check", "--verbose"])
        self.assertEqual(code_v, 1)
        self.assertIn("主体墨量不足", buf_err_v.getvalue())

    # ---------------- 风险 4：成功路径回归 ----------------

    def test_success_dry_run_contract(self):
        """成功预演场景：quiet 保持 rc=0 完全静默，verbose 输出统计摘要，均不写盘。"""
        out_panel = self.good_img.with_name("good_panel.png")

        # quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.good_img), "--quiet"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")
        self.assertFalse(out_panel.exists())

        # verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(self.good_img), "--verbose"])
        self.assertEqual(code_v, 0)
        self.assertIn("good.png", buf_out_v.getvalue())
        self.assertIn("主体 bbox", buf_out_v.getvalue())
        self.assertEqual(buf_err_v.getvalue(), "")
        self.assertFalse(out_panel.exists())

    def test_success_apply_contract(self):
        """成功写盘场景：quiet 与 verbose 均返回 rc=0，且写入的产物完全一致。"""
        out_q = self.tmp_path / "panel_quiet.png"
        out_v = self.tmp_path / "panel_verbose.png"

        # quiet 写盘
        buf_out_q = io.StringIO()
        buf_err_q = io.StringIO()
        with redirect_stdout(buf_out_q), redirect_stderr(buf_err_q):
            code_q = main([str(self.good_img), "--out", str(out_q), "--apply", "--quiet"])
        self.assertEqual(code_q, 0)
        self.assertEqual(buf_out_q.getvalue(), "")
        self.assertEqual(buf_err_q.getvalue(), "")
        self.assertTrue(out_q.exists())

        # verbose 写盘
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(self.good_img), "--out", str(out_v), "--apply", "--verbose"])
        self.assertEqual(code_v, 0)
        self.assertIn("已保存", buf_out_v.getvalue())
        self.assertEqual(buf_err_v.getvalue(), "")
        self.assertTrue(out_v.exists())

        # 产物属性严格一致
        with Image.open(out_q) as im_q, Image.open(out_v) as im_v:
            self.assertEqual(im_q.size, im_v.size)
            self.assertEqual(im_q.mode, im_v.mode)

    def test_flag_precedence_quiet_over_verbose(self):
        """参数冲突时 quiet 优先级最高：--quiet 与 --verbose 混用时强制保持静默。"""
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.good_img), "--verbose", "--quiet"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

    # ---------------- 真实 OS 子进程契约 ----------------

    def test_subprocess_failure_contract(self):
        """真实外部子进程失败契约：缺失输入在 OS 级退出 1，quiet 完全静默，verbose 输出 stderr。"""
        missing = self.tmp_path / "sub_missing.png"

        # quiet
        p_q = run_cli_subprocess([str(missing), "--quiet"])
        self.assertEqual(p_q.returncode, 1)
        self.assertEqual(p_q.stdout, "")
        self.assertEqual(p_q.stderr, "")

        # verbose
        p_v = run_cli_subprocess([str(missing), "--verbose"])
        self.assertEqual(p_v.returncode, 1)
        self.assertEqual(p_v.stdout, "")
        self.assertIn("源图片文件不存在", p_v.stderr)

    def test_subprocess_success_apply_contract(self):
        """真实外部子进程成功契约：写盘在 OS 级退出 0，quiet 静默并写盘，verbose 输出确认信息。"""
        out_q = self.tmp_path / "sub_out_q.png"
        out_v = self.tmp_path / "sub_out_v.png"

        # quiet
        p_q = run_cli_subprocess([str(self.good_img), "--out", str(out_q), "--apply", "--quiet"])
        self.assertEqual(p_q.returncode, 0)
        self.assertEqual(p_q.stdout, "")
        self.assertEqual(p_q.stderr, "")
        self.assertTrue(out_q.exists())

        # verbose
        p_v = run_cli_subprocess([str(self.good_img), "--out", str(out_v), "--apply", "--verbose"])
        self.assertEqual(p_v.returncode, 0)
        self.assertIn("已保存", p_v.stdout)
        self.assertEqual(p_v.stderr, "")
        self.assertTrue(out_v.exists())

    def test_main_cli_with_base_dir_and_relative_output(self):
        """测试 main 在传入 base_dir 与相对路径 --out 时能正确在 base_dir 下写盘。"""
        rel_out = Path("nested") / "cropped_rel.png"
        code = main([str(self.good_img), "--out", str(rel_out), "--apply", "--quiet"], base_dir=self.tmp_path)
        self.assertEqual(code, 0)
        expected_out = self.tmp_path / rel_out
        self.assertTrue(expected_out.is_file())

        rel_out_cli = Path("nested") / "cropped_rel_cli.png"
        code_cli = main([str(self.good_img), "--out", str(rel_out_cli), "--apply", "--quiet", "--base-dir", str(self.tmp_path)])
        self.assertEqual(code_cli, 0)
        expected_out_cli = self.tmp_path / rel_out_cli
        self.assertTrue(expected_out_cli.is_file())


if __name__ == "__main__":
    unittest.main()

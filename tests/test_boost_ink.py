#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_boost_ink.py
=======================
测试 boost_ink.py 的黑点保持增益算法、透明通道保持、指标计算、目标路径解析、文件备份与 CLI 流程。
"""

import io
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

import numpy as np
from PIL import Image

from scripts.boost_ink import (
    metrics,
    boost_image,
    boost_file,
    boost_ink,
    check_boosted_quality,
    check_boost_ink,
    run_qa_boost_ink,
    qa_boost_ink,
    qa_single_boost_ink,
    run_qa_single_boost_ink,
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


PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python3"
if not PYTHON_BIN.exists():
    PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
if not PYTHON_BIN.exists():
    PYTHON_BIN = Path(sys.executable)

SCRIPT_PATH = REPO_ROOT / "scripts" / "boost_ink.py"


def run_cli_subprocess(
    args: list[str], cwd: Path | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    """以独立外部子进程方式执行 boost_ink.py，验证真实 OS 进程契约。"""
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

    def test_cli_multiple_paths(self):
        img2 = self.dir_path / "test2.png"
        create_test_image(img2, bg_val=10, stroke_val=120)
        code = main([str(self.test_img), str(img2)])
        self.assertEqual(code, 0)

    def test_cli_check_success(self):
        code = main([str(self.test_img), "--check", "--min-ink", "1.0"])
        self.assertEqual(code, 0)

    def test_cli_check_failure(self):
        # min-ink 设置为 90%，触发墨量不足门禁
        code = main([str(self.test_img), "--check", "--min-ink", "90.0"])
        self.assertEqual(code, 1)


class TestCheckBoostedQuality(unittest.TestCase):
    def test_check_valid_image(self):
        arr = np.full((100, 100, 3), 10, dtype=np.uint8)
        arr[20:80, 20:80] = 200
        im = Image.fromarray(arr, "RGB")
        passed, issues = check_boosted_quality(im, min_ink=2.0)
        self.assertTrue(passed)
        self.assertEqual(len(issues), 0)

    def test_check_dark_image(self):
        # 全暗图 P99 < 30
        arr = np.full((100, 100, 3), 5, dtype=np.uint8)
        im = Image.fromarray(arr, "RGB")
        passed, issues = check_boosted_quality(im, min_ink=2.0)
        self.assertFalse(passed)
        self.assertTrue(any("整体过暗" in s for s in issues))

    def test_check_low_ink(self):
        # 极少亮像素
        arr = np.full((100, 100, 3), 10, dtype=np.uint8)
        arr[50:52, 50:52] = 200
        im = Image.fromarray(arr, "RGB")
        passed, issues = check_boosted_quality(im, min_ink=5.0)
        self.assertFalse(passed)
        self.assertTrue(any("墨量不足" in s for s in issues))


class TestBoostInkProgrammatic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img1 = self.dir_path / "img1.png"
        self.img2 = self.dir_path / "img2.png"
        create_test_image(self.img1, stroke_box=(20, 20, 60, 60), stroke_val=150)
        create_test_image(self.img2, stroke_box=(20, 20, 60, 60), stroke_val=160)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_boost_ink_basic(self):
        res = boost_ink(self.dir_path, target=220.0)
        self.assertEqual(len(res), 2)
        self.assertTrue(all("after" in r for r in res))

    def test_boost_ink_list_input(self):
        res = boost_ink([str(self.img1), self.img2], target=210.0)
        self.assertEqual(len(res), 2)
        names = [r["name"] for r in res]
        self.assertIn("img1.png", names)
        self.assertIn("img2.png", names)

    def test_boost_ink_check_pass(self):
        res = boost_ink(self.img1, check=True, min_ink=1.0)
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0]["quality_gate_passed"])

    def test_boost_ink_check_fail_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            boost_ink(self.img1, check=True, min_ink=95.0)
        self.assertIn("配图客观质量门禁未通过", str(ctx.exception))

    def test_boost_ink_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            boost_ink(self.dir_path / "not_existing.png")


class TestBoostInkCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img1 = self.dir_path / "img1.png"
        self.img2 = self.dir_path / "img2.png"
        create_test_image(self.img1, stroke_box=(20, 20, 60, 60), stroke_val=150)
        create_test_image(self.img2, stroke_box=(20, 20, 60, 60), stroke_val=160)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_single_and_multiple_files(self):
        ret = main([str(self.img1)])
        self.assertEqual(ret, 0)

        ret2 = main([str(self.img1), str(self.img2)])
        self.assertEqual(ret2, 0)

    def test_cli_directory_argument(self):
        ret = main([str(self.dir_path)])
        self.assertEqual(ret, 0)

    def test_cli_explicit_verbose(self):
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            ret = main(["-v", str(self.img1)])
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(ret, 0)
        self.assertIn("img1.png", out)
        self.assertIn("gain", out)

    def test_cli_quiet_mode_success(self):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            ret = main(["-q", str(self.img1)])
            out = sys.stdout.getvalue()
            err = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        self.assertEqual(ret, 0)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_cli_check_pass(self):
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            ret = main([str(self.img1), "--check", "--min-ink", "1.0"])
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(ret, 0)
        self.assertIn("配图客观质量门禁通过", out)

    def test_cli_check_fail(self):
        old_stderr = sys.stderr
        try:
            sys.stderr = io.StringIO()
            ret = main([str(self.img1), "--check", "--min-ink", "99.0"])
            err = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        self.assertEqual(ret, 1)
        self.assertIn("存在未通过客观质量门禁的配图", err)

    def test_cli_check_fail_quiet(self):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            ret = main(["--quiet", str(self.img1), "--check", "--min-ink", "99.0"])
            out = sys.stdout.getvalue()
            err = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        self.assertEqual(ret, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_cli_missing_file_verbose(self):
        old_stderr = sys.stderr
        try:
            sys.stderr = io.StringIO()
            ret = main([str(self.dir_path / "not_existing.png")])
            err = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        self.assertEqual(ret, 1)
        self.assertIn("[err]", err)

    def test_cli_missing_file_quiet(self):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            ret = main(["-q", str(self.dir_path / "not_existing.png")])
            out = sys.stdout.getvalue()
            err = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        self.assertEqual(ret, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_cli_apply_mode(self):
        ret = main([str(self.img1), "--apply"])
        self.assertEqual(ret, 0)
        backup_img = self.dir_path / f"_pre_{self.img1.name}"
        self.assertTrue(backup_img.exists())


class TestCheckBoostInk(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.good_img = self.tmp_path / "good.png"
        create_test_image(self.good_img, stroke_box=(20, 20, 60, 60), stroke_val=150)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_check_boost_ink_valid_file(self):
        ok, res, issues = check_boost_ink(self.good_img, min_ink=1.0)
        self.assertTrue(ok)
        self.assertEqual(issues, [])
        self.assertEqual(res["name"], "good.png")
        self.assertGreater(res["gain"], 1.0)
        self.assertTrue(res["quality_gate_passed"])

    def test_check_boost_ink_pil_image(self):
        with Image.open(self.good_img) as im:
            ok, res, issues = check_boost_ink(im, min_ink=1.0)
            self.assertTrue(ok)
            self.assertEqual(issues, [])
            self.assertIn("gain", res)
            self.assertTrue(res["quality_gate_passed"])

    def test_check_boost_ink_low_ink(self):
        sparse = self.tmp_path / "sparse.png"
        create_test_image(sparse, stroke_box=(20, 20, 5, 5), stroke_val=40)
        ok, res, issues = check_boost_ink(sparse, min_ink=50.0)
        self.assertFalse(ok)
        self.assertTrue(any("墨量不足" in s for s in issues))

    def test_check_boost_ink_nonexistent_file(self):
        missing = self.tmp_path / "missing.png"
        ok, res, issues = check_boost_ink(missing)
        self.assertFalse(ok)
        self.assertTrue(len(issues) > 0)
        self.assertIn("文件不存在", issues[0])


class TestRunQaBoostInk(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.img1 = self.tmp_path / "img1.png"
        self.img2 = self.tmp_path / "img2.png"
        create_test_image(self.img1, stroke_box=(20, 20, 60, 60), stroke_val=150)
        create_test_image(self.img2, stroke_box=(20, 20, 60, 60), stroke_val=160)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_qa_boost_ink_success(self):
        self.assertTrue(run_qa_boost_ink(self.img1, min_ink=1.0, verbose=False))
        self.assertTrue(run_qa_boost_ink([self.img1, self.img2], min_ink=1.0, verbose=False))
        self.assertTrue(run_qa_boost_ink(self.tmp_path, min_ink=1.0, verbose=False))

    def test_run_qa_boost_ink_failure(self):
        self.assertFalse(run_qa_boost_ink(self.img1, min_ink=99.0, verbose=False))

    def test_run_qa_boost_ink_missing_path(self):
        self.assertFalse(run_qa_boost_ink(self.tmp_path / "not_there.png", verbose=False))

    def test_run_qa_boost_ink_aliases(self):
        self.assertIs(qa_boost_ink, run_qa_boost_ink)
        self.assertIs(qa_single_boost_ink, check_boost_ink)
        self.assertIs(run_qa_single_boost_ink, check_boost_ink)

    def test_run_qa_boost_ink_with_base_dir(self):
        self.assertTrue(run_qa_boost_ink("img1.png", min_ink=1.0, verbose=False, base_dir=self.tmp_path))
        self.assertTrue(run_qa_boost_ink(["img1.png", "img2.png"], min_ink=1.0, verbose=False, base_dir=self.tmp_path))

    def test_main_cli_with_base_dir_and_check(self):
        code = main(["img1.png", "--check", "--min-ink", "1.0", "--quiet"], base_dir=self.tmp_path)
        self.assertEqual(code, 0)

    def test_boost_ink_with_base_dir(self):
        res = boost_ink("img1.png", apply=False, base_dir=self.tmp_path)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["name"], "img1.png")


class TestBoostInkContract(unittest.TestCase):
    """收敛后的进程契约测试：聚焦 4 类关键风险与 OS 级子进程契约。

    覆盖范围：
    - 风险 1：缺失输入（CLI 退出码与 quiet/verbose 行为）
    - 风险 2：损坏或不可读图片（坏数据字节，不产生坏产物，返回失败）
    - 风险 3：明确门禁失败（--check 墨量门禁未通过）
    - 风险 4：成功路径回归（dry-run 预演、--apply 写盘与备份契约、参数优先级）
    - 真实子进程：验证 OS 级退出码、标准流与文件生成契约（预演、写盘、门禁失败、缺失输入、未知参数）
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.good_img = self.tmp_path / "good.png"
        create_test_image(self.good_img, stroke_box=(20, 20, 60, 60), stroke_val=150)

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

        # verbose: 退出码 1 且 stderr 明确指出错误
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(missing), "--verbose"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertIn("[err]", buf_err.getvalue())

    # ---------------- 风险 2：损坏或不可读图片 ----------------

    def test_corrupted_image_contract(self):
        """损坏图片：quiet 保持 rc=1 且静默，verbose 诊断异常，均不写盘或产生坏产物。"""
        broken = self.tmp_path / "broken.png"
        broken.write_bytes(b"INVALID_HEADER_GARBAGE_BYTES")
        bak = self.tmp_path / "_pre_broken.png"

        # quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(broken), "--apply", "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")
        self.assertFalse(bak.exists())

        # verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(broken), "--apply", "--verbose"])
        self.assertEqual(code_v, 1)
        self.assertEqual(buf_out_v.getvalue(), "")
        self.assertIn("[err]", buf_err_v.getvalue())
        self.assertFalse(bak.exists())

    # ---------------- 风险 3：明确门禁失败 ----------------

    def test_explicit_gate_failure_contract(self):
        """明确门禁失败（墨量不足）：quiet 保持 rc=1 且静默，verbose 诊断不足。"""
        # quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.good_img), "--check", "--min-ink", "99.0", "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

        # verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(self.good_img), "--check", "--min-ink", "99.0", "--verbose"])
        self.assertEqual(code_v, 1)
        self.assertIn("存在未通过客观质量门禁的配图", buf_err_v.getvalue())

    # ---------------- 风险 4：成功路径回归 ----------------

    def test_success_dry_run_contract(self):
        """成功预演场景：quiet 保持 rc=0 完全静默，verbose 输出统计摘要，均不写盘。"""
        bak = self.tmp_path / f"_pre_{self.good_img.name}"

        # quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.good_img), "--quiet"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")
        self.assertFalse(bak.exists())

        # verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(self.good_img), "--verbose"])
        self.assertEqual(code_v, 0)
        self.assertIn("good.png", buf_out_v.getvalue())
        self.assertIn("gain", buf_out_v.getvalue())
        self.assertEqual(buf_err_v.getvalue(), "")
        self.assertFalse(bak.exists())

    def test_flag_precedence_quiet_over_verbose(self):
        """参数冲突时 quiet 优先级最高：--quiet 与 --verbose 混用时强制保持静默。"""
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.good_img), "--verbose", "--quiet"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

    def test_boost_ink_batch_verbose_param(self):
        """验证 boost_ink 编程式调用 verbose 参数。"""
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            res = boost_ink([self.good_img], apply=False, verbose=True)
        self.assertEqual(len(res), 1)
        self.assertIn("[预演]", buf_out.getvalue())

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
        self.assertIn("[err]", p_v.stderr)

    def test_subprocess_success_dry_run_contract(self):
        """真实外部子进程成功预演契约：canonical dry-run 在 OS 级退出 0 且绝不写盘，quiet 完全静默，verbose 输出预演摘要。"""
        sub_img = self.tmp_path / "sub_dry.png"
        create_test_image(sub_img, stroke_box=(20, 20, 60, 60), stroke_val=150)
        orig_bytes = sub_img.read_bytes()
        mtime_before = sub_img.stat().st_mtime
        bak = self.tmp_path / f"_pre_{sub_img.name}"

        # 默认 dry-run
        p_def = run_cli_subprocess([str(sub_img)])
        self.assertEqual(p_def.returncode, 0)
        self.assertIn("预演模式", p_def.stdout)
        self.assertEqual(p_def.stderr, "")
        self.assertEqual(sub_img.read_bytes(), orig_bytes)
        self.assertEqual(sub_img.stat().st_mtime, mtime_before)
        self.assertFalse(bak.exists())

        # quiet dry-run: rc=0 且完全静默，不写盘
        p_q = run_cli_subprocess([str(sub_img), "--quiet"])
        self.assertEqual(p_q.returncode, 0)
        self.assertEqual(p_q.stdout, "")
        self.assertEqual(p_q.stderr, "")
        self.assertEqual(sub_img.read_bytes(), orig_bytes)
        self.assertEqual(sub_img.stat().st_mtime, mtime_before)
        self.assertFalse(bak.exists())

        # verbose dry-run: rc=0 且输出统计与预演摘要，不写盘
        p_v = run_cli_subprocess([str(sub_img), "--verbose"])
        self.assertEqual(p_v.returncode, 0)
        self.assertIn("预演模式", p_v.stdout)
        self.assertIn("sub_dry.png", p_v.stdout)
        self.assertEqual(p_v.stderr, "")
        self.assertEqual(sub_img.read_bytes(), orig_bytes)
        self.assertEqual(sub_img.stat().st_mtime, mtime_before)
        self.assertFalse(bak.exists())

    def test_subprocess_explicit_gate_failure_contract(self):
        """真实外部子进程门禁失败契约：明确质量门禁失败时 canonical quiet/verbose 均 rc=1 且 quiet 静默、verbose 有门禁诊断。"""
        # quiet: rc=1 且完全静默
        p_q = run_cli_subprocess([str(self.good_img), "--check", "--min-ink", "99.0", "--quiet"])
        self.assertEqual(p_q.returncode, 1)
        self.assertEqual(p_q.stdout, "")
        self.assertEqual(p_q.stderr, "")

        # verbose: rc=1 且 stderr 输出门禁诊断信息
        p_v = run_cli_subprocess([str(self.good_img), "--check", "--min-ink", "99.0", "--verbose"])
        self.assertEqual(p_v.returncode, 1)
        self.assertIn("存在未通过客观质量门禁的配图", p_v.stderr)
        self.assertIn("墨量不足", p_v.stderr)

    def test_subprocess_unknown_argument_contract(self):
        """真实外部子进程未知参数契约：未知参数保持 argparse 规范行为 rc=2，stderr 输出 usage 诊断。"""
        p = run_cli_subprocess(["--unknown-parameter-flag-999"])
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")
        self.assertIn("unrecognized arguments", p.stderr)

        p_q = run_cli_subprocess([str(self.good_img), "--unknown-flag", "--quiet"])
        self.assertEqual(p_q.returncode, 2)
        self.assertEqual(p_q.stdout, "")
        self.assertIn("unrecognized arguments", p_q.stderr)

    def test_subprocess_success_apply_contract(self):
        """真实外部子进程成功契约：写盘在 OS 级退出 0，quiet 静默并写盘，verbose 输出确认信息。"""
        sub_img_q = self.tmp_path / "sub_q.png"
        create_test_image(sub_img_q, stroke_box=(20, 20, 60, 60), stroke_val=150)
        bak_q = self.tmp_path / f"_pre_{sub_img_q.name}"

        # quiet
        p_q = run_cli_subprocess([str(sub_img_q), "--apply", "--quiet"])
        self.assertEqual(p_q.returncode, 0)
        self.assertEqual(p_q.stdout, "")
        self.assertEqual(p_q.stderr, "")
        self.assertTrue(bak_q.exists())

        sub_img_v = self.tmp_path / "sub_v.png"
        create_test_image(sub_img_v, stroke_box=(20, 20, 60, 60), stroke_val=150)
        bak_v = self.tmp_path / f"_pre_{sub_img_v.name}"

        # verbose
        p_v = run_cli_subprocess([str(sub_img_v), "--apply", "--verbose"])
        self.assertEqual(p_v.returncode, 0)
        self.assertIn("已写盘", p_v.stdout)
        self.assertEqual(p_v.stderr, "")
        self.assertTrue(bak_v.exists())


if __name__ == "__main__":
    unittest.main()

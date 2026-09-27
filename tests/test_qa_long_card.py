#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_qa_long_card.py
==========================
测试 qa_long_card.py 的显式路径参数与安全自动发现机制。
使用临时目录与标准库 unittest，不引入额外第三方依赖。
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

for site_pkg in REPO_ROOT.glob(".venv/lib/python*/site-packages"):
    if site_pkg.is_dir() and str(site_pkg) not in sys.path:
        sys.path.insert(0, str(site_pkg))

from PIL import Image
import numpy as np

from scripts.qa_long_card import (
    resolve_project_dir,
    find_long_cards,
    main,
    load_spec_colors,
    parse_colors_from_spec_text,
    check_dimensions_and_mode,
    parse_card_segments,
    check_file_and_format,
    check_sharpness_and_health,
    run_qa_single_long_card,
    run_qa_long_card,
    qa_long_card,
    qa_single_long_card,
    hex_to_rgb,
    ACCENT_RGB,
    BG_RGB,
)


def create_minimal_card_project(project_path: Path) -> None:
    """创建包含 cards/ 目录的最小项目结构。"""
    cards_dir = project_path / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / "01_cover.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350"></svg>',
        encoding="utf-8",
    )


class TestResolveProjectDir(unittest.TestCase):
    def test_explicit_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom_proj"
            proj.mkdir()
            resolved = resolve_project_dir(str(proj))
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "relative_proj"
            proj.mkdir()
            resolved = resolve_project_dir("relative_proj", base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_nonexistent_project_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = Path(tmp_dir) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(str(non_exist))

    def test_auto_discovery_from_target_file_in_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "proj_alpha"
            create_minimal_card_project(proj)
            out_img = proj / "output" / "sample_长图.png"
            out_img.parent.mkdir(parents=True, exist_ok=True)
            out_img.write_bytes(b"dummy_png_bytes")

            resolved = resolve_project_dir(None, target_path=out_img, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_from_target_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "proj_beta"
            create_minimal_card_project(proj)

            resolved = resolve_project_dir(None, target_path=proj, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_from_current_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            create_minimal_card_project(base)
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, base.resolve())

    def test_auto_discovery_from_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "unique_project"
            create_minimal_card_project(proj)
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_when_base_is_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "projects"
            proj = base / "sub_project"
            create_minimal_card_project(proj)
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_none_found_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            resolved = resolve_project_dir(None, base_dir=base, strict=False)
            self.assertIsNone(resolved)

    def test_auto_discovery_none_found_strict_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(None, base_dir=base, strict=True)

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "proj_1"
            p2 = base / "projects" / "proj_2"
            create_minimal_card_project(p1)
            create_minimal_card_project(p2)
            with self.assertRaises(ValueError) as ctx:
                resolve_project_dir(None, base_dir=base)
            self.assertIn("proj_1", str(ctx.exception))
            self.assertIn("proj_2", str(ctx.exception))

    def test_auto_discovery_ignores_dirs_without_cards(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            empty_dir = base / "projects" / "empty_dir"
            empty_dir.mkdir(parents=True)
            real_proj = base / "projects" / "real_proj"
            create_minimal_card_project(real_proj)

            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, real_proj.resolve())


class TestFindLongCards(unittest.TestCase):
    def test_explicit_file_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f = Path(tmp_dir) / "custom_image.png"
            f.write_bytes(b"data")
            found = find_long_cards(f)
            self.assertEqual(found, [f])

    def test_find_in_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            out_img = base / "output" / "agentflow_长图.png"
            out_img.parent.mkdir(parents=True, exist_ok=True)
            out_img.write_bytes(b"data")

            found = find_long_cards(base)
            self.assertEqual(found, [out_img])

    def test_find_in_projects_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj_img = base / "projects" / "test_proj" / "output" / "test_proj_long_card.png"
            proj_img.parent.mkdir(parents=True, exist_ok=True)
            proj_img.write_bytes(b"data")

            found = find_long_cards(base)
            self.assertEqual(found, [proj_img])

    def test_nonexistent_target_raises_filenotfound(self):
        with self.assertRaises(FileNotFoundError):
            find_long_cards("/path/does_not_exist_xyz_long_card.png")

    def test_non_png_file_raises_valueerror(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            txt_file = Path(tmp_dir) / "notes.txt"
            txt_file.write_text("dummy", encoding="utf-8")
            with self.assertRaises(ValueError):
                find_long_cards(txt_file)


class TestLoadSpecColors(unittest.TestCase):
    """测试规范色彩配置解析与动态发现机制。"""

    def test_parse_colors_from_spec_text_basic(self):
        text = """## colors
bg #0B0C12
accent #6E7BFF
"""
        colors = parse_colors_from_spec_text(text)
        self.assertEqual(colors.get("bg"), "#0B0C12")
        self.assertEqual(colors.get("accent"), "#6E7BFF")

    def test_parse_colors_with_yaml_bullets_quotes_and_comments(self):
        text = """## colors
- background: "#08090C" # 暗黑背景底色
- accent: #FF6600       # 强调品牌色
"""
        colors = parse_colors_from_spec_text(text)
        self.assertEqual(colors.get("background"), "#08090C")
        self.assertEqual(colors.get("accent"), "#FF6600")

    def test_load_spec_colors_from_card_spec(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            (proj / "card_spec.md").write_text(
                "## colors\nbg #010203\naccent #112233\n",
                encoding="utf-8",
            )
            acc, bg = load_spec_colors(proj)
            self.assertEqual(acc, hex_to_rgb("#112233"))
            self.assertEqual(bg, hex_to_rgb("#010203"))

    def test_load_spec_colors_from_spec_lock_background(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            (proj / "spec_lock.md").write_text(
                "## colors\n- background: #040506\n- accent: #445566\n",
                encoding="utf-8",
            )
            acc, bg = load_spec_colors(proj)
            self.assertEqual(acc, hex_to_rgb("#445566"))
            self.assertEqual(bg, hex_to_rgb("#040506"))

    def test_load_spec_colors_complementary_fallback(self):
        # card_spec 只有 bg，spec_lock 补充 accent
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            (proj / "card_spec.md").write_text("## colors\nbg #050607\n", encoding="utf-8")
            (proj / "spec_lock.md").write_text("## colors\n- accent: #778899\n", encoding="utf-8")
            acc, bg = load_spec_colors(proj)
            self.assertEqual(acc, hex_to_rgb("#778899"))
            self.assertEqual(bg, hex_to_rgb("#050607"))

    def test_load_spec_colors_from_file_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            spec_file = proj / "card_spec.md"
            spec_file.write_text("## colors\naccent #AABBCC\nbg #223344\n", encoding="utf-8")
            acc, bg = load_spec_colors(spec_file)
            self.assertEqual(acc, hex_to_rgb("#AABBCC"))
            self.assertEqual(bg, hex_to_rgb("#223344"))

    def test_load_spec_colors_nonexistent_returns_defaults(self):
        acc, bg = load_spec_colors(Path("/non_existent_project_12345"))
        # 无法在目标项目找到时，兜底到仓库级规范或默认规范常量
        self.assertIsInstance(acc, tuple)
        self.assertEqual(len(acc), 3)
        self.assertIsInstance(bg, tuple)
        self.assertEqual(len(bg), 3)


class TestCheckDimensionsAndMode(unittest.TestCase):
    """测试长图尺寸与色彩模式客观校验。"""

    def test_valid_image(self):
        img = Image.new("RGB", (1080, 2500), color=(10, 10, 10))
        ok, msg = check_dimensions_and_mode(img)
        self.assertTrue(ok)
        self.assertIn("1080×2500", msg)

    def test_wrong_width(self):
        img = Image.new("RGB", (1920, 2500), color=(10, 10, 10))
        ok, msg = check_dimensions_and_mode(img)
        self.assertFalse(ok)
        self.assertIn("宽度 1920px 不符合标准 1080px", msg)

    def test_height_too_low_with_header_footer(self):
        img = Image.new("RGB", (1080, 1500), color=(10, 10, 10))
        ok, msg = check_dimensions_and_mode(img, require_header=True, require_footer=True)
        self.assertFalse(ok)
        self.assertIn("异常过低", msg)

    def test_height_allowed_for_no_header_no_footer(self):
        # 无 Header 无 Footer 时允许 1350px 基础卡片高度
        img = Image.new("RGB", (1080, 1350), color=(10, 10, 10))
        ok, msg = check_dimensions_and_mode(img, require_header=False, require_footer=False)
        self.assertTrue(ok)

    def test_invalid_mode(self):
        img = Image.new("L", (1080, 2500), color=10)
        ok, msg = check_dimensions_and_mode(img)
        self.assertFalse(ok)
        self.assertIn("色彩模式 L 不合规", msg)


class TestParseCardSegments(unittest.TestCase):
    """测试长图卡片切片序列与间距解析。"""

    def test_parse_with_header_and_footer(self):
        # 2 张 1350 卡片，间距 16px，header 420px，footer 320px
        # total_h = 420 + 16 + 1350 + 16 + 1350 + 16 + 320 = 3488
        arr = np.zeros((3488, 1080, 3), dtype=np.uint8)
        n, gap, slices = parse_card_segments(arr, has_header=True, has_footer=True)
        self.assertEqual(n, 2)
        self.assertEqual(gap, 16)
        self.assertEqual(len(slices), 2)
        self.assertEqual(slices[0], (436, 1786))
        self.assertEqual(slices[1], (1802, 3152))

    def test_parse_without_header_and_footer(self):
        # 2 张 1350 卡片，间距 16px，无 header，无 footer
        # total_h = 1350 + 16 + 1350 = 2716
        arr = np.zeros((2716, 1080, 3), dtype=np.uint8)
        n, gap, slices = parse_card_segments(arr, has_header=False, has_footer=False)
        self.assertEqual(n, 2)
        self.assertEqual(gap, 16)
        self.assertEqual(len(slices), 2)
        self.assertEqual(slices[0], (0, 1350))
        self.assertEqual(slices[1], (1366, 2716))


class TestQALongCardCLI(unittest.TestCase):
    def test_cli_explicit_nonexistent_project_fails(self):
        script = REPO_ROOT / "scripts" / "qa_long_card.py"
        res = subprocess.run(
            [sys.executable, str(script), "--project", "non_existent_path_12345"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("指定的项目目录不存在", res.stderr)

    def test_cli_ambiguous_projects_fails_safely(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "proj_1"
            p2 = base / "projects" / "proj_2"
            create_minimal_card_project(p1)
            create_minimal_card_project(p2)
            # 放入一个顶层 output 长图，触发从 cwd/projects 发现
            dummy_img = base / "output" / "test_长图.png"
            dummy_img.parent.mkdir(parents=True, exist_ok=True)
            dummy_img.write_bytes(b"dummy")

            script = REPO_ROOT / "scripts" / "qa_long_card.py"
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("无法安全确定", res.stderr)

    def test_cli_accepts_no_header_and_no_footer_flags(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            # 运行不存在文件的命令，测试参数解析器能识别 --no-header 与 --no-footer
            script = REPO_ROOT / "scripts" / "qa_long_card.py"
            res = subprocess.run(
                [sys.executable, str(script), "--no-header", "--no-footer", "non_existent_file.png"],
                capture_output=True,
                text=True,
            )
            # 退出码为 1 (文件不存在或无法解码)，但不能报 unrecognized arguments
            self.assertNotIn("unrecognized arguments", res.stderr)

    @patch("scripts.qa_long_card.run_qa_long_card", return_value=True)
    def test_cli_quiet_flag(self, mock_qa):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
            code = main(["valid_mock.png", "--quiet"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

        # -q 短参数测试
        buf_out2 = io.StringIO()
        buf_err2 = io.StringIO()
        with patch("sys.stdout", buf_out2), patch("sys.stderr", buf_err2):
            code2 = main(["valid_mock.png", "-q"])
        self.assertEqual(code2, 0)
        self.assertEqual(buf_out2.getvalue(), "")
        self.assertEqual(buf_err2.getvalue(), "")

    @patch("scripts.qa_long_card.run_qa_long_card", return_value=True)
    def test_cli_verbose_flag(self, mock_qa):
        code_v = main(["valid_mock.png", "-v"])
        self.assertEqual(code_v, 0)
        code_verbose = main(["valid_mock.png", "--verbose"])
        self.assertEqual(code_verbose, 0)

    def test_cli_nonexistent_returns_1(self):
        buf_err = io.StringIO()
        with patch("sys.stderr", buf_err):
            code = main(["/path/not_exist_xyz.png"])
        self.assertEqual(code, 1)
        self.assertIn("目标路径不存在", buf_err.getvalue())

    def test_cli_quiet_error_silenced(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
            code = main(["/path/not_exist_xyz.png", "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

    def test_cli_empty_dir_returns_1(self):
        with tempfile.TemporaryDirectory() as td:
            buf_err = io.StringIO()
            with patch("sys.stderr", buf_err):
                code = main([td])
            self.assertEqual(code, 1)
            self.assertIn("未发现长图 PNG 文件", buf_err.getvalue())


class TestCheckFileAndFormat(unittest.TestCase):
    def test_nonexistent_file_returns_false(self):
        ok, msg, img = check_file_and_format("non_existent_file_98765.png")
        self.assertFalse(ok)
        self.assertIn("文件不存在", msg)
        self.assertIsNone(img)

    def test_undersized_file_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tiny_file = Path(tmp_dir) / "tiny.png"
            tiny_file.write_bytes(b"short")
            ok, msg, img = check_file_and_format(str(tiny_file))
            self.assertFalse(ok)
            self.assertIn("文件体积异常过小", msg)
            self.assertIsNone(img)

    def test_corrupt_file_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            corrupt = Path(tmp_dir) / "corrupt.png"
            corrupt.write_bytes(b"0" * (120 * 1024))
            ok, msg, img = check_file_and_format(corrupt)
            self.assertFalse(ok)
            self.assertIn("图像无法解码", msg)
            self.assertIsNone(img)

    def test_valid_file_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            valid = Path(tmp_dir) / "valid.png"
            # 创建超过 100KB 的图像
            np.random.seed(42)
            arr = np.random.randint(0, 255, (600, 600, 3), dtype=np.uint8)
            Image.fromarray(arr).save(valid, format="PNG")
            self.assertGreaterEqual(valid.stat().st_size, 100 * 1024)
            ok, msg, img = check_file_and_format(str(valid))
            self.assertTrue(ok)
            self.assertIn("图像无损解码成功", msg)
            self.assertIsNotNone(img)
            img.close()


class TestCheckSharpnessAndHealth(unittest.TestCase):
    def test_string_path_support(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dummy = Path(tmp_dir) / "dummy.png"
            dummy.write_bytes(b"0" * (120 * 1024))
            np.random.seed(42)
            arr = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
            ok, msg = check_sharpness_and_health(str(dummy), arr)
            self.assertTrue(ok)
            self.assertIn("拉普拉斯梯度方差", msg)

    def test_low_sharpness_detected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dummy = Path(tmp_dir) / "dummy.png"
            dummy.write_bytes(b"0" * (120 * 1024))
            flat = np.full((100, 100, 3), 128, dtype=np.uint8)
            ok, msg = check_sharpness_and_health(dummy, flat)
            self.assertFalse(ok)
            self.assertIn("拉普拉斯清晰度过低", msg)


class TestProgrammaticAPI(unittest.TestCase):
    def test_run_qa_single_long_card_with_str_and_quiet(self):
        res = run_qa_single_long_card("non_existent_file.png", verbose=False)
        self.assertFalse(res)

    def test_run_qa_long_card_with_empty_directory_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = run_qa_long_card(tmp_dir, verbose=False)
            self.assertFalse(res)

    def test_qa_long_card_alias_callable(self):
        self.assertEqual(qa_long_card, run_qa_long_card)
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = qa_long_card(Path(tmp_dir), verbose=False)
            self.assertFalse(res)

    def test_qa_single_long_card_alias_callable(self):
        self.assertEqual(qa_single_long_card, run_qa_single_long_card)
        res = qa_single_long_card("non_existent_file.png", verbose=False)
        self.assertFalse(res)

    def test_run_qa_long_card_with_nonexistent_target_returns_false(self):
        res = run_qa_long_card("/non_existent_long_card_file_12345.png", verbose=False)
        self.assertFalse(res)

    def test_run_qa_long_card_discovers_in_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            out_dir = base / "output"
            out_dir.mkdir(parents=True)
            target_png = out_dir / "agentflow_长图.png"
            target_png.write_bytes(b"invalid")
            res = run_qa_long_card(base, verbose=False)
            self.assertFalse(res)


if __name__ == "__main__":
    unittest.main()

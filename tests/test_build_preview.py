#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_build_preview.py
===========================
测试 build_preview.py 的显式源目录参数与安全自动发现机制。
使用临时目录与标准库 unittest，不修改或覆盖 output/ 生成物。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_preview import build_preview, resolve_src_dir, inline_images, extract_aspect, main


def create_minimal_svg(svg_path: Path, title: str = "智流 OS 测试") -> None:
    """创建最简有效 SVG 占位文件。"""
    svg_content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        f'<text x="100" y="200" font-size="72" fill="#F7F7F9">{title}</text>'
        '</svg>'
    )
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg_content, encoding="utf-8")


class TestResolveSrcDir(unittest.TestCase):
    def test_explicit_existing_svg_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "custom_svgs"
            create_minimal_svg(svg_dir / "01.svg")
            resolved = resolve_src_dir(str(svg_dir))
            self.assertEqual(resolved, svg_dir.resolve())

    def test_explicit_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            svg_dir = base / "rel_svgs"
            create_minimal_svg(svg_dir / "01.svg")
            resolved = resolve_src_dir("rel_svgs", base_dir=base)
            self.assertEqual(resolved, svg_dir.resolve())

    def test_explicit_project_dir_resolves_to_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "my_project"
            create_minimal_svg(proj / "svg_output" / "01.svg")
            resolved = resolve_src_dir(str(proj))
            self.assertEqual(resolved, (proj / "svg_output").resolve())

    def test_explicit_nonexistent_dir_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = Path(tmp_dir) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                resolve_src_dir(str(non_exist))

    def test_auto_discovery_from_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "alpha"
            create_minimal_svg(proj / "svg_output" / "01.svg")
            resolved = resolve_src_dir(None, base_dir=base)
            self.assertEqual(resolved, (proj / "svg_output").resolve())

    def test_auto_discovery_when_base_is_project_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            create_minimal_svg(base / "svg_output" / "01.svg")
            resolved = resolve_src_dir(None, base_dir=base)
            self.assertEqual(resolved, (base / "svg_output").resolve())

    def test_auto_discovery_when_base_is_svg_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "svg_output"
            create_minimal_svg(base / "01.svg")
            resolved = resolve_src_dir(None, base_dir=base)
            self.assertEqual(resolved, base.resolve())

    def test_auto_discovery_when_base_is_projects_container(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "projects"
            proj = base / "beta"
            create_minimal_svg(proj / "svg_output" / "01.svg")
            resolved = resolve_src_dir(None, base_dir=base)
            self.assertEqual(resolved, (proj / "svg_output").resolve())

    def test_auto_discovery_none_found_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError):
                resolve_src_dir(None, base_dir=base)

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "proj_1"
            p2 = base / "projects" / "proj_2"
            create_minimal_svg(p1 / "svg_output" / "01.svg")
            create_minimal_svg(p2 / "svg_output" / "02.svg")
            with self.assertRaises(ValueError) as ctx:
                resolve_src_dir(None, base_dir=base)
            self.assertIn("proj_1", str(ctx.exception))
            self.assertIn("proj_2", str(ctx.exception))

    def test_auto_discovery_ignores_dirs_without_svgs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p_empty = base / "projects" / "empty_dir"
            p_empty.mkdir(parents=True)
            p_no_svgs = base / "projects" / "no_svgs" / "svg_output"
            p_no_svgs.mkdir(parents=True)
            (p_no_svgs / "readme.txt").write_text("not svg", encoding="utf-8")
            p_real = base / "projects" / "real_proj"
            create_minimal_svg(p_real / "svg_output" / "01.svg")

            resolved = resolve_src_dir(None, base_dir=base)
            self.assertEqual(resolved, (p_real / "svg_output").resolve())

    def test_real_repo_auto_discovery(self):
        resolved = resolve_src_dir()
        expected = (REPO_ROOT / "projects" / "agentflow-os-launch" / "svg_output").resolve()
        self.assertEqual(resolved, expected)


class TestBuildPreview(unittest.TestCase):
    def test_build_preview_explicit_src(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            svg_dir = tmp_path / "svgs"
            create_minimal_svg(svg_dir / "01.svg", "第一页")
            create_minimal_svg(svg_dir / "02.svg", "第二页")
            out_file = tmp_path / "custom_preview.html"

            build_preview(svg_dir, out_file, "测试预览")

            self.assertTrue(out_file.exists())
            html = out_file.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", html)
            self.assertIn("<title>测试预览</title>", html)
            self.assertIn('class="slide active"', html)
            self.assertIn("01 / 02", html)

    def test_build_preview_empty_svg_dir_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            empty_dir = tmp_path / "empty_svgs"
            empty_dir.mkdir()
            out_file = tmp_path / "out.html"
            with self.assertRaises(FileNotFoundError):
                build_preview(empty_dir, out_file, "测试")


class TestBuildPreviewCLI(unittest.TestCase):
    def test_cli_explicit_argument(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            svg_dir = tmp_path / "svgs"
            create_minimal_svg(svg_dir / "01.svg")
            out_file = tmp_path / "preview.html"

            script = REPO_ROOT / "scripts" / "build_preview.py"
            res = subprocess.run(
                [sys.executable, str(script), str(svg_dir), str(out_file), "显式CLI测试"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue(out_file.exists())

    def test_cli_auto_discovery_from_project_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "test_proj"
            create_minimal_svg(proj / "svg_output" / "01.svg")

            script = REPO_ROOT / "scripts" / "build_preview.py"
            out_file = base / "out.html"
            # 传 "-" 作为占位触发自动发现 src，同时显式指定 out
            res = subprocess.run(
                [sys.executable, str(script), "-", str(out_file), "自动发现CLI测试"],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue(out_file.exists())

    def test_cli_auto_discovery_default_invocation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "test_proj"
            create_minimal_svg(proj / "svg_output" / "01.svg")

            script = REPO_ROOT / "scripts" / "build_preview.py"
            # 不带任何参数运行，将在 tmp_dir 下默认生成 output/预览.html
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue((base / "output" / "预览.html").exists())

    def test_cli_ambiguous_fails_safely(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "p1"
            p2 = base / "projects" / "p2"
            create_minimal_svg(p1 / "svg_output" / "01.svg")
            create_minimal_svg(p2 / "svg_output" / "02.svg")

            script = REPO_ROOT / "scripts" / "build_preview.py"
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("无法安全确定", res.stderr)

    def test_cli_nonexistent_src_fails_safely(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            non_exist = base / "not_there"
            script = REPO_ROOT / "scripts" / "build_preview.py"
            res = subprocess.run(
                [sys.executable, str(script), str(non_exist)],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("不存在", res.stderr)


class TestInlineImagesAndExtractAspect(unittest.TestCase):
    def test_extract_aspect_standard_space(self):
        svg = '<svg viewBox="0 0 1080 1350"></svg>'
        self.assertEqual(extract_aspect(svg), (1080.0, 1350.0))

    def test_extract_aspect_comma_separated(self):
        svg = '<svg viewBox="0, 0, 1920, 1080"></svg>'
        self.assertEqual(extract_aspect(svg), (1920.0, 1080.0))

    def test_extract_aspect_width_height_fallback(self):
        svg = '<svg width="1080px" height="1350px"><text>test</text></svg>'
        self.assertEqual(extract_aspect(svg), (1080.0, 1350.0))

    def test_extract_aspect_default_fallback(self):
        svg = '<svg><text>test</text></svg>'
        self.assertEqual(extract_aspect(svg), (1280.0, 720.0))

    def test_inline_images_single_quote_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            img_file = tmp / "icon.png"
            img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")
            svg_snippet = "<svg><image  xlink:href = 'icon.png'  width='10' height='10' /></svg>"
            inlined = inline_images(svg_snippet, tmp)
            self.assertIn("data:image/png;base64,", inlined)

    def test_inline_images_already_data_uri_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            already_data = '<image href="data:image/png;base64,1234" />'
            self.assertEqual(inline_images(already_data, tmp), already_data)

            missing = '<image href="not_exists.png" />'
            self.assertEqual(inline_images(missing, tmp), missing)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_make_cards.py
========================
测试 make_cards.py 的显式项目参数与安全自动发现机制。
使用临时目录与标准库 unittest，不引入第三方依赖。
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

from scripts.make_cards import resolve_project_dir, main


def create_minimal_svg(svg_path: Path) -> None:
    """创建包含最简有效 text 的 SVG 文件。"""
    svg_content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<text x="100" y="200" font-size="72" fill="#F7F7F9">智流 OS 核心架构</text>'
        '</svg>'
    )
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg_content, encoding="utf-8")


class TestResolveProjectDir(unittest.TestCase):
    def test_explicit_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom_proj"
            proj.mkdir()
            resolved = resolve_project_dir(str(proj))
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_nonexistent_project_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = Path(tmp_dir) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(str(non_exist))

    def test_auto_discovery_from_current_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            create_minimal_svg(base / "svg_output" / "01_test.svg")
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, base.resolve())

    def test_auto_discovery_from_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "alpha"
            create_minimal_svg(proj / "svg_output" / "01_test.svg")
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_when_base_is_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "projects"
            proj = base / "beta"
            create_minimal_svg(proj / "svg_output" / "01_test.svg")
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_none_found_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(None, base_dir=base)

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "proj_1"
            p2 = base / "projects" / "proj_2"
            create_minimal_svg(p1 / "svg_output" / "01.svg")
            create_minimal_svg(p2 / "svg_output" / "02.svg")
            with self.assertRaises(ValueError) as ctx:
                resolve_project_dir(None, base_dir=base)
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

            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, p_real.resolve())


class TestMakeCardsCLI(unittest.TestCase):
    def test_cli_explicit_argument(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "test_proj"
            create_minimal_svg(proj / "svg_output" / "01_cover.svg")

            script = REPO_ROOT / "scripts" / "make_cards.py"
            res = subprocess.run(
                [sys.executable, str(script), str(proj)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue((proj / "cards" / "01_cover.svg").exists())

    def test_cli_auto_discovery(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "test_proj"
            create_minimal_svg(proj / "svg_output" / "01_cover.svg")

            script = REPO_ROOT / "scripts" / "make_cards.py"
            # 以项目目录作为工作目录运行，不带 project 参数
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(proj),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue((proj / "cards" / "01_cover.svg").exists())

    def test_cli_auto_discovery_from_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "p1"
            create_minimal_svg(proj / "svg_output" / "01_cover.svg")

            script = REPO_ROOT / "scripts" / "make_cards.py"
            # 以模拟仓库根目录作为工作目录运行，不带 project 参数
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue((proj / "cards" / "01_cover.svg").exists())

    def test_cli_ambiguous_fails_safely(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "p1"
            p2 = base / "projects" / "p2"
            create_minimal_svg(p1 / "svg_output" / "01.svg")
            create_minimal_svg(p2 / "svg_output" / "02.svg")

            script = REPO_ROOT / "scripts" / "make_cards.py"
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("无法安全确定", res.stderr)


if __name__ == "__main__":
    unittest.main()

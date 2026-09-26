#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_qa_long_card.py
==========================
测试 qa_long_card.py 的显式路径参数与安全自动发现机制。
使用临时目录与标准库 unittest，不引入额外第三方依赖。
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

from scripts.qa_long_card import resolve_project_dir, find_long_cards, main


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


if __name__ == "__main__":
    unittest.main()

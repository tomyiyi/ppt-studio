#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_make_video.py
========================
测试 make_video.py 的安全项目发现机制、空 voiceover 校验及 CLI 行为。
使用标准库 unittest 与 tempfile，不生成或覆盖任何输出视频。
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.make_video import load_voiceover, make_video, resolve_project_dir, main


def create_minimal_svg(svg_path: Path) -> None:
    """创建最简 SVG 占位文件。"""
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080"/>', encoding="utf-8")


def create_valid_project(
    proj_dir: Path,
    with_vo_json: bool = True,
    with_notes: bool = False,
    svg_dir_name: str = "svg_output",
) -> Path:
    """在指定路径创建一个具有合法 voiceover 与 SVG 画布的最小项目。"""
    proj_dir.mkdir(parents=True, exist_ok=True)
    if with_vo_json:
        vo_content = [
            {
                "page": "01",
                "title": "测试页面",
                "narration": "这是一个测试解说分镜。",
                "pause_after": 0.5,
                "motion": "none",
            }
        ]
        (proj_dir / "voiceover.json").write_text(json.dumps(vo_content, ensure_ascii=False), encoding="utf-8")
    elif with_notes:
        notes_dir = proj_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "01.md").write_text("# 标题\n正文第一行解说内容", encoding="utf-8")

    svg_file = proj_dir / svg_dir_name / "01.svg"
    create_minimal_svg(svg_file)
    return proj_dir


class TestResolveProjectDir(unittest.TestCase):
    """测试项目路径解析与自适应安全发现。"""

    def test_explicit_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom_proj"
            proj.mkdir()
            resolved = resolve_project_dir(str(proj))
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_subfolder_normalization(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom_proj"
            proj.mkdir()
            sub = proj / "svg_output"
            sub.mkdir()
            resolved = resolve_project_dir(str(sub))
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_nonexistent_project_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = Path(tmp_dir) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(str(non_exist))

    def test_auto_discovery_from_current_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            create_valid_project(base)
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, base.resolve())

    def test_auto_discovery_from_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            create_valid_project(base)
            sub = base / "notes"
            sub.mkdir(parents=True, exist_ok=True)
            resolved = resolve_project_dir(None, base_dir=sub)
            self.assertEqual(resolved, base.resolve())

    def test_auto_discovery_from_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "alpha"
            create_valid_project(proj)
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_when_base_is_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "projects"
            proj = base / "beta"
            create_valid_project(proj, svg_dir_name="cards")
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_none_found_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError) as ctx:
                resolve_project_dir(None, base_dir=base)
            self.assertIn("未在当前目录或 projects/ 下发现", str(ctx.exception))

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "proj_1"
            p2 = base / "projects" / "proj_2"
            create_valid_project(p1)
            create_valid_project(p2)
            with self.assertRaises(ValueError) as ctx:
                resolve_project_dir(None, base_dir=base)
            self.assertIn("发现多个有效项目", str(ctx.exception))
            self.assertIn("proj_1", str(ctx.exception))
            self.assertIn("proj_2", str(ctx.exception))

    def test_auto_discovery_ignores_incomplete_projects(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            # 只有 svg 没有 voiceover
            p_no_vo = base / "projects" / "no_vo"
            create_minimal_svg(p_no_vo / "svg_output" / "01.svg")
            # 只有 voiceover 没有 svg
            p_no_svg = base / "projects" / "no_svg"
            p_no_svg.mkdir(parents=True)
            (p_no_svg / "voiceover.json").write_text('[{"page": "1"}]', encoding="utf-8")
            # 完整项目
            p_valid = base / "projects" / "valid_proj"
            create_valid_project(p_valid)

            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, p_valid.resolve())


class TestVoiceoverValidation(unittest.TestCase):
    """测试 voiceover 解析与空输入校验。"""

    def test_empty_voiceover_json_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "empty_vo_proj"
            proj.mkdir()
            (proj / "voiceover.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_voiceover(proj)
            self.assertIn("voiceover.json 内容为空", str(ctx.exception))

    def test_empty_notes_dir_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "empty_notes_proj"
            (proj / "notes").mkdir(parents=True)
            with self.assertRaises(ValueError) as ctx:
                load_voiceover(proj)
            self.assertIn("未找到任何 .md 文件", str(ctx.exception))

    def test_no_voiceover_and_no_notes_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "no_vo_no_notes"
            proj.mkdir()
            with self.assertRaises(FileNotFoundError):
                load_voiceover(proj)

    def test_make_video_rejects_empty_voiceover(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "empty_vo_proj"
            proj.mkdir()
            (proj / "voiceover.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                make_video(project_dir=proj)
            self.assertIn("voiceover.json 内容为空", str(ctx.exception))


class TestMakeVideoCLI(unittest.TestCase):
    """测试 CLI 命令入口参数解析与异常捕获（不生成实际视频）。"""

    def test_cli_explicit_nonexistent_returns_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = str(Path(tmp_dir) / "non_existent")
            code = main([non_exist])
            self.assertEqual(code, 1)

    def test_cli_auto_discovery_ambiguous_returns_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "p1"
            p2 = base / "projects" / "p2"
            create_valid_project(p1)
            create_valid_project(p2)

            with patch("scripts.make_video.Path.cwd", return_value=base):
                code = main([])
                self.assertEqual(code, 1)

    def test_cli_success_delegation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "valid_proj"
            create_valid_project(proj)

            with patch("scripts.make_video.make_video") as mock_make:
                code = main([str(proj), "--voice", "zh-female", "--format", "16:9"])
                self.assertEqual(code, 0)
                mock_make.assert_called_once()
                call_kwargs = mock_make.call_args.kwargs
                self.assertEqual(call_kwargs["project_dir"], proj.resolve())
                self.assertEqual(call_kwargs["voice_key"], "zh-female")
                self.assertEqual(call_kwargs["format_ratio"], "16:9")


if __name__ == "__main__":
    unittest.main()

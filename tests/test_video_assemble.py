#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_video_assemble.py
============================
测试 video_assemble.py 的视频成对原子提交、底图准备、时序探针及项目解析机制。
使用标准库 unittest 与 tempfile，不调用真实图形渲染或编解码硬件。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.video_assemble import (
    _find_svg_dir,
    commit_video_pair,
    ensure_page_images,
    probe_duration,
    resolve_project_dir,
    run_cmd,
)


class TestCommitVideoPair(unittest.TestCase):
    """测试 commit_video_pair 的原子提交与回滚机制。"""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp_dir.name)
        self.staged_video = self.base / "staged.mp4"
        self.staged_srt = self.base / "staged.srt"
        self.out_video = self.base / "dist" / "output.mp4"
        self.out_srt = self.base / "dist" / "output.srt"

        self.staged_video.write_bytes(b"new-video-bytes")
        self.staged_srt.write_bytes(b"new-srt-bytes")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_commit_video_pair_paths(self):
        self.out_video.parent.mkdir(parents=True, exist_ok=True)
        self.out_video.write_bytes(b"old-video")
        self.out_srt.write_bytes(b"old-srt")

        commit_video_pair(self.staged_video, self.staged_srt, self.out_video, self.out_srt)

        self.assertEqual(self.out_video.read_bytes(), b"new-video-bytes")
        self.assertEqual(self.out_srt.read_bytes(), b"new-srt-bytes")
        self.assertFalse(self.staged_video.exists())
        self.assertFalse(self.staged_srt.exists())
        self.assertFalse(any(self.out_video.parent.glob(".*.backup")))

    def test_commit_video_pair_strings_and_base_dir(self):
        # 使用相对路径字符串并指定 base_dir
        (self.base / "dist").mkdir(parents=True, exist_ok=True)
        self.out_video.write_bytes(b"old-video")
        self.out_srt.write_bytes(b"old-srt")

        commit_video_pair(
            "staged.mp4",
            "staged.srt",
            "dist/output.mp4",
            "dist/output.srt",
            base_dir=self.base,
        )

        self.assertEqual(self.out_video.read_bytes(), b"new-video-bytes")
        self.assertEqual(self.out_srt.read_bytes(), b"new-srt-bytes")

    def test_commit_video_pair_rollback_on_failure(self):
        self.out_video.parent.mkdir(parents=True, exist_ok=True)
        self.out_video.write_bytes(b"old-video")
        self.out_srt.write_bytes(b"old-srt")

        with self.assertRaises(FileNotFoundError):
            commit_video_pair(
                self.staged_video,
                self.base / "nonexistent.srt",
                self.out_video,
                self.out_srt,
            )

        # 检查原有文件是否完整恢复
        self.assertEqual(self.out_video.read_bytes(), b"old-video")
        self.assertEqual(self.out_srt.read_bytes(), b"old-srt")
        self.assertFalse(any(self.out_video.parent.glob(".*.backup")))


class TestProbeDuration(unittest.TestCase):
    """测试 probe_duration 时长探测。"""

    @patch("scripts.video_assemble.run_cmd")
    def test_probe_duration_with_path_and_str(self, mock_cmd):
        proc = MagicMock()
        proc.stdout = " 12.345 \n"
        mock_cmd.return_value = proc

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            media = base / "test.mp4"
            media.touch()

            # Path
            dur1 = probe_duration(media)
            self.assertAlmostEqual(dur1, 12.345)

            # str + base_dir
            dur2 = probe_duration("test.mp4", base_dir=base)
            self.assertAlmostEqual(dur2, 12.345)


class TestEnsurePageImages(unittest.TestCase):
    """测试 ensure_page_images 静态底图准备。"""

    @patch("scripts.video_assemble.render_one")
    def test_ensure_page_images_16_9(self, mock_render):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_project"
            svg_dir = proj / "svg_output"
            svg_dir.mkdir(parents=True, exist_ok=True)
            (svg_dir / "01_cover.svg").write_text("<svg></svg>", encoding="utf-8")
            (svg_dir / "02_detail.svg").write_text("<svg></svg>", encoding="utf-8")

            work_dir = base / "work"

            res = ensure_page_images(
                proj,
                ["01_cover", "02_detail"],
                "16:9",
                work_dir,
            )

            self.assertEqual(len(res), 2)
            self.assertIn("01_cover", res)
            self.assertIn("02_detail", res)
            self.assertEqual(mock_render.call_count, 2)

    @patch("scripts.video_assemble.render_one")
    def test_ensure_page_images_vertical_str_and_base_dir(self, mock_render):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_project"
            cards_dir = proj / "cards"
            cards_dir.mkdir(parents=True, exist_ok=True)
            (cards_dir / "01.svg").write_text("<svg></svg>", encoding="utf-8")

            res = ensure_page_images(
                "my_project",
                ["01"],
                "9:16",
                "work",
                base_dir=base,
            )

            self.assertEqual(len(res), 1)
            self.assertIn("01", res)
            self.assertEqual(mock_render.call_count, 1)

    def test_ensure_page_images_missing_src_dir_raises(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "empty_proj"
            proj.mkdir()
            with self.assertRaises(FileNotFoundError):
                ensure_page_images(proj, ["01"], "16:9", base / "work")

    def test_ensure_page_images_missing_page_raises(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "proj"
            svg_dir = proj / "svg_output"
            svg_dir.mkdir(parents=True)
            (svg_dir / "01.svg").write_text("<svg></svg>", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                ensure_page_images(proj, ["02"], "16:9", base / "work")


class TestFindSvgDir(unittest.TestCase):
    """测试 _find_svg_dir 的多版本优先级探查。"""

    def test_prefers_highest_versioned_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            d_v1 = base / "svg_output"
            d_v3 = base / "svg_output_v3"
            d_v2 = base / "svg_output_v2"
            for d in (d_v1, d_v2, d_v3):
                d.mkdir()
                (d / "p.svg").write_text("<svg/>", encoding="utf-8")

            found = _find_svg_dir(base)
            self.assertEqual(found, d_v3)

    def test_find_svg_dir_str_and_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_proj"
            d_svg = proj / "svg_output"
            d_svg.mkdir(parents=True)
            (d_svg / "p.svg").write_text("<svg/>", encoding="utf-8")

            found = _find_svg_dir("my_proj", base_dir=base)
            self.assertEqual(found, d_svg)


class TestResolveProjectDir(unittest.TestCase):
    """测试 resolve_project_dir 路径与自适应发现。"""

    def test_explicit_existing_project(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "custom"
            proj.mkdir()
            self.assertEqual(resolve_project_dir(proj), proj.resolve())

    def test_explicit_nonexistent_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(Path(td) / "not_there")


class TestRunCmd(unittest.TestCase):
    """测试 run_cmd 包装。"""

    def test_run_cmd_success(self):
        res = run_cmd(["echo", "hello"])
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "hello")

    def test_run_cmd_failure_raises(self):
        with self.assertRaises(subprocess.CalledProcessError):
            run_cmd(["false"], check=True)


if __name__ == "__main__":
    unittest.main()

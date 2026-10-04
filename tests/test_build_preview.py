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

from scripts.build_preview import (
    build_preview,
    resolve_src_dir,
    resolve_project_dir,
    resolve_project_meta,
    inline_images,
    extract_aspect,
    main,
)


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

    def test_explicit_project_dir_resolves_to_highest_version_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "versioned_proj"
            create_minimal_svg(proj / "svg_output" / "01.svg")
            create_minimal_svg(proj / "svg_output_v2" / "01.svg")
            create_minimal_svg(proj / "svg_output_v4" / "01.svg")
            resolved = resolve_src_dir(str(proj))
            self.assertEqual(resolved, (proj / "svg_output_v4").resolve())

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

    def test_auto_discovery_resolves_to_highest_version_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "projects"
            proj = base / "beta"
            create_minimal_svg(proj / "svg_output" / "01.svg")
            create_minimal_svg(proj / "svg_output_v3" / "01.svg")
            resolved = resolve_src_dir(None, base_dir=base)
            self.assertEqual(resolved, (proj / "svg_output_v3").resolve())

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
        resolved = resolve_src_dir(base_dir=REPO_ROOT / "projects" / "agentflow-os-launch")
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


    def test_inline_images_with_query_params(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            img_file = tmp / "diagram.png"
            img_file.write_bytes(b"\x89PNG\r\n\x1a\ndata")
            svg_snippet = '<svg><image href="diagram.png?version=1.2#crop" width="10" height="10" /></svg>'
            inlined = inline_images(svg_snippet, tmp)
            self.assertIn("data:image/png;base64,", inlined)


class TestCardsResolution(unittest.TestCase):
    def test_explicit_project_with_cards_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "deck"
            create_minimal_svg(proj / "svg_output" / "01.svg")
            create_minimal_svg(proj / "cards" / "01.svg")

            res_slides = resolve_src_dir(str(proj), cards=False)
            self.assertEqual(res_slides, (proj / "svg_output").resolve())

            res_cards = resolve_src_dir(str(proj), cards=True)
            self.assertEqual(res_cards, (proj / "cards").resolve())

    def test_fallback_to_cards_when_no_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "cards_only"
            create_minimal_svg(proj / "cards" / "01.svg")

            res = resolve_src_dir(str(proj), cards=False)
            self.assertEqual(res, (proj / "cards").resolve())

    def test_auto_discovery_cards_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "my_cards"
            create_minimal_svg(proj / "cards" / "01.svg")

            res = resolve_src_dir(None, base_dir=base, cards=True)
            self.assertEqual(res, (proj / "cards").resolve())


class TestResolveProjectMeta(unittest.TestCase):
    def test_meta_from_spec_lock(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "agent_proj"
            svg_dir = proj / "svg_output"
            svg_dir.mkdir(parents=True)
            spec_lock = proj / "spec_lock.md"
            spec_lock.write_text(
                "## communication\n- objective: 发布智流 Agent\n\n"
                "## colors\n- accent: #10B981\n- background: #0A0A0E\n- surface: #16171E\n",
                encoding="utf-8",
            )
            create_minimal_svg(svg_dir / "01_cover.svg")

            meta = resolve_project_meta(svg_dir)
            self.assertEqual(meta["title"], "智流 Agent")
            self.assertEqual(meta["accent"], "#10B981")
            self.assertEqual(meta["background"], "#0A0A0E")
            self.assertEqual(meta["surface"], "#16171E")

    def test_meta_prioritizes_versioned_spec_lock(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "agent_proj"
            svg_dir = proj / "svg_output_v4"
            svg_dir.mkdir(parents=True)
            spec_base = proj / "spec_lock.md"
            spec_base.write_text(
                "## communication\n- objective: 旧版目标\n\n## colors\n- accent: #111111\n",
                encoding="utf-8",
            )
            spec_v4 = proj / "spec_lock_v4.md"
            spec_v4.write_text(
                "## communication\n- objective: 发布智流 v4\n\n## colors\n- accent: #22C55E\n",
                encoding="utf-8",
            )
            create_minimal_svg(svg_dir / "01_cover.svg")

            meta = resolve_project_meta(svg_dir)
            self.assertEqual(meta["title"], "智流 v4")
            self.assertEqual(meta["accent"], "#22C55E")

    def test_meta_from_card_spec(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "card_proj"
            cards_dir = proj / "cards"
            cards_dir.mkdir(parents=True)
            card_spec = proj / "card_spec.md"
            card_spec.write_text(
                "# 卡片契约\ntitle: 灵动矩阵\n\n## colors\naccent #F59E0B\nbg #050505\n",
                encoding="utf-8",
            )
            create_minimal_svg(cards_dir / "01_cover.svg")

            meta = resolve_project_meta(cards_dir)
            self.assertEqual(meta["title"], "灵动矩阵")
            self.assertEqual(meta["accent"], "#F59E0B")
            self.assertEqual(meta["background"], "#050505")

    def test_meta_from_cover_svg(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "custom_svgs"
            svg_dir.mkdir()
            svg_path = svg_dir / "01_cover.svg"
            svg_path.write_text(
                '<svg viewBox="0 0 1280 720"><text font-size="96">星火飞跃</text></svg>',
                encoding="utf-8",
            )
            meta = resolve_project_meta(svg_dir)
            self.assertEqual(meta["title"], "星火飞跃")

    def test_meta_fallback_project_dir_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "quantum-nexus-deck"
            svg_dir = proj / "svg_output"
            svg_dir.mkdir(parents=True)
            create_minimal_svg(svg_dir / "slide.svg", "内容")

            meta = resolve_project_meta(svg_dir)
            self.assertEqual(meta["title"], "Quantum Nexus Deck")


    def test_meta_ignores_numeric_typography_title(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "numeric_title_proj"
            svg_dir = proj / "svg_output"
            svg_dir.mkdir(parents=True)
            spec_lock = proj / "spec_lock.md"
            spec_lock.write_text(
                "## communication\n- objective: 发布量子跃迁引擎\n\n## typography\n- title: 32\n",
                encoding="utf-8",
            )
            create_minimal_svg(svg_dir / "01_cover.svg")

            meta = resolve_project_meta(svg_dir)
            self.assertEqual(meta["title"], "量子跃迁引擎")


class TestQualityGateCheck(unittest.TestCase):
    def test_build_preview_with_check_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            svg_dir = tmp / "svgs"
            create_minimal_svg(svg_dir / "01_cover.svg", "第一页")
            create_minimal_svg(svg_dir / "02_detail.svg", "第二页")
            out_file = tmp / "checked_preview.html"

            res = build_preview(svg_dir, out_file, title="测试质检通过", check=True)
            self.assertEqual(res, out_file)
            self.assertTrue(out_file.exists())

    def test_build_preview_check_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            svg_dir = tmp / "svgs"
            svg_dir.mkdir()
            # 写入比例严重不一致的两个 SVG，触发 qa_preview 门禁失败
            (svg_dir / "01.svg").write_text('<svg viewBox="0 0 1280 720"><text>1</text></svg>', encoding="utf-8")
            (svg_dir / "02.svg").write_text('<svg viewBox="0 0 1080 1350"><text>2</text></svg>', encoding="utf-8")
            out_file = tmp / "fail_preview.html"

            with self.assertRaises(RuntimeError) as ctx:
                build_preview(svg_dir, out_file, title="失败测试", check=True)
            self.assertIn("未通过", str(ctx.exception))

    def test_check_failure_preserves_existing_preview_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            svg_dir = tmp / "svgs"
            svg_dir.mkdir()
            (svg_dir / "01.svg").write_text('<svg viewBox="0 0 1280 720"><text>1</text></svg>', encoding="utf-8")
            (svg_dir / "02.svg").write_text('<svg viewBox="0 0 1080 1350"><text>2</text></svg>', encoding="utf-8")
            out_file = tmp / "existing_preview.html"
            out_file.write_text("old-preview", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                build_preview(svg_dir, out_file, title="失败测试", check=True)
            self.assertEqual(out_file.read_text(encoding="utf-8"), "old-preview")
            self.assertFalse(any(tmp.glob(".existing_preview.html.*")))


class TestCLIAdvancedFlags(unittest.TestCase):
    def test_cli_cards_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "deck"
            create_minimal_svg(proj / "svg_output" / "01.svg")
            card_file = proj / "cards" / "01_card.svg"
            create_minimal_svg(card_file, "卡片首屏")
            out_file = proj / "out_cards.html"

            script = REPO_ROOT / "scripts" / "build_preview.py"
            res = subprocess.run(
                [sys.executable, str(script), str(proj), str(out_file), "--cards"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue(out_file.exists())
            html = out_file.read_text(encoding="utf-8")
            self.assertIn("卡片首屏", html)

    def test_cli_check_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "deck"
            create_minimal_svg(proj / "svg_output" / "01.svg", "页1")
            create_minimal_svg(proj / "svg_output" / "02.svg", "页2")
            out_file = proj / "out_checked.html"

            script = REPO_ROOT / "scripts" / "build_preview.py"
            res = subprocess.run(
                [sys.executable, str(script), str(proj / "svg_output"), str(out_file), "门禁测试", "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue(out_file.exists())
            self.assertIn("客观质量门禁通过", res.stdout)

    def test_cli_title_override_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "deck"
            create_minimal_svg(proj / "svg_output" / "01.svg")
            out_file = proj / "out_title.html"

            script = REPO_ROOT / "scripts" / "build_preview.py"
            res = subprocess.run(
                [sys.executable, str(script), str(proj / "svg_output"), str(out_file), "--title-override", "覆盖标题"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            html = out_file.read_text(encoding="utf-8")
            self.assertIn("<title>覆盖标题</title>", html)


class TestBuildPreviewSubdirAndSpecResolution(unittest.TestCase):
    """测试 build_preview 对子目录、规范文件、单文件自适应解析。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.proj = Path(self.td.name) / "test_proj"
        self.svg_dir = self.proj / "svg_output"
        self.render_dir = self.proj / "render"
        self.images_dir = self.proj / "images"
        self.notes_dir = self.proj / "notes"
        self.svg_dir.mkdir(parents=True)
        self.render_dir.mkdir(parents=True)
        self.images_dir.mkdir(parents=True)
        self.notes_dir.mkdir(parents=True)

        self.spec_file = self.proj / "spec_lock.md"
        self.spec_file.write_text(
            "## communication\n- objective: 发布测试产品\n\n## colors\n- accent: #6E7BFF\n",
            encoding="utf-8",
        )
        self.svg_file = self.svg_dir / "01_cover.svg"
        create_minimal_svg(self.svg_file, "测试首页")

    def tearDown(self):
        self.td.cleanup()

    def test_resolve_project_dir_subfolders_and_file(self):
        self.assertEqual(resolve_project_dir(self.svg_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.render_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.images_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.spec_file), self.proj.resolve())

    def test_resolve_src_dir_from_subfolder(self):
        self.assertEqual(resolve_src_dir(str(self.render_dir), base_dir=Path(self.td.name)), self.svg_dir.resolve())
        self.assertEqual(resolve_src_dir(str(self.images_dir), base_dir=Path(self.td.name)), self.svg_dir.resolve())
        self.assertEqual(resolve_src_dir(str(self.notes_dir), base_dir=Path(self.td.name)), self.svg_dir.resolve())

    def test_resolve_src_dir_from_spec_file(self):
        self.assertEqual(resolve_src_dir(str(self.spec_file), base_dir=Path(self.td.name)), self.svg_dir.resolve())

    def test_resolve_src_dir_from_single_svg_file(self):
        self.assertEqual(resolve_src_dir(str(self.svg_file), base_dir=Path(self.td.name)), self.svg_dir.resolve())

    def test_resolve_src_dir_cards_from_subfolder_and_spec_file(self):
        proj_cards = Path(self.td.name) / "card_proj"
        cards_dir = proj_cards / "cards"
        render_cards_dir = proj_cards / "render_cards"
        cards_dir.mkdir(parents=True)
        render_cards_dir.mkdir(parents=True)
        card_file = cards_dir / "01_card.svg"
        create_minimal_svg(card_file, "卡片一")
        card_spec = proj_cards / "card_spec.md"
        card_spec.write_text("# 卡片规范\n", encoding="utf-8")

        self.assertEqual(resolve_src_dir(str(render_cards_dir), cards=True, base_dir=Path(self.td.name)), cards_dir.resolve())
        self.assertEqual(resolve_src_dir(str(card_spec), cards=True, base_dir=Path(self.td.name)), cards_dir.resolve())
        self.assertEqual(resolve_src_dir(str(card_file), cards=True, base_dir=Path(self.td.name)), cards_dir.resolve())

    def test_build_preview_from_subfolder_and_spec_file(self):
        out_from_render = self.proj / "preview_render.html"
        out_from_spec = self.proj / "preview_spec.html"
        build_preview(src=self.render_dir, out=out_from_render)
        self.assertTrue(out_from_render.exists())
        build_preview(src=self.spec_file, out=out_from_spec)
        self.assertTrue(out_from_spec.exists())

    def test_cli_from_subfolder_and_spec_file(self):
        script = REPO_ROOT / "scripts" / "build_preview.py"
        out_cli1 = self.proj / "out_cli1.html"
        res1 = subprocess.run(
            [sys.executable, str(script), str(self.render_dir), str(out_cli1)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res1.returncode, 0, msg=f"CLI failed: {res1.stderr}")
        self.assertTrue(out_cli1.exists())

        out_cli2 = self.proj / "out_cli2.html"
        res2 = subprocess.run(
            [sys.executable, str(script), str(self.spec_file), str(out_cli2)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res2.returncode, 0, msg=f"CLI failed: {res2.stderr}")
        self.assertTrue(out_cli2.exists())


if __name__ == "__main__":
    unittest.main()

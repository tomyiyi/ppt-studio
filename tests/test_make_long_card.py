#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_make_long_card.py
============================
测试 make_long_card.py 的元信息解析、自适应安全项目发现、长图构建与 CLI 门禁。
使用临时目录与标准库 unittest，不引入额外外部依赖。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 确保能加载项目内 .venv site-packages 中的 PIL
for site_pkg in REPO_ROOT.glob(".venv/lib/python*/site-packages"):
    if site_pkg.is_dir() and str(site_pkg) not in sys.path:
        sys.path.insert(0, str(site_pkg))

from PIL import Image

from scripts.make_long_card import (
    hex_to_rgb,
    read_project_meta,
    build_header_image,
    build_footer_image,
    resolve_project_dir,
    make_long_card,
    main,
    BG_COLOR,
    ACCENT_COLOR,
)


def create_minimal_card_project(project_path: Path, count: int = 2, card_size: tuple[int, int] = (100, 150)) -> None:
    """创建包含 cards/ 及 render_cards/ 的最小测试项目。"""
    cards_dir = project_path / "cards"
    render_dir = project_path / "render_cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, count + 1):
        stem = f"{i:02d}_card"
        # 写入 SVG
        svg_file = cards_dir / f"{stem}.svg"
        svg_file.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {card_size[0]} {card_size[1]}"></svg>',
            encoding="utf-8",
        )
        # 预先生成 PNG，避免依赖外部渲染器
        png_file = render_dir / f"{stem}.png"
        img = Image.new("RGB", card_size, color=(20 * i, 30 * i, 40 * i))
        img.save(png_file, format="PNG")
        img.close()


class TestHexToRgb(unittest.TestCase):
    def test_valid_hex_with_hash(self):
        self.assertEqual(hex_to_rgb("#6E7BFF", (0, 0, 0)), (110, 123, 255))

    def test_valid_hex_without_hash(self):
        self.assertEqual(hex_to_rgb("0B0C12", (0, 0, 0)), (11, 12, 18))

    def test_invalid_hex_returns_default(self):
        self.assertEqual(hex_to_rgb("invalid", (1, 2, 3)), (1, 2, 3))
        self.assertEqual(hex_to_rgb("#fff", (1, 2, 3)), (1, 2, 3))
        self.assertEqual(hex_to_rgb("", (1, 2, 3)), (1, 2, 3))


class TestReadProjectMeta(unittest.TestCase):
    def test_default_meta_without_spec(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "demo-os-launch"
            proj.mkdir()
            meta = read_project_meta(proj)
            self.assertEqual(meta["title"], "Demo Os Launch")
            self.assertEqual(meta["accent_color"], ACCENT_COLOR)
            self.assertEqual(meta["bg_color"], BG_COLOR)

    def test_meta_with_card_spec_and_notes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom-project"
            proj.mkdir()
            # 写入 card_spec.md
            spec_file = proj / "card_spec.md"
            spec_file.write_text(
                "- objective: 自定义长图全景\n"
                "- core_message: 极速可验证交付\n"
                "accent_color: #123456\n"
                "bg_color: #654321\n",
                encoding="utf-8",
            )
            # 写入 notes/01_cover.md
            notes_dir = proj / "notes"
            notes_dir.mkdir()
            (notes_dir / "01_cover.md").write_text("只说一句话：新一代智能体发布", encoding="utf-8")

            meta = read_project_meta(proj)
            self.assertEqual(meta["objective"], "自定义长图全景")
            self.assertEqual(meta["core_message"], "极速可验证交付")
            self.assertEqual(meta["accent_color"], (18, 52, 86))
            self.assertEqual(meta["bg_color"], (101, 67, 33))
            self.assertEqual(meta["headline"], "新一代智能体发布")


class TestBuildHeaderFooter(unittest.TestCase):
    def test_build_header_image(self):
        meta = {"title": "Test Title", "accent_color": ACCENT_COLOR, "bg_color": BG_COLOR}
        img = build_header_image(width=1080, meta=meta, card_count=3)
        self.assertEqual(img.size, (1080, 420))
        self.assertEqual(img.mode, "RGB")
        img.close()

    def test_build_footer_image(self):
        meta = {"accent_color": ACCENT_COLOR, "bg_color": BG_COLOR}
        img = build_footer_image(width=1080, meta=meta)
        self.assertEqual(img.size, (1080, 320))
        self.assertEqual(img.mode, "RGB")
        img.close()


class TestResolveProjectDir(unittest.TestCase):
    def test_explicit_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj_a"
            create_minimal_card_project(proj)
            resolved = resolve_project_dir(str(proj))
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "proj_rel"
            create_minimal_card_project(proj)
            resolved = resolve_project_dir("proj_rel", base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_nonexistent_project_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = Path(tmp_dir) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(str(non_exist))

    def test_explicit_cards_dir_resolves_to_parent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            create_minimal_card_project(proj)
            cards = proj / "cards"
            resolved = resolve_project_dir(str(cards))
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_dir_without_cards_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            empty_dir = Path(tmp_dir) / "empty"
            empty_dir.mkdir()
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(str(empty_dir))

    def test_auto_discovery_from_base_dir_with_cards(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            create_minimal_card_project(base)
            resolved = resolve_project_dir(base_dir=base)
            self.assertEqual(resolved, base.resolve())

    def test_auto_discovery_from_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p_dir = base / "projects"
            proj = p_dir / "my_project"
            create_minimal_card_project(proj)
            resolved = resolve_project_dir(base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p_dir = base / "projects"
            create_minimal_card_project(p_dir / "proj_1")
            create_minimal_card_project(p_dir / "proj_2")
            with self.assertRaises(ValueError) as ctx:
                resolve_project_dir(base_dir=base)
            self.assertIn("无法安全确定", str(ctx.exception))

    def test_auto_discovery_no_projects_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(base_dir=base)


class TestMakeLongCard(unittest.TestCase):
    def test_make_long_card_full(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "deck"
            create_minimal_card_project(proj, count=2, card_size=(200, 300))
            out_img = proj / "output" / "long.png"

            res = make_long_card(
                project_dir=proj,
                out_path=out_img,
                gap=10,
                include_header=True,
                include_footer=True,
            )
            self.assertEqual(res, out_img.resolve())
            self.assertTrue(out_img.exists())

            # 校验尺寸: 宽 200, 高 = 420(header) + 10(gap) + 300 + 10(gap) + 300 + 10(gap) + 320(footer) = 1370
            with Image.open(out_img) as im:
                self.assertEqual(im.size, (200, 1370))

    def test_make_long_card_without_header_footer(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "deck"
            create_minimal_card_project(proj, count=2, card_size=(200, 300))
            out_img = proj / "output" / "long_no_hf.png"

            res = make_long_card(
                project_dir=proj,
                out_path=out_img,
                gap=10,
                include_header=False,
                include_footer=False,
            )
            self.assertTrue(out_img.exists())
            with Image.open(out_img) as im:
                # 高 = 300 + 10 + 300 = 610
                self.assertEqual(im.size, (200, 610))

    def test_missing_cards_dir_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "empty"
            proj.mkdir()
            with self.assertRaises(FileNotFoundError):
                make_long_card(proj)


class TestMainCLI(unittest.TestCase):
    def test_main_help_exits_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_nonexistent_project_returns_one(self):
        code = main(["/non_existent_project_12345"])
        self.assertEqual(code, 1)

    def test_main_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "deck"
            create_minimal_card_project(proj, count=2, card_size=(200, 300))
            out_img = proj / "long_cli.png"
            code = main([str(proj), "--out", str(out_img), "--no-header", "--no-footer"])
            self.assertEqual(code, 0)
            self.assertTrue(out_img.exists())


if __name__ == "__main__":
    unittest.main()

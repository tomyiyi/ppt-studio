#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_qa_cards.py
======================
测试 qa_cards.py 的路径解析、版式规范与字号阶梯加载、主句一致性、签名竖线门禁与 CLI 行为。
使用标准库 unittest 与 tempfile，不修改已有生成物。
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

from scripts.qa_cards import (
    DEFAULT_RAMP,
    load_ramp,
    load_spec_roles,
    load_spec_colors,
    check_card_statement_consistency,
    resolve_card_dirs,
    run_qa_cards,
    main,
)


def create_minimal_card_svg(
    file_path: Path,
    font_size: int = 72,
    statement_text: str = "智流系统核心能力发布",
    has_accent_bar: bool = True,
    accent_color: str = "#6E7BFF",
    bar_width: float = 6.0,
    bar_height: float = 80.0,
    aspect_w: int = 1080,
    aspect_h: int = 1350,
) -> None:
    """生成用于测试的最小 SVG 卡片。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    bar_tag = (
        f'<rect x="80" y="320" width="{bar_width}" height="{bar_height}" fill="{accent_color}" />\n'
        if has_accent_bar else ""
    )
    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {aspect_w} {aspect_h}">
  <rect x="0" y="0" width="{aspect_w}" height="{aspect_h}" fill="#0A0D14" />
  {bar_tag}
  <text x="100" y="380" font-size="{font_size}" fill="#F0F3FF">{statement_text}</text>
  <text x="100" y="500" font-size="36" fill="#8A92A6">副标题说明信息</text>
  <text x="100" y="600" font-size="28" fill="#5F667A">辅助详情文字内容</text>
</svg>
"""
    file_path.write_text(svg_content, encoding="utf-8")


class TestResolveCardDirs(unittest.TestCase):
    def test_explicit_card_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            card_dir = Path(tmp_dir) / "custom_cards"
            card_dir.mkdir()
            create_minimal_card_svg(card_dir / "01_cover.svg")
            resolved = resolve_card_dirs(str(card_dir))
            self.assertEqual(resolved, [card_dir.resolve()])

    def test_explicit_project_dir_with_cards(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "my_project"
            proj.mkdir()
            cards_dir = proj / "cards"
            create_minimal_card_svg(cards_dir / "01_cover.svg")
            resolved = resolve_card_dirs(str(proj))
            self.assertEqual(resolved, [cards_dir.resolve()])

    def test_explicit_svg_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cards_dir = Path(tmp_dir) / "cards"
            svg_file = cards_dir / "01_cover.svg"
            create_minimal_card_svg(svg_file)
            resolved = resolve_card_dirs(str(svg_file))
            self.assertEqual(resolved, [cards_dir.resolve()])

    def test_explicit_nonexistent_target_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = Path(tmp_dir) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                resolve_card_dirs(str(non_exist))

    def test_explicit_non_svg_file_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            txt_file = Path(tmp_dir) / "notes.txt"
            txt_file.write_text("dummy", encoding="utf-8")
            with self.assertRaises(ValueError):
                resolve_card_dirs(str(txt_file))

    def test_auto_discovery_from_base_dir_with_cards(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cards_dir = base / "cards"
            create_minimal_card_svg(cards_dir / "01_cover.svg")
            resolved = resolve_card_dirs(".", base_dir=base)
            self.assertEqual(resolved, [cards_dir.resolve()])

    def test_auto_discovery_from_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "unique_proj"
            cards_dir = proj / "cards"
            create_minimal_card_svg(cards_dir / "01_cover.svg")
            resolved = resolve_card_dirs(".", base_dir=base)
            self.assertEqual(resolved, [cards_dir.resolve()])

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "p1" / "cards"
            p2 = base / "projects" / "p2" / "cards"
            create_minimal_card_svg(p1 / "01_cover.svg")
            create_minimal_card_svg(p2 / "01_cover.svg")
            with self.assertRaises(ValueError) as ctx:
                resolve_card_dirs(".", base_dir=base)
            self.assertIn("无法安全确定", str(ctx.exception))

    def test_auto_discovery_no_cards_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError):
                resolve_card_dirs(".", base_dir=base)


class TestCardSpecLoading(unittest.TestCase):
    def test_load_ramp_from_spec(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_path = Path(tmp_dir) / "card_spec.md"
            spec_path.write_text(
                """# Card Specification
## typography
28 footnote
36 body
44 subhead
72 statement
96 title
132 hero
""",
                encoding="utf-8",
            )
            ramp = load_ramp(spec_path)
            self.assertEqual(ramp, {28, 36, 44, 72, 96, 132})

    def test_load_spec_roles(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_path = Path(tmp_dir) / "card_spec.md"
            spec_path.write_text(
                """## typography
28 detail
36 caption
72 statement
""",
                encoding="utf-8",
            )
            roles = load_spec_roles(spec_path)
            self.assertEqual(roles.get("statement"), 72)
            self.assertEqual(roles.get("caption"), 36)

    def test_load_spec_colors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_path = Path(tmp_dir) / "card_spec.md"
            spec_path.write_text(
                """## colors
accent #6E7BFF
background #0A0D14
text_primary #F0F3FF
""",
                encoding="utf-8",
            )
            colors = load_spec_colors(spec_path)
            self.assertEqual(colors.get("accent"), "#6E7BFF")
            self.assertEqual(colors.get("background"), "#0A0D14")

    def test_fallback_ramp_on_missing_spec(self):
        ramp = load_ramp(Path("/non_existent_dir_spec/card_spec.md"))
        self.assertEqual(ramp, DEFAULT_RAMP)


class TestStatementConsistency(unittest.TestCase):
    def test_consistent_statement(self):
        card_slides = [
            ("01_cover", [{"fs": 96, "txt": "智流 OS"}, {"fs": 36, "txt": "副标"}]),
            ("02_tension", [{"fs": 72, "txt": "跨卡主句一"}, {"fs": 36, "txt": "说明"}]),
            ("03_position", [{"fs": 72, "txt": "跨卡主句二"}, {"fs": 36, "txt": "说明"}]),
        ]
        ok, msg = check_card_statement_consistency(card_slides, expected_sz=72)
        self.assertTrue(ok)
        self.assertIn("严格对齐", msg)

    def test_drift_statement_detected(self):
        card_slides = [
            ("01_cover", [{"fs": 96, "txt": "封面"}, {"fs": 36, "txt": "副标"}]),
            ("02_tension", [{"fs": 72, "txt": "标准主句"}, {"fs": 36, "txt": "说明"}]),
            ("03_position", [{"fs": 56, "txt": "漂移主句字号偏小"}, {"fs": 36, "txt": "说明"}]),
        ]
        ok, msg = check_card_statement_consistency(card_slides, expected_sz=72)
        self.assertFalse(ok)
        self.assertIn("发现主句字号漂移", msg)
        self.assertIn("03_position", msg)

    def test_single_card_skips(self):
        card_slides = [
            ("02_tension", [{"fs": 72, "txt": "单张卡片"}, {"fs": 36, "txt": "说明"}]),
        ]
        ok, msg = check_card_statement_consistency(card_slides, expected_sz=72)
        self.assertTrue(ok)
        self.assertIn("跳过", msg)


class TestRunQaCards(unittest.TestCase):
    def test_valid_card_suite_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cards_dir = Path(tmp_dir) / "cards"
            create_minimal_card_svg(cards_dir / "01_cover.svg", font_size=96, statement_text="封面大标题")
            create_minimal_card_svg(cards_dir / "02_tension.svg", font_size=72, statement_text="正文主句一")
            create_minimal_card_svg(cards_dir / "03_position.svg", font_size=72, statement_text="正文主句二")
            ok = run_qa_cards(cards_dir)
            self.assertTrue(ok)

    def test_missing_accent_bar_warns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cards_dir = Path(tmp_dir) / "cards"
            create_minimal_card_svg(cards_dir / "01_cover.svg", has_accent_bar=False)
            ok = run_qa_cards(cards_dir)
            self.assertFalse(ok)

    def test_wrong_accent_bar_color_warns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cards_dir = Path(tmp_dir) / "cards"
            create_minimal_card_svg(cards_dir / "01_cover.svg", accent_color="#FF0000")
            ok = run_qa_cards(cards_dir)
            self.assertFalse(ok)

    def test_off_ramp_font_size_warns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cards_dir = Path(tmp_dir) / "cards"
            # 50px 不在默认阶梯 {28, 36, 44, 56, 72, 96, 132} 中
            create_minimal_card_svg(cards_dir / "01_cover.svg", font_size=50)
            ok = run_qa_cards(cards_dir)
            self.assertFalse(ok)


class TestMainCLI(unittest.TestCase):
    def test_cli_success_on_valid_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cards_dir = Path(tmp_dir) / "cards"
            create_minimal_card_svg(cards_dir / "01_cover.svg", font_size=72)
            exit_code = main([str(cards_dir)])
            self.assertEqual(exit_code, 0)

    def test_cli_failure_on_nonexistent_dir(self):
        exit_code = main(["/non_existent_dir_98765"])
        self.assertEqual(exit_code, 1)

    def test_cli_failure_on_ambiguous_projects(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "p1" / "cards"
            p2 = base / "projects" / "p2" / "cards"
            create_minimal_card_svg(p1 / "01_cover.svg")
            create_minimal_card_svg(p2 / "01_cover.svg")
            # 在没有指定 target 时传入包含多项目的目录作为 target 选项
            exit_code = main([str(base / "projects")])
            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()

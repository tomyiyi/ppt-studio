#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_qa_layout.py
=======================
测试 qa_layout.py 的基础数值解析、属性继承、版式规范、主句一致性、路径自适应探查与 CLI 行为。
使用标准库 unittest 与 tempfile，不修改或覆盖任何生成物。
"""

import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.qa_layout import (
    DEFAULT_RAMP,
    CANVAS_W,
    CANVAS_H,
    MARGIN,
    parse_num,
    char_w,
    text_width,
    inherited_font_size,
    load_ramp,
    load_spec_roles,
    check_overflow,
    check_typescale,
    check_backdrop,
    check_dup_images,
    check_line_collisions,
    check_statement_consistency,
    resolve_layout_dirs,
    run_qa_layout,
    main,
)


def create_test_svg(
    file_path: Path,
    width: int = 1280,
    height: int = 720,
    title: str = "智流系统发布",
    title_sz: int = 56,
    body_sz: int = 16,
    img_w: int = 1280,
    img_h: int = 720,
    img_href: str = "bg.png",
    second_img_href: str | None = None,
    extra_content: str = "",
) -> None:
    """生成用于测试的 SVG 幻灯片。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    img_tag = f'<image href="{img_href}" width="{img_w}" height="{img_h}" />\n' if img_href else ""
    second_img_tag = (
        f'<image href="{second_img_href}" width="{img_w}" height="{img_h}" />\n'
        if second_img_href
        else ""
    )
    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#0A0D14" />
  {img_tag}
  {second_img_tag}
  <text x="80" y="140" font-size="{title_sz}" fill="#F0F3FF">{title}</text>
  <text x="80" y="240" font-size="{body_sz}" fill="#8A92A6">正文段落说明文字内容</text>
  {extra_content}
</svg>
"""
    file_path.write_text(svg_content, encoding="utf-8")


class TestParseNum(unittest.TestCase):
    """测试安全数值解析器。"""

    def test_none_and_empty(self):
        self.assertEqual(parse_num(None), 0.0)
        self.assertEqual(parse_num("", 10.0), 10.0)
        self.assertEqual(parse_num("   ", -1.0), -1.0)

    def test_numbers(self):
        self.assertEqual(parse_num(42), 42.0)
        self.assertEqual(parse_num(3.14), 3.14)
        self.assertEqual(parse_num("56"), 56.0)
        self.assertEqual(parse_num("16.5"), 16.5)

    def test_units_and_spaces(self):
        self.assertEqual(parse_num("56px"), 56.0)
        self.assertEqual(parse_num("  72 px "), 72.0)
        self.assertEqual(parse_num("-15.2px"), -15.2)


class TestInheritedFontSize(unittest.TestCase):
    """测试 SVG font-size 继承解析。"""

    def test_direct_font_size(self):
        xml_str = '<svg xmlns="http://www.w3.org/2000/svg"><text font-size="24">测试</text></svg>'
        root = ET.fromstring(xml_str)
        t = root.find("{http://www.w3.org/2000/svg}text")
        sz = inherited_font_size(t, [root])
        self.assertEqual(sz, 24.0)

    def test_parent_g_inheritance(self):
        xml_str = '<svg xmlns="http://www.w3.org/2000/svg"><g font-size="32px"><text>继承</text></g></svg>'
        root = ET.fromstring(xml_str)
        g = root.find("{http://www.w3.org/2000/svg}g")
        t = g.find("{http://www.w3.org/2000/svg}text")
        sz = inherited_font_size(t, [root, g])
        self.assertEqual(sz, 32.0)

    def test_fallback_default(self):
        xml_str = '<svg xmlns="http://www.w3.org/2000/svg"><text>无字号</text></svg>'
        root = ET.fromstring(xml_str)
        t = root.find("{http://www.w3.org/2000/svg}text")
        sz = inherited_font_size(t, [root])
        self.assertEqual(sz, 16.0)


class TestTextWidthAndOverflow(unittest.TestCase):
    """测试文本测宽与安全区溢出判定。"""

    def test_char_w(self):
        self.assertEqual(char_w("中"), 1.0)
        self.assertEqual(char_w("A", mono=False), 0.52)
        self.assertEqual(char_w("A", mono=True), 0.60)

    def test_text_width(self):
        w = text_width("中文", 20)
        self.assertEqual(w, 40.0)
        w_ls = text_width("中文", 20, ls=2.0)
        self.assertEqual(w_ls, 42.0)

    def test_overflow_detection(self):
        # 产生右溢出文本：x=1200, 文本很长
        xml_str = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W} {CANVAS_H}">'
            '<text x="1200" y="100" font-size="40">超长右侧溢出文本内容展示</text>'
            '</svg>'
        )
        root = ET.fromstring(xml_str)
        issues = check_overflow(root)
        self.assertTrue(any("右溢出" in i for i in issues))

    def test_left_overflow_with_end_anchor(self):
        # text-anchor=end, x=50, 向左延伸溢出
        xml_str = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W} {CANVAS_H}">'
            '<text x="50" y="100" font-size="30" text-anchor="end">左侧溢出内容</text>'
            '</svg>'
        )
        root = ET.fromstring(xml_str)
        issues = check_overflow(root)
        self.assertTrue(any("左溢出" in i for i in issues))


class TestTypescaleAndBackdrop(unittest.TestCase):
    """测试字号阶梯合规、底图覆盖率与源图重影。"""

    def test_typescale_compliant(self):
        xml_str = '<svg xmlns="http://www.w3.org/2000/svg"><text font-size="16">正文</text><text font-size="56">标题</text></svg>'
        root = ET.fromstring(xml_str)
        used, off = check_typescale(root, {16, 56})
        self.assertEqual(off, [])
        self.assertEqual(used, {16: 1, 56: 1})

    def test_typescale_violations(self):
        xml_str = '<svg xmlns="http://www.w3.org/2000/svg"><text font-size="14">非标正文</text><text font-size="50">非标标题</text></svg>'
        root = ET.fromstring(xml_str)
        used, off = check_typescale(root, {16, 56})
        self.assertEqual(off, [14, 50])

    def test_backdrop_full_cover(self):
        xml_str = (
            f'<svg xmlns="http://www.w3.org/2000/svg">'
            f'<image href="bg.png" width="{CANVAS_W}" height="{CANVAS_H}" />'
            f'</svg>'
        )
        root = ET.fromstring(xml_str)
        cov = check_backdrop(root)
        self.assertIsNotNone(cov)
        self.assertAlmostEqual(cov, 100.0)

    def test_backdrop_under_cover(self):
        xml_str = '<svg xmlns="http://www.w3.org/2000/svg"><image href="thumb.png" width="400" height="300" /></svg>'
        root = ET.fromstring(xml_str)
        cov = check_backdrop(root)
        self.assertIsNotNone(cov)
        self.assertLess(cov, 90.0)

    def test_backdrop_none(self):
        xml_str = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1280" height="720" /></svg>'
        root = ET.fromstring(xml_str)
        cov = check_backdrop(root)
        self.assertIsNone(cov)

    def test_check_dup_images(self):
        xml_str = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<image href="images/card_bg.png" />'
            '<image href="images/card_bg_panel.png" />'
            '</svg>'
        )
        root = ET.fromstring(xml_str)
        dups = check_dup_images(root)
        self.assertIn("card_bg", dups)


class TestLineCollisions(unittest.TestCase):
    """测试文本压行碰撞检测。"""

    def test_no_collision(self):
        xml_str = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<text x="100" y="100" font-size="20">第一行</text>'
            '<text x="100" y="140" font-size="20">第二行距离足够</text>'
            '</svg>'
        )
        root = ET.fromstring(xml_str)
        collisions = check_line_collisions(root)
        self.assertEqual(collisions, [])

    def test_collision_detected(self):
        xml_str = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<text x="100" y="100" font-size="30">第一行大字</text>'
            '<text x="100" y="105" font-size="30">第二行严重重叠</text>'
            '</svg>'
        )
        root = ET.fromstring(xml_str)
        collisions = check_line_collisions(root)
        self.assertTrue(len(collisions) > 0)
        self.assertIn("压行", collisions[0])


class TestStatementConsistency(unittest.TestCase):
    """测试跨正文页主句字号一致性。"""

    def test_consistent_statements(self):
        svg_slides = [
            ("01_cover", ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-size="96">封面</text></svg>')),
            ("02_slide", ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-size="56">第二页主句</text></svg>')),
            ("03_slide", ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-size="56">第三页主句</text></svg>')),
        ]
        ok, msg = check_statement_consistency(svg_slides, expected_sz=56)
        self.assertTrue(ok)
        self.assertIn("严格对齐", msg)

    def test_drifting_statements(self):
        svg_slides = [
            ("01_cover", ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-size="96">封面</text></svg>')),
            ("02_slide", ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-size="56">第二页主句</text></svg>')),
            ("03_slide", ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-size="44">第三页主句漂移</text></svg>')),
        ]
        ok, msg = check_statement_consistency(svg_slides, expected_sz=56)
        self.assertFalse(ok)
        self.assertIn("主句字号漂移", msg)


class TestResolveLayoutDirs(unittest.TestCase):
    """测试待质检目录与文件的自适应安全探查。"""

    def test_explicit_svg_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "svgs"
            create_test_svg(svg_dir / "01.svg")
            resolved = resolve_layout_dirs(str(svg_dir))
            self.assertEqual(resolved, [svg_dir.resolve()])

    def test_explicit_project_dir_with_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "my_proj"
            create_test_svg(proj / "svg_output" / "01.svg")
            resolved = resolve_layout_dirs(str(proj))
            self.assertEqual(resolved, [(proj / "svg_output").resolve()])

    def test_explicit_single_svg_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_file = Path(tmp_dir) / "slide.svg"
            create_test_svg(svg_file)
            resolved = resolve_layout_dirs(str(svg_file))
            self.assertEqual(resolved, [svg_file.resolve()])

    def test_explicit_non_svg_file_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            txt_file = Path(tmp_dir) / "readme.txt"
            txt_file.write_text("hello", encoding="utf-8")
            with self.assertRaises(ValueError):
                resolve_layout_dirs(str(txt_file))

    def test_explicit_nonexistent_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = Path(tmp_dir) / "not_there"
            with self.assertRaises(FileNotFoundError):
                resolve_layout_dirs(str(non_exist))

    def test_auto_discovery_from_projects(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "test_p"
            create_test_svg(proj / "svg_output" / "01.svg")
            resolved = resolve_layout_dirs(None, base_dir=base)
            self.assertEqual(resolved, [(proj / "svg_output").resolve()])

    def test_auto_discovery_ambiguous_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "p1"
            p2 = base / "projects" / "p2"
            create_test_svg(p1 / "svg_output" / "01.svg")
            create_test_svg(p2 / "svg_output" / "01.svg")
            with self.assertRaises(ValueError):
                resolve_layout_dirs(None, base_dir=base)


class TestRunQaLayout(unittest.TestCase):
    """测试完整质检门禁执行流程。"""

    def test_valid_layout_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "svg_output"
            create_test_svg(svg_dir / "01_cover.svg", title_sz=96, body_sz=16)
            create_test_svg(svg_dir / "02_tension.svg", title_sz=56, body_sz=16)
            ok = run_qa_layout(svg_dir)
            self.assertTrue(ok)

    def test_corrupted_svg_handled_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "svg_output"
            svg_dir.mkdir()
            bad_svg = svg_dir / "bad.svg"
            bad_svg.write_text("<svg>未闭合的损坏文件", encoding="utf-8")
            ok = run_qa_layout(svg_dir)
            self.assertFalse(ok)

    def test_empty_svg_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            empty_dir = Path(tmp_dir) / "empty"
            empty_dir.mkdir()
            ok = run_qa_layout(empty_dir)
            self.assertFalse(ok)


class TestMainCli(unittest.TestCase):
    """测试 CLI 命令行入口调度与返回码。"""

    def test_cli_success_on_valid_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "svgs"
            create_test_svg(svg_dir / "01.svg", title_sz=56, body_sz=16)
            with patch("sys.stdout", new_callable=io.StringIO):
                code = main([str(svg_dir)])
            self.assertEqual(code, 0)

    def test_cli_fails_on_nonexistent_path(self):
        with patch("sys.stderr", new_callable=io.StringIO):
            code = main(["/non_existent_path_xyz123"])
        self.assertEqual(code, 1)

    def test_cli_fails_on_non_svg_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f = Path(tmp_dir) / "test.txt"
            f.touch()
            with patch("sys.stderr", new_callable=io.StringIO):
                code = main([str(f)])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()

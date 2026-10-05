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
    load_canvas_from_spec,
    load_margin_from_spec,
    SEVERITY,
    check_role_discipline,
    BREATHING_MAX_CARDS,
    check_overflow,
    check_typescale,
    check_backdrop,
    check_dup_images,
    check_line_collisions,
    check_statement_consistency,
    check_contrast,
    Image,
    np,
    resolve_layout_dirs,
    qa_single_layout,
    run_qa_single_layout,
    run_qa_layout,
    qa_layout,
    resolve_project_dir,
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


class TestDefaultRampAndSpecLoading(unittest.TestCase):
    """测试默认字号阶梯规范、spec 规格加载与行内注释过滤。"""

    def test_default_ramp_includes_standard_statement(self):
        expected = {11, 13, 16, 20, 24, 32, 44, 56, 96}
        self.assertEqual(DEFAULT_RAMP, expected)
        self.assertIn(56, DEFAULT_RAMP)

    def test_load_ramp_from_sizes_directive(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_file = Path(tmp_dir) / "spec_lock.md"
            spec_file.write_text(
                "## canvas\n- viewBox: 0 0 1280 720\n\n- sizes: [11, 13, 16, 20, 24, 32, 44, 56, 96]\n",
                encoding="utf-8",
            )
            ramp = load_ramp(str(spec_file))
            self.assertEqual(ramp, {11, 13, 16, 20, 24, 32, 44, 56, 96})

    def test_load_ramp_from_role_mapping_with_comments(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_file = Path(tmp_dir) / "spec_lock.md"
            spec_file.write_text(
                "## typography\n"
                "- body: 16 # 正文标准\n"
                "- statement: 56 # 跨页统摄主句\n"
                "- cover: 96\n",
                encoding="utf-8",
            )
            ramp = load_ramp(str(spec_file))
            self.assertEqual(ramp, {16, 56, 96})

    def test_load_ramp_nonexistent_fallback(self):
        ramp = load_ramp("/non_existent_spec_lock_path.md")
        self.assertEqual(ramp, DEFAULT_RAMP)

    def test_load_spec_roles_with_inline_comments(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_file = Path(tmp_dir) / "spec_lock.md"
            spec_file.write_text(
                "## typography\n"
                "- body: 16 # 正文字号\n"
                "- statement: 56 # 统一主句\n",
                encoding="utf-8",
            )
            roles = load_spec_roles(str(spec_file))
            self.assertEqual(roles, {"body": 16, "statement": 56})

    def test_load_spec_roles_nonexistent_returns_empty(self):
        roles = load_spec_roles("/non_existent_spec_lock_path.md")
        self.assertEqual(roles, {})

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


class TestCanvasFromSpec(unittest.TestCase):
    """画布尺寸/margin 从 spec_lock.md 自动读取。"""

    def _write_spec(self, tmp_dir, content):
        spec_file = Path(tmp_dir) / "spec_lock.md"
        spec_file.write_text(content, encoding="utf-8")
        return str(spec_file)

    def test_canvas_1920x1080(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_spec(d, "## canvas\n- viewBox: 0 0 1920 1080\n- margin: 144px\n")
            self.assertEqual(load_canvas_from_spec(p), (1920, 1080))

    def test_canvas_default_1280x720(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_spec(d, "## canvas\n- viewBox: 0 0 1280 720\n")
            self.assertEqual(load_canvas_from_spec(p), (1280, 720))

    def test_canvas_missing_viewbox(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_spec(d, "## canvas\n- format: PPT 16:9\n")
            self.assertEqual(load_canvas_from_spec(p), (None, None))

    def test_canvas_nonexistent_file(self):
        self.assertEqual(load_canvas_from_spec("/non_existent_spec.md"), (None, None))

    def test_margin_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_spec(d, "## canvas\n- margin: 96px\n")
            self.assertEqual(load_margin_from_spec(p), 96)

    def test_margin_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_spec(d, "## canvas\n- viewBox: 0 0 1280 720\n")
            self.assertIsNone(load_margin_from_spec(p))

    def test_margin_nonexistent_file(self):
        self.assertIsNone(load_margin_from_spec("/non_existent_spec.md"))


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

    def test_decorative_watermark_excluded(self):
        """装饰水印（如 225px 页码）不是主句：两页主句同为 56px 时应判一致。"""
        mk = lambda wm: (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<text font-size="56">页面主句</text>'
            f'<text font-size="225" data-decorative="true" opacity="0.08">{wm}</text>'
            "</svg>"
        )
        svg_slides = [
            ("01_cover", ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-size="96">封面</text></svg>')),
            ("02_slide", ET.fromstring(mk("02"))),
            ("03_slide", ET.fromstring(mk("03"))),
        ]
        ok, msg = check_statement_consistency(svg_slides, expected_sz=56)
        self.assertTrue(ok, msg)
        self.assertIn("严格对齐 (56px)", msg)

    def test_decorative_watermark_does_not_mask_drift(self):
        """水印不得掩盖真实漂移：主句 56px vs 44px 即使都有 225px 水印也要报漂移。"""
        mk = lambda txt, wm: (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            f'<text font-size="{txt[0]}">{txt[1]}</text>'
            f'<text font-size="225" data-decorative="true" opacity="0.08">{wm}</text>'
            "</svg>"
        )
        svg_slides = [
            ("01_cover", ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-size="96">封面</text></svg>')),
            ("02_slide", ET.fromstring(mk(("56", "第二页主句"), "02"))),
            ("03_slide", ET.fromstring(mk(("44", "第三页主句漂移"), "03"))),
        ]
        ok, msg = check_statement_consistency(svg_slides, expected_sz=56)
        self.assertFalse(ok)
        self.assertIn("主句字号漂移", msg)
        self.assertIn("03_slide", msg)


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

    def test_explicit_project_dir_prefers_latest_svg_version(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "my_proj"
            create_test_svg(proj / "svg_output" / "01.svg")
            create_test_svg(proj / "svg_output_v4" / "01.svg")
            resolved = resolve_layout_dirs(str(proj))
            self.assertEqual(resolved, [(proj / "svg_output_v4").resolve()])

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

    def test_auto_discovery_from_projects_prefers_latest_svg_version(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "test_p"
            create_test_svg(proj / "svg_output" / "01.svg")
            create_test_svg(proj / "svg_output_v4" / "01.svg")
            resolved = resolve_layout_dirs(None, base_dir=base)
            self.assertEqual(resolved, [(proj / "svg_output_v4").resolve()])

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

    def test_run_qa_layout_with_default_ramp_statement_56(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "isolated_svgs"
            create_test_svg(svg_dir / "01.svg", title_sz=56, body_sz=16)
            # 传入不存在的 spec 路径，验证默认阶梯是否包含 56 且判定通过
            non_exist_spec = Path(tmp_dir) / "no_spec.md"
            ok = run_qa_layout(svg_dir, spec_path=non_exist_spec)
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

    def test_cli_quiet_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "svgs"
            create_test_svg(svg_dir / "01.svg", title_sz=56, body_sz=16)
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
                code = main([str(svg_dir), "--quiet"])
            self.assertEqual(code, 0)
            self.assertEqual(buf_out.getvalue(), "")
            self.assertEqual(buf_err.getvalue(), "")

            # -q 短参数测试
            buf_out2 = io.StringIO()
            buf_err2 = io.StringIO()
            with patch("sys.stdout", buf_out2), patch("sys.stderr", buf_err2):
                code2 = main([str(svg_dir), "-q"])
            self.assertEqual(code2, 0)
            self.assertEqual(buf_out2.getvalue(), "")
            self.assertEqual(buf_err2.getvalue(), "")

    def test_cli_verbose_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "svgs"
            create_test_svg(svg_dir / "01.svg", title_sz=56, body_sz=16)
            buf_out = io.StringIO()
            with patch("sys.stdout", buf_out):
                code = main([str(svg_dir), "-v"])
            self.assertEqual(code, 0)
            self.assertIn("ALL CLEAR", buf_out.getvalue())

            buf_out2 = io.StringIO()
            with patch("sys.stdout", buf_out2):
                code2 = main([str(svg_dir), "--verbose"])
            self.assertEqual(code2, 0)
            self.assertIn("ALL CLEAR", buf_out2.getvalue())

    def test_cli_quiet_error_silenced(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
            code = main(["/path/not_exist_xyz123", "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

    def test_cli_with_render_dir_nonexistent_target(self):
        buf_err = io.StringIO()
        with patch("sys.stderr", buf_err):
            code = main(["/non_existent_target_123", "some_render_dir"])
        self.assertEqual(code, 1)
        self.assertIn("指定的目标路径不存在", buf_err.getvalue())

        # quiet 模式静默
        buf_err_q = io.StringIO()
        with patch("sys.stderr", buf_err_q):
            code_q = main(["/non_existent_target_123", "some_render_dir", "-q"])
        self.assertEqual(code_q, 1)
        self.assertEqual(buf_err_q.getvalue(), "")


class TestContrastPolarity(unittest.TestCase):
    def test_light_background_dark_small_text_uses_reverse_polarity(self):
        pixels = np.full((80, 220, 3), 255, dtype=np.uint8)
        pixels[18:22, 10:90] = 17
        image = Image.fromarray(pixels, mode="RGB")
        root = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text x="10" y="30" font-size="16">small</text></svg>')
        rows = check_contrast(image, root, polarity="light")
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0][0], 4.5)


class TestQaLayoutProgrammaticAPI(unittest.TestCase):
    """测试 qa_layout / run_qa_layout / qa_single_layout 可编程接口。"""

    def test_alias_equivalence(self):
        self.assertIs(qa_layout, run_qa_layout)

    def test_alias_run_qa_single_layout(self):
        self.assertIs(run_qa_single_layout, qa_single_layout)

    def test_qa_single_layout_none_returns_false(self):
        self.assertFalse(qa_single_layout(None, verbose=False))

    def test_qa_single_layout_path_and_str(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "svgs"
            create_test_svg(svg_dir / "01.svg", title_sz=56, body_sz=16)
            self.assertTrue(qa_single_layout(svg_dir, verbose=False))
            self.assertTrue(qa_single_layout(str(svg_dir), verbose=False))

    def test_qa_single_layout_verbose_false_silence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_dir = Path(tmp_dir) / "svgs"
            create_test_svg(svg_dir / "01.svg", title_sz=56, body_sz=16)
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
                res = qa_single_layout(svg_dir, verbose=False)
            self.assertTrue(res)
            self.assertEqual(buf_out.getvalue(), "")
            self.assertEqual(buf_err.getvalue(), "")

    def test_qa_single_layout_nonexistent_returns_false(self):
        res = qa_single_layout("/non_existent_svg_dir_99999", verbose=False)
        self.assertFalse(res)

    def test_qa_single_layout_non_svg_file_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            txt_file = Path(tmp_dir) / "test.txt"
            txt_file.touch()
            res = qa_single_layout(txt_file, verbose=False)
            self.assertFalse(res)

    def test_qa_single_layout_single_svg_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_file = Path(tmp_dir) / "01.svg"
            create_test_svg(svg_file, title_sz=56, body_sz=16)
            self.assertTrue(qa_single_layout(svg_file, verbose=False))
            self.assertTrue(qa_single_layout(str(svg_file), verbose=False))

    def test_qa_single_layout_project_dir_with_svg_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj_dir = Path(tmp_dir) / "my_project"
            svg_out = proj_dir / "svg_output"
            create_test_svg(svg_out / "01.svg", title_sz=56, body_sz=16)
            self.assertTrue(qa_single_layout(proj_dir, verbose=False))

    def test_run_qa_layout_project_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj_dir = Path(tmp_dir) / "my_project"
            svg_out = proj_dir / "svg_output"
            create_test_svg(svg_out / "01.svg", title_sz=56, body_sz=16)
            self.assertTrue(run_qa_layout(proj_dir, verbose=False))
            self.assertTrue(run_qa_layout(str(proj_dir), verbose=False))

    def test_run_qa_layout_empty_directory_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertFalse(run_qa_layout(tmp_dir, verbose=False))

    def test_run_qa_layout_nonexistent_returns_false(self):
        self.assertFalse(run_qa_layout("/non_existent_layout_dir_99999", verbose=False))


if __name__ == "__main__":
    unittest.main()


class TestStageEarly(unittest.TestCase):
    """--stage early 前 N 页方法样本 + severity 分级。"""

    def test_severity_map(self):
        self.assertEqual(SEVERITY["overflow"], "error")
        self.assertEqual(SEVERITY["collision"], "error")
        self.assertEqual(SEVERITY["contrast"], "error")
        self.assertEqual(SEVERITY["dup_images"], "error")
        self.assertEqual(SEVERITY["typescale"], "warning")
        self.assertEqual(SEVERITY["backdrop"], "warning")
        self.assertEqual(SEVERITY["panel"], "warning")
        self.assertEqual(SEVERITY["statement"], "warning")

    def test_early_page_filtering(self):
        import re
        with tempfile.TemporaryDirectory() as d:
            svg_dir = Path(d)
            for i in range(1, 7):
                (svg_dir / ("%02d_p.svg" % i)).write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1280" height="720"/></svg>',
                    encoding="utf-8")
            files = sorted(svg_dir.glob("*.svg"))
            def _page_key(p):
                m = re.match(r"(\d+)_", p.stem)
                return int(m.group(1)) if m else 9999
            early = sorted(files, key=_page_key)[:3]
            self.assertEqual([p.stem for p in early], ["01_p", "02_p", "03_p"])


class TestRoleDiscipline(unittest.TestCase):
    """breathing 页禁止多卡片网格（role 纪律）。"""

    def _svg(self, n_cards):
        rects = "".join(
            '<rect x="%d" y="100" width="400" height="300" fill="#eee"/>' % (100 + i * 450)
            for i in range(n_cards))
        return ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1920" height="1080" fill="#fff"/>%s</svg>' % rects)

    def _map(self):
        return {"P04": {"role": "Typographic Hero", "rhythm": "breathing"},
                "P05": {"role": "Product Grid", "rhythm": "dense"}}

    def test_breathing_violation(self):
        ok, msg = check_role_discipline(self._svg(3), "P04", self._map(), 1920, 1080)
        self.assertFalse(ok)
        self.assertIn("违反 role 纪律", msg)

    def test_breathing_ok(self):
        ok, _ = check_role_discipline(self._svg(2), "P04", self._map(), 1920, 1080)
        self.assertTrue(ok)

    def test_dense_skipped(self):
        ok, msg = check_role_discipline(self._svg(5), "P05", self._map(), 1920, 1080)
        self.assertTrue(ok)
        self.assertIn("跳过", msg)

    def test_unknown_page_skipped(self):
        ok, _ = check_role_discipline(self._svg(5), "P99", self._map(), 1920, 1080)
        self.assertTrue(ok)

    def test_max_cards_constant(self):
        self.assertEqual(BREATHING_MAX_CARDS, 2)


class TestQaLayoutSubdirAndSpecResolution(unittest.TestCase):
    """测试 qa_layout 对子目录、规范文件及多版本 spec 的自适应探查。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.proj = Path(self.td.name) / "test_proj"
        self.svg_dir = self.proj / "svg_output"
        self.render_dir = self.proj / "render"
        self.images_dir = self.proj / "images"
        self.svg_dir.mkdir(parents=True)
        self.render_dir.mkdir(parents=True)
        self.images_dir.mkdir(parents=True)

        self.spec_file = self.proj / "spec_lock.md"
        self.spec_file.write_text(
            "# spec\n## canvas\n- viewBox: 0 0 1280 720\n- margin: 60px\n## typography\n- sizes: [16, 24, 32, 56]\n- statement: 56\n",
            encoding="utf-8",
        )
        svg_content = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
            '<rect width="1280" height="720" fill="#000"/>'
            '<text x="60" y="100" font-size="56" fill="#fff">主标题测试</text>'
            "</svg>"
        )
        (self.svg_dir / "01_cover.svg").write_text(svg_content, encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def test_resolve_project_dir_subfolders_and_file(self):
        self.assertEqual(resolve_project_dir(self.svg_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.render_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.images_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.spec_file), self.proj.resolve())

    def test_resolve_layout_dirs_from_subfolder_and_spec_file(self):
        # 传入子目录 render 或 images
        res_render = resolve_layout_dirs(self.render_dir)
        self.assertEqual(res_render, [self.svg_dir.resolve()])
        res_images = resolve_layout_dirs(self.images_dir)
        self.assertEqual(res_images, [self.svg_dir.resolve()])

        # 传入 spec_lock.md 文件
        res_spec = resolve_layout_dirs(self.spec_file)
        self.assertEqual(res_spec, [self.svg_dir.resolve()])

    def test_qa_single_layout_from_subfolder_and_file(self):
        # 从子目录运行 qa_single_layout
        ok = qa_single_layout(self.render_dir, verbose=False)
        self.assertTrue(ok)

        # 从 spec 文件运行 qa_single_layout
        ok_spec = qa_single_layout(self.spec_file, verbose=False)
        self.assertTrue(ok_spec)

    def test_qa_single_layout_with_dir_spec_path(self):
        # 将 spec_path 指向项目根目录，应自适应解析为 spec_lock.md
        ok = qa_single_layout(self.svg_dir, spec_path=self.proj, verbose=False)
        self.assertTrue(ok)

    def test_cli_from_subfolder_and_spec_file(self):
        self.assertEqual(main([str(self.render_dir)]), 0)
        self.assertEqual(main([str(self.spec_file)]), 0)

    def test_resolve_project_dir_render_cards_and_output(self):
        render_cards = self.proj / "render_cards"
        render_cards.mkdir(parents=True, exist_ok=True)
        output_dir = self.proj / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        self.assertEqual(resolve_project_dir(render_cards), self.proj.resolve())
        self.assertEqual(resolve_project_dir(output_dir), self.proj.resolve())

    def test_resolve_project_dir_fallback_without_cpm(self):
        from unittest.mock import patch
        with patch("scripts.qa_layout._cpm_resolve_project_dir", None):
            self.assertEqual(resolve_project_dir(self.svg_dir), self.proj.resolve())
            self.assertEqual(resolve_project_dir(self.spec_file), self.proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=self.svg_dir), self.proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=self.spec_file), self.proj.resolve())

    def test_resolve_project_dir_base_dir(self):
        self.assertEqual(resolve_project_dir(base_dir=self.svg_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(base_dir=self.render_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(base_dir=self.images_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(base_dir=self.spec_file), self.proj.resolve())



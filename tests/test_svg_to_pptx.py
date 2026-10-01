#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_svg_to_pptx.py
=========================
测试 svg_to_pptx.py：SVG 解析 / 背景剥离 / 单位换算 / PPTX 构建 / CLI。

端到端构建测试需要 rsvg-convert 与 python-pptx（缺失则跳过）；
qa_pptx 回读集成测试复用仓库既有门禁（默认字阶 [11,13,16,20,24,32,44,56,96]，
fixture 字号只用 20/96，保证门禁可过）。
"""

import io
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.svg_to_pptx import (
    TextItem,
    check_dependencies,
    estimate_width_px,
    extract_texts,
    main,
    parse_color,
    parse_viewbox,
    render_background,
    resolve_svg_dir,
    rsvg_available,
    strip_body_texts,
    build_pptx,
    PX_TO_PT,
)

try:
    from scripts.svg_to_pptx import _PPTX_OK
except ImportError:  # pragma: no cover
    _PPTX_OK = False

try:
    from scripts.qa_pptx import run_qa_pptx
    _QA_OK = True
except ImportError:  # pragma: no cover
    _QA_OK = False

SVG_TMPL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" width="1920" height="1080">
<rect x="0" y="0" width="1920" height="1080" fill="{bg}"/>
{texts}
</svg>"""

BG_COLORS = ("#F5F2EC", "#EDE8DC", "#F0EDE6")

PAGE1_TEXTS = """
<text x="144" y="200" font-family="Noto Serif CJK SC" font-size="96" fill="#1A1A1A" font-weight="900">标题一</text>
<text x="960" y="400" font-family="Noto Sans CJK SC" font-size="20" fill="#575046" text-anchor="middle" letter-spacing="4">副标题文字</text>
<text x="1776" y="1050" font-family="Bodoni Moda" font-size="225" fill="#1A1A1A" opacity="0.08" text-anchor="end" data-decorative="true">01</text>
"""

PAGE2_TEXTS = """
<text x="1776" y="200" font-family="Noto Serif CJK SC" font-size="96" fill="#8C2F1B" font-weight="700" text-anchor="end">标题二</text>
<text x="144" y="400" font-family="Noto Sans CJK SC" font-size="20" fill="#1A1A1A">正文内容行</text>
"""

PAGE3_TEXTS = """
<text x="144" y="200" font-family="Noto Serif CJK SC" font-size="96" fill="#1A1A1A">标题三</text>
<text x="144" y="400" font-family="Noto Sans CJK SC" font-size="20" fill="#2F5D8C" font-style="italic">斜体说明</text>
"""


def _write_fixture(tmp: Path) -> list[Path]:
    files = []
    for i, (texts, bg) in enumerate(zip((PAGE1_TEXTS, PAGE2_TEXTS, PAGE3_TEXTS), BG_COLORS), start=1):
        p = tmp / f"0{i}_page{i}.svg"
        p.write_text(SVG_TMPL.format(texts=texts, bg=bg), encoding="utf-8")
        files.append(p)
    return files


class TestParse(unittest.TestCase):
    def test_parse_viewbox(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.svg"
            p.write_text(SVG_TMPL.format(texts="", bg="#F5F2EC"), encoding="utf-8")
            self.assertEqual(parse_viewbox(p), (1920.0, 1080.0))

    def test_parse_viewbox_fallback_wh(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "b.svg"
            p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"></svg>',
                         encoding="utf-8")
            self.assertEqual(parse_viewbox(p), (1280.0, 720.0))

    def test_parse_color(self):
        self.assertEqual(parse_color("#1A1A1A"), (26, 26, 26))
        self.assertEqual(parse_color("#fff"), (255, 255, 255))
        self.assertEqual(parse_color("#8C2F1B"), (140, 47, 27))

    def test_px_to_pt_constant(self):
        self.assertAlmostEqual(PX_TO_PT, 0.75)


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.files = _write_fixture(Path(self.td.name))

    def tearDown(self):
        self.td.cleanup()

    def test_decorative_excluded(self):
        texts = extract_texts(self.files[0])
        self.assertEqual(len(texts), 2)
        self.assertNotIn("01", [t.text for t in texts])

    def test_fields_page1(self):
        texts = extract_texts(self.files[0])
        t0, t1 = texts
        self.assertEqual(t0.text, "标题一")
        self.assertEqual(t0.size_px, 96)
        self.assertEqual(t0.anchor, "start")
        self.assertTrue(t0.bold)
        self.assertFalse(t0.italic)
        self.assertEqual(t0.fill, "#1A1A1A")
        self.assertEqual(t1.anchor, "middle")
        self.assertEqual(t1.letter_spacing_px, 4)
        self.assertEqual(t1.family, "Noto Sans CJK SC")

    def test_fields_page2_end_anchor_bold(self):
        (t0, t1) = extract_texts(self.files[1])
        self.assertEqual(t0.anchor, "end")
        self.assertTrue(t0.bold)
        self.assertEqual(t0.fill, "#8C2F1B")
        self.assertFalse(t1.bold)

    def test_italic(self):
        texts = extract_texts(self.files[2])
        self.assertTrue(texts[1].italic)

    def test_empty_text_skipped(self):
        p = Path(self.td.name) / "empty.svg"
        p.write_text(SVG_TMPL.format(
            texts='<text x="10" y="10" font-size="20">   </text>', bg="#F5F2EC"), encoding="utf-8")
        self.assertEqual(extract_texts(p), [])


class TestStrip(unittest.TestCase):
    def test_body_texts_removed_decorative_kept(self):
        with tempfile.TemporaryDirectory() as td:
            files = _write_fixture(Path(td))
            out = strip_body_texts(files[0]).decode("utf-8")
            self.assertNotIn("标题一", out)
            self.assertNotIn("副标题文字", out)
            self.assertIn("01", out)          # 装饰水印保留在背景层
            self.assertIn("<rect", out)       # 非文本元素不受影响

    def test_stripped_svg_still_valid_xml(self):
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as td:
            files = _write_fixture(Path(td))
            root = ET.fromstring(strip_body_texts(files[0]))
            self.assertTrue(root.tag.endswith("svg"))


class TestWidth(unittest.TestCase):
    def test_estimate_positive(self):
        item = TextItem("标题一", 144, 200, 96, "Noto Serif CJK SC",
                        "#1A1A1A", True, False, "start", 0)
        w = estimate_width_px(item)
        self.assertGreater(w, 0)

    def test_letter_spacing_increases_width(self):
        base = TextItem("副标题文字", 960, 400, 20, "Noto Sans CJK SC",
                        "#575046", False, False, "middle", 0)
        spaced = TextItem("副标题文字", 960, 400, 20, "Noto Sans CJK SC",
                          "#575046", False, False, "middle", 10)
        self.assertGreater(estimate_width_px(spaced), estimate_width_px(base))


class TestResolve(unittest.TestCase):
    def test_explicit_svg_dir(self):
        with tempfile.TemporaryDirectory() as td:
            _write_fixture(Path(td))
            svg_dir, proj = resolve_svg_dir(td)
            self.assertEqual(svg_dir, Path(td).resolve())

    def test_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            resolve_svg_dir("/tmp/definitely-not-here-xyz")


class TestCheck(unittest.TestCase):
    def test_check_returns_tuple(self):
        ok, problems = check_dependencies()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(problems, list)
        self.assertEqual(rsvg_available(), shutil_which_rsvg())

    def test_main_check_mode(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--check"])
        self.assertIn(code, (0, 1))


def shutil_which_rsvg():
    import shutil
    return shutil.which("rsvg-convert") is not None


@unittest.skipUnless(_PPTX_OK and shutil_which_rsvg(), "需要 python-pptx + rsvg-convert")
class TestBuildEndToEnd(unittest.TestCase):
    def test_build_three_pages(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            files = _write_fixture(tdp)
            out = tdp / "out.pptx"
            stats = build_pptx(files, out, fmt="ppt169")
            self.assertEqual(stats["pages"], 3)
            self.assertGreater(stats["texts"], 0)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 0)

            with zipfile.ZipFile(out) as z:
                names = z.namelist()
                slides = [n for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
                self.assertEqual(len(slides), 3)
                media = [n for n in names if n.startswith("ppt/media/")]
                self.assertEqual(len(media), 3)
                self.assertTrue(all(n.endswith(".png") for n in media))
                # 每页既有图片层也有文本层
                import xml.etree.ElementTree as ET
                NS_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
                for s in slides:
                    root = ET.fromstring(z.read(s))
                    pics = root.findall(f".//{NS_P}pic")
                    sps = root.findall(f".//{NS_P}sp")
                    self.assertGreater(len(pics), 0, s)
                    self.assertGreater(len(sps), 0, s)
                # 文本内容真实写入（可编辑，非纯图片）
                all_text = " ".join(
                    ET.tostring(ET.fromstring(z.read(s)), encoding="unicode") for s in slides)
                self.assertIn("标题一", all_text)
                self.assertIn("标题二", all_text)

    def test_build_empty_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                build_pptx([], Path(td) / "x.pptx")

    def test_build_bad_format_raises(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            files = _write_fixture(tdp)
            with self.assertRaises(ValueError):
                build_pptx(files, tdp / "x.pptx", fmt="ppt999")

    def test_render_background_png_valid(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            files = _write_fixture(tdp)
            png = tdp / "bg.png"
            render_background(strip_body_texts(files[0]), png, 1920, 1080)
            self.assertTrue(png.is_file())
            self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    @unittest.skipUnless(_QA_OK, "需要 qa_pptx")
    def test_qa_pptx_readback_passes(self):
        """生成的 pptx 必须通过仓库既有 7 项回读门禁。"""
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            files = _write_fixture(tdp)
            out = tdp / "out.pptx"
            build_pptx(files, out)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = run_qa_pptx(out, verbose=False)
            self.assertTrue(ok, f"qa_pptx 回读未通过:\n{buf.getvalue()}")

    def test_main_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            _write_fixture(tdp)
            out = tdp / "cli.pptx"
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main([str(tdp), "-o", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()

"""tests/test_drift_report.py -- spec 漂移可视化对比报告（第 21 轮）。"""
from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.drift_report import build_report, page_statement, render_html

SPEC = """# Execution Lock -- test
## canvas
- viewBox: 0 0 1920 1080
## typography
- sizes: [20, 26, 56, 84]
- statement: 56
"""

SVG_TMPL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">
{texts}
</svg>"""


def _text(x: int, y: int, size: int, content: str, decorative: bool = False) -> str:
    dec = ' data-decorative="true"' if decorative else ""
    return f'<text x="{x}" y="{y}" font-size="{size}"{dec}>{content}</text>'


class DriftReportTestBase(unittest.TestCase):
    def make_project(self, td: str) -> Path:
        proj = Path(td) / "proj"
        svg_dir = proj / "svg_output"
        svg_dir.mkdir(parents=True)
        (proj / "spec_lock.md").write_text(SPEC, encoding="utf-8")
        (svg_dir / "01_cover.svg").write_text(
            SVG_TMPL.format(texts=_text(100, 500, 225, "封面大标题")), encoding="utf-8")
        (svg_dir / "02_ok.svg").write_text(
            SVG_TMPL.format(texts=_text(100, 500, 56, "对齐的主句") + _text(100, 600, 20, "正文小字")),
            encoding="utf-8")
        (svg_dir / "03_drift.svg").write_text(
            SVG_TMPL.format(texts=_text(100, 500, 72, "漂移的主句") + _text(100, 600, 20, "正文小字")),
            encoding="utf-8")
        (svg_dir / "04_deco.svg").write_text(
            SVG_TMPL.format(texts=_text(1700, 1000, 225, "9", decorative=True)
                            + _text(100, 500, 56, "带水印的对齐页")),
            encoding="utf-8")
        return proj


class TestPageStatement(DriftReportTestBase):
    def test_detects_statement(self):
        root = ET.fromstring(SVG_TMPL.format(texts=_text(100, 500, 56, "主句")))
        self.assertEqual(page_statement(root), (56, "主句"))

    def test_ignores_decorative_watermark(self):
        root = ET.fromstring(SVG_TMPL.format(
            texts=_text(1700, 1000, 225, "9", decorative=True) + _text(100, 500, 56, "真主句")))
        self.assertEqual(page_statement(root), (56, "真主句"))

    def test_none_when_no_large_text(self):
        root = ET.fromstring(SVG_TMPL.format(texts=_text(100, 500, 20, "小字")))
        self.assertIsNone(page_statement(root))


class TestBuildReport(DriftReportTestBase):
    def test_drift_pages_detected(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            rep = build_report(proj)
            self.assertEqual(rep["spec_file"], "spec_lock.md")
            self.assertEqual(rep["expected_statement"], 56)
            self.assertEqual(rep["n_drift"], 1)
            self.assertEqual(rep["drift_pages"], ["03_drift"])
            by_page = {p["page"]: p for p in rep["pages"]}
            self.assertTrue(by_page["01_cover"]["cover"])
            self.assertEqual(by_page["02_ok"]["statement_size"], 56)
            self.assertFalse(by_page["02_ok"]["drift"])
            # 装饰水印 225px 不得掩盖真实主句
            self.assertEqual(by_page["04_deco"]["statement_size"], 56)
            self.assertFalse(by_page["04_deco"]["drift"])

    def test_off_ramp_detected(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            rep = build_report(proj)
            # 72px 不在字阶 [20,26,56,84] 内
            self.assertIn(72, rep["off_ramp_sizes"])
            self.assertNotIn(56, rep["off_ramp_sizes"])

    def test_missing_spec_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                build_report(Path(td))


class TestRenderHtml(DriftReportTestBase):
    def test_html_contains_badges_and_bars(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            rep = build_report(proj)
            h = render_html(rep)
            self.assertIn("DRIFT", h)
            self.assertIn("漂移的主句", h)
            self.assertIn("03_drift", h)
            self.assertIn("spec 字阶", h)
            # 自包含：无外部资源引用
            self.assertNotIn("http://", h)
            self.assertNotIn("https://", h)
            self.assertIn("<!DOCTYPE html>", h)


if __name__ == "__main__":
    unittest.main()

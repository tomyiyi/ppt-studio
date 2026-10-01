"""tests/test_drift_report.py -- spec 漂移可视化对比报告（第 21 轮）。"""
from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.drift_report import build_report, main, page_statement, render_html, render_markdown

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


class TestRenderMarkdown(DriftReportTestBase):
    def test_md_has_decision_options_per_drift_page(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            rep = build_report(proj)
            md = render_markdown(rep)
            # 决策简报头 + 结论
            self.assertIn("# Spec 漂移决策简报", md)
            self.assertIn("1 页主句漂移（03_drift）", md)
            # 每页漂移：原文、实际 vs 期望、A/B 显式选项
            self.assertIn("### 03_drift", md)
            self.assertIn("「漂移的主句」", md)
            self.assertIn("实际 72px vs 期望 56px（+16px）", md)
            self.assertIn("选项 A（回齐 spec）", md)
            self.assertIn("选项 B（更新 spec）", md)
            self.assertIn("56px", md)  # A 选项回齐到期望字号
            self.assertIn("spec_lock.md", md)

    def test_md_ramp_note_distinguishes_on_vs_off_ramp(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            rep = build_report(proj)
            md = render_markdown(rep)
            # 72px 不在字阶 [20,26,56,84] → 必须提示先查来源
            self.assertIn("不在 spec 字阶内", md)

    def test_md_on_ramp_drift_note(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            svg_dir = proj / "svg_output"
            # 84px 在字阶内但不是 statement(56) → 纯档位选择问题
            (svg_dir / "05_onramp.svg").write_text(
                SVG_TMPL.format(texts=_text(100, 500, 84, "在阶漂移")), encoding="utf-8")
            rep = build_report(proj)
            md = render_markdown(rep)
            self.assertIn("2 页主句漂移", md)
            self.assertIn("05_onramp", md)
            self.assertIn("在 spec 字阶内（纯 statement 档位选择问题）", md)

    def test_md_no_drift_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"
            svg_dir = proj / "svg_output"
            svg_dir.mkdir(parents=True)
            (proj / "spec_lock.md").write_text(SPEC, encoding="utf-8")
            (svg_dir / "02_ok.svg").write_text(
                SVG_TMPL.format(texts=_text(100, 500, 56, "对齐的主句")), encoding="utf-8")
            rep = build_report(proj)
            md = render_markdown(rep)
            self.assertIn("无主句漂移，无需决策", md)
            self.assertNotIn("## 需决策", md)

    def test_md_off_ramp_section(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            rep = build_report(proj)
            md = render_markdown(rep)
            self.assertIn("脱离字阶的字号", md)
            self.assertIn("72", md)

    def test_md_ok_pages_listed(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            rep = build_report(proj)
            md = render_markdown(rep)
            self.assertIn("无需决策（主句合规）", md)
            self.assertIn("02_ok（56px）", md)
            # 封面不进合规清单
            self.assertNotIn("01_cover", md.split("## 无需决策（主句合规）")[1])

    def test_cli_format_md_writes_markdown_file(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self.make_project(td)
            out = Path(td) / "brief.md"
            rc = main([str(proj), "--format", "md", "-o", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())
            body = out.read_text(encoding="utf-8")
            self.assertIn("# Spec 漂移决策简报", body)
            self.assertNotIn("<!DOCTYPE html>", body)


if __name__ == "__main__":
    unittest.main()

"""tests/test_brief_to_spec.py -- brief -> spec 初稿管线（第 22 轮，全 mock 不调 Agnes）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.brief_to_spec import (build_spec_prompt, draft_spec,
                                     validate_spec_draft, _strip_fences, main)

GOOD_DRAFT = """# Execution Lock — 测试主题（初稿，待人工审定）
## canvas
- viewBox: 0 0 1920 1080
- margin: 144px
- grid: 12 栏
## typography
- sizes: [20, 26, 36, 42, 72, 84, 180, 225]
- statement: 84
- font_body: Noto Sans CJK SC
## page_map
- P01: role=Cover, rhythm=anchor
- P02: role=Trend Essay, rhythm=dense
- P03: role=Detail Macro, rhythm=dense
- P04: role=Typographic Hero, rhythm=breathing
- P05: role=Product Grid, rhythm=dense
- P06: role=Closing, rhythm=anchor
## details
- caption_rule: 每张配图配 20px 全大写图注
- no_frames: 禁止任何框线分区
"""

BRIEF = """# 2026 秋冬针织趋势（测试简报）
## 核心结论
粗针织回潮 [1]，环保纱线占比提升 [2]。
## 分项趋势
### 粗针织
 oversize 粗针织毛衣在秀场占比上升 [1]。
### 环保纱线
再生羊毛使用率提高 [2]。
## 来源清单
[1] 测试来源一
[2] 测试来源二
"""


class TestBuildSpecPrompt(unittest.TestCase):
    def test_iron_rules_present(self):
        p = build_spec_prompt("测试主题", BRIEF)
        self.assertIn("- sizes: [20, 26, 36, 42, 72, 84, 180, 225]", p)
        self.assertIn("- statement: 84", p)
        self.assertIn("- viewBox: 0 0 1920 1080", p)
        self.assertIn("只输出 markdown 本身", p)
        self.assertIn("TODO", p)  # 禁止占位符的铁律被写进 prompt

    def test_topic_and_brief_injected(self):
        p = build_spec_prompt("针织", BRIEF)
        self.assertIn("针织", p)
        self.assertIn("粗针织回潮", p)


class TestValidateSpecDraft(unittest.TestCase):
    def test_good_draft_passes(self):
        r = validate_spec_draft(GOOD_DRAFT)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["pages"], 6)

    def test_tampered_ramp_fails(self):
        r = validate_spec_draft(GOOD_DRAFT.replace(
            "- sizes: [20, 26, 36, 42, 72, 84, 180, 225]",
            "- sizes: [20, 26, 36]"))
        self.assertFalse(r["ok"])
        self.assertTrue(any("字阶" in p for p in r["problems"]))

    def test_non_sequential_pages_fail(self):
        bad = GOOD_DRAFT.replace("- P03: role=Detail Macro, rhythm=dense\n", "")
        r = validate_spec_draft(bad)
        self.assertFalse(r["ok"])
        self.assertTrue(any("不连续" in p for p in r["problems"]))

    def test_bad_rhythm_fails(self):
        bad = GOOD_DRAFT.replace("rhythm=dense", "rhythm=chaotic", 1)
        r = validate_spec_draft(bad)
        self.assertFalse(r["ok"])
        self.assertTrue(any("rhythm" in p for p in r["problems"]))

    def test_placeholder_fails(self):
        r = validate_spec_draft(GOOD_DRAFT.replace("Noto Sans CJK SC", "TODO 选字体"))
        self.assertFalse(r["ok"])

    def test_missing_section_fails(self):
        r = validate_spec_draft(GOOD_DRAFT.replace("## details", "## misc"))
        self.assertFalse(r["ok"])
        self.assertTrue(any("details" in p for p in r["problems"]))


class TestDraftSpecChain(unittest.TestCase):
    def test_full_chain_mocked(self):
        with tempfile.TemporaryDirectory() as td:
            brief = Path(td) / "brief.md"
            brief.write_text(BRIEF, encoding="utf-8")
            out = Path(td) / "spec_draft.md"
            with mock.patch("scripts.brief_to_spec.call_agnes",
                            return_value=GOOD_DRAFT) as ca:
                r = draft_spec(str(brief), output=str(out))
            ca.assert_called_once()
            self.assertTrue(r["validation"]["ok"])
            self.assertTrue(out.is_file())

    def test_invalid_draft_reported(self):
        with tempfile.TemporaryDirectory() as td:
            brief = Path(td) / "brief.md"
            brief.write_text(BRIEF, encoding="utf-8")
            with mock.patch("scripts.brief_to_spec.call_agnes",
                            return_value="# 乱写\n无结构"):
                r = draft_spec(str(brief))
            self.assertFalse(r["validation"]["ok"])
            self.assertTrue(r["validation"]["problems"])

    def test_strip_fences(self):
        fenced = "```markdown\n" + GOOD_DRAFT + "\n```\n"
        self.assertEqual(_strip_fences(fenced).strip(), GOOD_DRAFT.strip())
        self.assertEqual(_strip_fences(GOOD_DRAFT), GOOD_DRAFT)

    def test_fenced_draft_auto_stripped_in_chain(self):
        # 实跑复现：Agnes 整体包裹 ```markdown 围栏，程序侧剥离后校验通过
        with tempfile.TemporaryDirectory() as td:
            brief = Path(td) / "brief.md"
            brief.write_text(BRIEF, encoding="utf-8")
            with mock.patch("scripts.brief_to_spec.call_agnes",
                            return_value="```markdown\n" + GOOD_DRAFT + "\n```"):
                r = draft_spec(str(brief))
            self.assertTrue(r["validation"]["ok"], r["validation"]["problems"])

    def test_dry_run_no_call(self):
        with tempfile.TemporaryDirectory() as td:
            brief = Path(td) / "brief.md"
            brief.write_text(BRIEF, encoding="utf-8")
            with mock.patch("scripts.brief_to_spec.call_agnes", return_value="") as ca:
                r = draft_spec(str(brief), dry_run=True)
            ca.assert_not_called()
            self.assertTrue(r["dry_run"])

    def test_draft_spec_with_base_dir_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_proj"
            proj.mkdir()
            (proj / "brief.md").write_text(BRIEF, encoding="utf-8")
            with mock.patch("scripts.brief_to_spec.call_agnes", return_value=GOOD_DRAFT):
                res = draft_spec("my_proj/brief.md", output="my_proj/output/spec.md", base_dir=base)
            self.assertTrue(res["validation"]["ok"])
            self.assertTrue((proj / "output" / "spec.md").is_file())
            self.assertIn("1920 1080", (proj / "output" / "spec.md").read_text(encoding="utf-8"))

    def test_main_cli_with_base_dir_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_proj"
            proj.mkdir()
            (proj / "brief.md").write_text(BRIEF, encoding="utf-8")
            with mock.patch("scripts.brief_to_spec.call_agnes", return_value=GOOD_DRAFT):
                code = main(["my_proj/brief.md", "-o", "my_proj/output/spec.md"], base_dir=base)
            self.assertEqual(code, 0)
            self.assertTrue((proj / "output" / "spec.md").is_file())

    def test_main_cli_with_base_dir_flag(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_proj"
            proj.mkdir()
            (proj / "brief.md").write_text(BRIEF, encoding="utf-8")
            with mock.patch("scripts.brief_to_spec.call_agnes", return_value=GOOD_DRAFT):
                code = main(["my_proj/brief.md", "-o", "my_proj/output/spec.md", "--base-dir", str(base)])
            self.assertEqual(code, 0)
            self.assertTrue((proj / "output" / "spec.md").is_file())

    def test_main_cli_file_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            code = main(["non_existent_brief.md"], base_dir=base)
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()

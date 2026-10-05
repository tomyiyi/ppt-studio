#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_brief_writer.py（mock 网络，不调真实 Agnes）"""
import io
import json
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from brief_writer import (
    build_brief_prompt,
    citable_sources,
    validate_citations,
    write_brief,
    main,
)

BRIEF = {
    "topic": "2026秋冬时尚趋势",
    "sources": [
        {"title": "Pantone 官方", "url": "https://www.pantone.com/x",
         "snippet": "Red Mahogany 领衔", "trust": 0.95, "grade": "A"},
        {"title": "Coveteur 报道", "url": "https://coveteur.com/y",
         "snippet": "宽肩西装", "trust": 0.80, "grade": "B"},
        {"title": "小站转述", "url": "https://blog.example/z",
         "snippet": "据传流行", "trust": 0.30, "grade": "D"},
        {"title": "无 URL 条目", "url": "",
         "snippet": "x", "trust": 0.50, "grade": "C"},
    ],
}

FAKE_MD = (
    "## 核心结论\n"
    "- Red Mahogany 领衔秋冬色板 [1]\n"
    "- 宽肩西装成 NYFW 认证趋势 [2]\n"
    "\n## 数据一览表\n"
    "| 指标 | 值 |\n|---|---|\n| 搜索热度 | +40% [1] |\n"
)


class FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen_factory(md: str):
    payload = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": md}}]}
    ).encode("utf-8")

    def _fake(req, timeout=None):
        # 断言：打到 chat/completions，且 Authorization 头存在才放行语义由调用方决定
        assert "/chat/completions" in req.full_url, req.full_url
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"], "model 不能为空"
        assert body["messages"] and body["messages"][0]["role"] == "user"
        return FakeResp(payload)

    return _fake


class TestBriefWriter(unittest.TestCase):
    def test_citable_sources_filters_D_and_empty_url(self):
        cs = citable_sources(BRIEF)
        self.assertEqual(len(cs), 2)
        self.assertEqual([s["grade"] for s in cs], ["A", "B"])
        # 保持 trust 降序
        self.assertGreaterEqual(cs[0]["trust"], cs[1]["trust"])

    def test_prompt_contains_iron_rules(self):
        cs = citable_sources(BRIEF)
        p = build_brief_prompt(BRIEF["topic"], cs)
        for needle in ["只写有来源支撑", "[n]", "没有来源支撑的内容，一律不写",
                       "优先引用 A/B 级来源", "暂无可靠来源支撑，略去"]:
            self.assertIn(needle, p)
        # D 级来源不出场
        self.assertNotIn("blog.example", p)
        # 可引用来源在场
        self.assertIn("pantone.com", p)
        self.assertIn("[1]", p)
        self.assertIn("[2]", p)

    def test_validate_citations_ok(self):
        r = validate_citations(FAKE_MD, 2)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["cited_count"], 2)

    def test_validate_citations_out_of_range(self):
        r = validate_citations("某结论 [9]", 2)
        self.assertFalse(r["ok"])
        self.assertTrue(any("超出" in p for p in r["problems"]))

    def test_validate_citations_missing_on_fact_line(self):
        r = validate_citations("热度增长 +40% 无引用", 2)
        self.assertFalse(r["ok"])
        self.assertTrue(any("无引用" in p for p in r["problems"]))

    @patch("brief_writer.load_chat_gateway", return_value=("http://x/v1", "k"))
    @patch("urllib.request.urlopen", side_effect=fake_urlopen_factory(FAKE_MD))
    def test_write_brief_end_to_end(self, _mu, _mg):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td) / "brief.json"
            bp.write_text(json.dumps(BRIEF), encoding="utf-8")
            out = Path(td) / "report.md"
            res = write_brief(str(bp), str(out))
            self.assertTrue(res["citation_check"]["ok"])
            self.assertEqual(res["sources_used"], 2)
            text = out.read_text(encoding="utf-8")
            self.assertIn("## 来源清单", text)
            self.assertIn("pantone.com", text)

    @patch("brief_writer.load_chat_gateway", return_value=("http://x/v1", "k"))
    @patch("urllib.request.urlopen",
           side_effect=fake_urlopen_factory("## 结论\n- 很好 [5]"))
    def test_write_brief_warns_bad_citation(self, _mu, _mg):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td) / "brief.json"
            bp.write_text(json.dumps(BRIEF), encoding="utf-8")
            err = io.StringIO()
            with patch("sys.stderr", err):
                res = write_brief(str(bp), None)
            self.assertFalse(res["citation_check"]["ok"])
            self.assertIn("超出", err.getvalue())

    def test_write_brief_refuses_without_citable(self):
        import tempfile
        bad = {"topic": "x", "sources": [
            {"title": "t", "url": "https://e.com", "trust": 0.1, "grade": "D"}]}
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td) / "brief.json"
            bp.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                write_brief(str(bp), None)

    @patch("brief_writer.load_chat_gateway", return_value=("http://x/v1", "k"))
    @patch("urllib.request.urlopen", side_effect=fake_urlopen_factory(FAKE_MD))
    def test_write_brief_with_base_dir_and_relative_paths(self, _mu, _mg):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_proj"
            proj.mkdir()
            (proj / "brief.json").write_text(json.dumps(BRIEF), encoding="utf-8")
            res = write_brief("my_proj/brief.json", "my_proj/out/report.md", base_dir=base)
            self.assertTrue(res["citation_check"]["ok"])
            self.assertTrue((proj / "out" / "report.md").is_file())

    @patch("brief_writer.load_chat_gateway", return_value=("http://x/v1", "k"))
    @patch("urllib.request.urlopen", side_effect=fake_urlopen_factory(FAKE_MD))
    def test_main_cli_with_base_dir_and_relative_paths(self, _mu, _mg):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_proj"
            proj.mkdir()
            (proj / "brief.json").write_text(json.dumps(BRIEF), encoding="utf-8")
            code = main(["my_proj/brief.json", "-o", "my_proj/out/report.md"], base_dir=base)
            self.assertEqual(code, 0)
            self.assertTrue((proj / "out" / "report.md").is_file())

    def test_main_cli_file_not_found(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            code = main(["missing.json"], base_dir=base)
            self.assertEqual(code, 1)


REAL_BRIEF = {'topic': '2026秋冬时尚趋势', 'sources': [{'title': 'Pantone 官方 FW2026 色板', 'url': 'https://www.pantone.com/color-finder/19-1521', 'snippet': 'Red Mahogany 19-1521 领衔 2026 秋冬色板，深酒红调成为核心流行色。', 'trust': 0.95, 'grade': 'A'}, {'title': 'W Magazine：Celine Hiver 2026', 'url': 'https://www.wmagazine.com/celine-hiver-2026', 'snippet': 'Celine 2026 冬季系列首推爵士鞋款，成为秀场焦点单品。', 'trust': 0.88, 'grade': 'A'}, {'title': 'Coveteur：BioFluff 皮草替代品', 'url': 'https://coveteur.com/biofluff-fur-alternative', 'snippet': 'BioFluff 植物基皮草替代品受关注，fur-trim 装饰细节出现在多个品牌秋冬系列。', 'trust': 0.8, 'grade': 'B'}, {'title': 'Elle：2026 秋冬配饰趋势', 'url': 'https://www.elle.com/fashion/fw2026-accessories', 'snippet': '爵士鞋与宽肩廓形西装成为 2026 秋冬关键单品，配饰强调复古运动混搭。', 'trust': 0.78, 'grade': 'B'}, {'title': 'Grazia 街拍观察', 'url': 'https://www.grazia.com/fw2026-street-style', 'snippet': '街拍中深色系大衣出现频率上升，约占受访造型的六成。', 'trust': 0.62, 'grade': 'C'}, {'title': '某论坛爆料帖', 'url': 'https://forum.example.com/fw2026-rumor', 'snippet': '据传 2026 秋冬将流行霓虹绿，相关搜索热度暴涨 300%，多家大牌秘密备货。', 'trust': 0.25, 'grade': 'D'}, {'title': '营销号小道消息', 'url': 'https://blog.example.com/glow-down-jacket', 'snippet': '小道消息称某大牌将推出夜间会发光的羽绒服，定价或超 5 万元。', 'trust': 0.18, 'grade': 'D'}]}

REAL_AGNES_OUTPUT = '## 核心结论\n\n1. 色彩趋势方面，深酒红调（Red Mahogany 19-1521）被确立为 2026 秋冬季节的核心流行色 [1]。\n2. 鞋履成为本季焦点，爵士鞋款由 Celine 2026 冬季系列首推，并进一步被确认为该季度关键单品之一 [2][4]。\n3. 面料与细节上，植物基皮草替代品（如 BioFluff）受到关注，fur-trim 装饰细节出现在多个品牌的秋冬系列中 [3]。\n4. 廓形与混搭风格上，宽肩廓形西装与复古运动混搭的配饰风格构成 2026 秋冬的重要搭配特征 [4]。\n5. 街拍数据显示，深色系大衣在实际穿搭中占比较高，受访造型中约有六成呈现深色系 [5]。\n\n## 分项趋势\n\n**色彩趋势**\nRed Mahogany 19-1521 在 Pantone 官方发布的 2026 秋冬色板中占据领衔位置，深酒红调成为核心流行色 [1]。\n\n**鞋履与关键单品**\nCeline 2026 冬季系列将爵士鞋款作为首推单品，使其成为秀场焦点 [2]。后续配饰趋势分析亦将爵士鞋与宽肩廓形西装并列为 2026 秋冬关键单品 [4]。\n\n**面料与细节**\n植物基皮草替代品 BioFluff 受到行业关注，且 fur-trim 装饰细节出现在多个品牌的秋冬系列中 [3]。\n\n**廓形与配饰风格**\n配饰趋势强调复古运动混搭风格，同时宽肩廓形西装成为关键单品之一 [4]。\n\n**街拍验证**\nGrazia 的街拍观察显示，深色系大衣在 2026 秋冬街头造型中占据主流，约占受访造型的六成 [5]。\n\n## 数据一览表\n\n| 趋势领域 | 关键观察 | 来源等级 | 来源编号 |\n| :--- | :--- | :--- | :--- |\n| 色彩 | Red Mahogany 19-1521 为核心流行色（深酒红调） | A | [1] |\n| 鞋履 | Celine 首推爵士鞋款，为秀场焦点 | A | [2] |\n| 面料/细节 | BioFluff 植物基皮草替代品受关注，fur-trim 细节普及 | B | [3] |\n| 廓形/配饰 | 爵士鞋、宽肩廓形西装为关键单品；复古运动混搭配饰 | B | [4] |\n| 街拍验证 | 深色系大衣占比约 60% | C | [5] |\n\n## 来源清单\n\n[1] Pantone 官方 FW2026 色板\nURL: https://www.pantone.com/color-finder/19-1521\n[2] W Magazine：Celine Hiver 2026\nURL: https://www.wmagazine.com/celine-hiver-2026\n[3] Coveteur：BioFluff 皮草替代品\nURL: https://coveteur.com/biofluff-fur-alternative\n[4] Elle：2026 秋冬配饰趋势\nURL: https://www.elle.com/fashion/fw2026-accessories\n[5] Grazia 街拍观察\nURL: https://www.grazia.com/fw2026-street-style'

class TestBriefWriterRealE2EBaseline(unittest.TestCase):
    """第 14 轮真实端到端回归：prompt 不含 D 级，真实输出引用合规（不调网络）。"""

    def test_real_prompt_excludes_D_grade(self):
        cs = citable_sources(REAL_BRIEF)
        self.assertEqual(len(cs), 5)
        p = build_brief_prompt(REAL_BRIEF["topic"], cs)
        for decoy in ["霓虹绿", "300%", "发光", "forum.example.com",
                      "blog.example.com"]:
            self.assertNotIn(decoy, p)

    def test_real_output_citations_valid(self):
        r = validate_citations(REAL_AGNES_OUTPUT, 5)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["cited_count"], 5)

    def test_real_output_no_D_leakage(self):
        for decoy in ["霓虹绿", "300%", "发光", "据传", "小道消息"]:
            self.assertNotIn(decoy, REAL_AGNES_OUTPUT)

    def test_real_output_structure(self):
        for h in ["## 核心结论", "## 分项趋势", "## 数据一览表", "## 来源清单"]:
            self.assertIn(h, REAL_AGNES_OUTPUT)


if __name__ == "__main__":
    unittest.main()

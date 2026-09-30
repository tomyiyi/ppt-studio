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


if __name__ == "__main__":
    unittest.main()

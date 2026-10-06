#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_research_to_spec.py（mock 网络；第 18 轮改写为 mock search_router）"""
import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.research_to_spec import (
    gen_subqueries, research, search_all_backends, _to_scorable,
    DEFAULT_BACKENDS, main,
)

# router 归一化格式的假结果
FAKE_TAVILY = [
    {"title": "Pantone report", "url": "https://www.pantone.com/x",
     "snippet": "color trends", "source": "tavily", "backend": "tavily",
     "extra": {"published": "2026-08-01"}},
]
FAKE_BILI = [
    {"title": "趋势解析", "url": "https://www.bilibili.com/video/BV1x",
     "snippet": "fashion", "source": "bilibili", "backend": "bili",
     "extra": {"published_at": "2026-09-01"}},
]
FAKE_XHS = [
    {"title": "秋冬穿搭", "url": "https://www.xiaohongshu.com/discovery/item/abc",
     "snippet": "作者: 某博主", "source": "xiaohongshu", "backend": "xhs",
     "extra": {}},
]


def _router_side_effect(query, **kwargs):
    name = kwargs["backends"][0]
    table = {"tavily": FAKE_TAVILY, "bili": FAKE_BILI, "xhs": FAKE_XHS}
    return {"query": query, "backend_used": name,
            "results": [dict(r) for r in table[name]], "attempts": []}


class TestResearchToSpec(unittest.TestCase):
    def test_gen_subqueries(self):
        sq = gen_subqueries("2026时尚", n=5)
        self.assertEqual(len(sq), 5)
        self.assertTrue(all("2026时尚" in s for s in sq))

    def test_default_backends_exclude_xhs(self):
        # 红线：xhs 默认关闭（Cookie 过期 + 禁真实请求）
        self.assertNotIn("xhs", DEFAULT_BACKENDS)
        self.assertIn("tavily", DEFAULT_BACKENDS)
        self.assertIn("bili", DEFAULT_BACKENDS)

    @patch("scripts.research_to_spec.router_search", side_effect=_router_side_effect)
    def test_research_breadth(self, _):
        # 广度语义：每个启用的后端都贡献结果（非 fallback 首个即停）
        brief = research("2026时尚", backends=("tavily", "bili"), per_query=2)
        self.assertEqual(brief["topic"], "2026时尚")
        self.assertEqual(brief["backends"], ["tavily", "bili"])
        self.assertEqual(len(brief["subqueries"]), 5)
        self.assertEqual(brief["source_count"], 2)
        urls = [s["url"] for s in brief["sources"]]
        self.assertEqual(len(urls), len(set(urls)))
        # 每条标注 backend_used
        used = {s["backend_used"] for s in brief["sources"]}
        self.assertEqual(used, {"tavily", "bili"})
        # 打分已附加
        for s in brief["sources"]:
            self.assertIn("trust", s)
            self.assertIn("grade", s)
            self.assertIn("trust_reasons", s)
        # 按 trust 降序
        trusts = [s["trust"] for s in brief["sources"]]
        self.assertEqual(trusts, sorted(trusts, reverse=True))
        # pantone 应为 A 级排第一
        self.assertEqual(brief["sources"][0]["grade"], "A")

    @patch("scripts.research_to_spec.router_search", side_effect=_router_side_effect)
    def test_research_with_xhs_opt_in(self, _):
        brief = research("2026时尚", backends=("tavily", "xhs", "bili"), per_query=1)
        self.assertEqual(brief["source_count"], 3)
        self.assertIn("xhs", brief["backends"])
        xhs_src = [s for s in brief["sources"] if s["backend_used"] == "xhs"][0]
        self.assertIn("xiaohongshu.com", xhs_src["url"])

    def test_backend_isolation(self):
        # 单后端异常只 warn 跳过，不中断其他后端
        def boom(query, **kwargs):
            if kwargs["backends"][0] == "tavily":
                raise RuntimeError("tavily 挂了")
            return _router_side_effect(query, **kwargs)

        err = io.StringIO()
        with patch("scripts.research_to_spec.router_search", side_effect=boom):
            with redirect_stderr(err):
                out = search_all_backends("q", ["tavily", "bili"], 5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["backend_used"], "bili")
        self.assertIn("tavily", err.getvalue())

    def test_unknown_backend_fail_fast(self):
        with self.assertRaises(ValueError):
            research("x", backends=("nope",))

    def test_to_scorable_published_fallback(self):
        # tavily extra.published / bili extra.published_at / xhs 无
        self.assertEqual(_to_scorable(FAKE_TAVILY[0])["published_at"], "2026-08-01")
        self.assertEqual(_to_scorable(FAKE_BILI[0])["published_at"], "2026-09-01")
        self.assertEqual(_to_scorable(FAKE_XHS[0])["published_at"], "")

    @patch("scripts.research_to_spec.router_search", side_effect=_router_side_effect)
    def test_empty(self, _):
        with patch("scripts.research_to_spec.router_search",
                   return_value={"query": "x", "backend_used": None,
                                 "results": [], "attempts": []}):
            brief = research("xyz", per_query=1)
        self.assertEqual(brief["source_count"], 0)
        self.assertEqual(brief["sources"], [])

    @patch("scripts.research_to_spec.router_search", side_effect=_router_side_effect)
    def test_brief_writer_chain(self, _):
        # research 输出 -> brief_writer 可引用过滤 -> prompt 构建，全链路无网络
        from scripts.brief_writer import citable_sources, build_brief_prompt
        brief = research("2026时尚", backends=("tavily", "bili"), per_query=1)
        citable = citable_sources(brief)
        self.assertTrue(len(citable) > 0)
        self.assertTrue(all(s.get("url") for s in citable))
        prompt = build_brief_prompt(brief["topic"], citable)
        self.assertIn("2026时尚", prompt)
        self.assertIn("[1]", prompt)

    @patch("scripts.research_to_spec.router_search", side_effect=_router_side_effect)
    def test_main_cli_with_base_dir_and_relative_output(self, _):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            code = main(["2026时尚", "-o", "my_proj/out/brief.json", "--per-query", "1"], base_dir=base)
            self.assertEqual(code, 0)
            out_file = base / "my_proj" / "out" / "brief.json"
            self.assertTrue(out_file.is_file())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["topic"], "2026时尚")
            self.assertGreater(data["source_count"], 0)

    @patch("scripts.research_to_spec.router_search", side_effect=_router_side_effect)
    def test_main_cli_with_base_dir_flag(self, _):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            code = main(["2026时尚", "-o", "my_proj/out/brief.json", "--per-query", "1", "--base-dir", str(base)])
            self.assertEqual(code, 0)
            out_file = base / "my_proj" / "out" / "brief.json"
            self.assertTrue(out_file.is_file())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["topic"], "2026时尚")
            self.assertGreater(data["source_count"], 0)

    @patch("scripts.research_to_spec.router_search", side_effect=_router_side_effect)
    def test_main_cli_with_empty_backends_fallback(self, _):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with patch("scripts.research_to_spec.BACKENDS", []):
                code = main(["2026时尚", "-o", "my_proj/out/brief.json", "--per-query", "1", "--base-dir", str(base)])
                self.assertEqual(code, 0)
                out_file = base / "my_proj" / "out" / "brief.json"
                self.assertTrue(out_file.is_file())


if __name__ == "__main__":
    unittest.main()

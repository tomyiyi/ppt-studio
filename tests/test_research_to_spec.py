#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_research_to_spec.py（mock 网络）"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.research_to_spec import gen_subqueries, research

FAKE_TAVILY = [
    {"title": "Pantone report", "url": "https://www.pantone.com/x",
     "published_at": "2026-08-01", "snippet": "color trends", "source": "tavily"},
]
FAKE_BILI = [
    {"title": "趋势解析", "url": "https://www.bilibili.com/video/BV1x",
     "published_at": "2026-09-01", "description": "fashion", "source": "bilibili"},
]


class TestResearchToSpec(unittest.TestCase):
    def test_gen_subqueries(self):
        sq = gen_subqueries("2026时尚", n=5)
        self.assertEqual(len(sq), 5)
        self.assertTrue(all("2026时尚" in s for s in sq))

    @patch("scripts.research_to_spec.search_bili", return_value=FAKE_BILI)
    @patch("scripts.research_to_spec.search_tavily", return_value=FAKE_TAVILY)
    def test_research(self, mt, mb):
        brief = research("2026时尚", per_query=2)
        self.assertEqual(brief["topic"], "2026时尚")
        self.assertEqual(len(brief["subqueries"]), 5)
        self.assertEqual(brief["source_count"], 2)
        # 去重：URL 唯一
        urls = [s["url"] for s in brief["sources"]]
        self.assertEqual(len(urls), len(set(urls)))
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

    @patch("scripts.research_to_spec.search_bili", return_value=[])
    @patch("scripts.research_to_spec.search_tavily", return_value=[])
    def test_empty(self, mt, mb):
        brief = research("xyz", per_query=1)
        self.assertEqual(brief["source_count"], 0)
        self.assertEqual(brief["sources"], [])


if __name__ == "__main__":
    unittest.main()

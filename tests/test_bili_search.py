#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_bili_search.py -- bili_search.py 单元测试（mock 网络）"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.bili_search import search, main


def _fake_response(payload):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


SAMPLE = {
    "code": 0,
    "data": {"result": [
        {"title": "2026<t>秋冬</t>趋势", "bvid": "BV1abc",
         "author": "时尚UP", "play": 12345, "danmaku": 100,
         "duration": "5:00", "pubdate": 1759000000,
         "description": "趋势解析"},
    ]},
}


class TestBiliSearch(unittest.TestCase):
    @patch("scripts.bili_search.urllib.request.urlopen")
    def test_search_parses(self, mock_open):
        mock_open.return_value = _fake_response(SAMPLE)
        out = search("2026趋势", max_results=1)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["title"], "2026秋冬趋势")  # HTML 标签已剥
        self.assertEqual(r["url"], "https://www.bilibili.com/video/BV1abc")
        self.assertEqual(r["author"], "时尚UP")
        self.assertEqual(r["play"], 12345)
        self.assertEqual(r["source"], "bilibili")
        self.assertRegex(r["published_at"], r"^\d{4}-\d{2}-\d{2}$")

    @patch("scripts.bili_search.urllib.request.urlopen")
    def test_api_error(self, mock_open):
        mock_open.return_value = _fake_response({"code": -412, "message": "req err"})
        out = search("x", max_results=5)
        self.assertEqual(out, [])

    @patch("scripts.bili_search.urllib.request.urlopen")
    def test_network_fail(self, mock_open):
        mock_open.side_effect = Exception("timeout")
        out = search("x", max_results=5)
        self.assertEqual(out, [])

    @patch("scripts.bili_search.urllib.request.urlopen")
    def test_main_cli_with_base_dir_and_relative_output(self, mock_open):
        import tempfile
        mock_open.return_value = _fake_response(SAMPLE)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            code = main(["2026趋势", "--max", "1", "-o", "data/bili_res.json"], base_dir=base)
            self.assertEqual(code, 0)
            out_file = base / "data" / "bili_res.json"
            self.assertTrue(out_file.is_file())
            payload = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["results"][0]["title"], "2026秋冬趋势")


if __name__ == "__main__":
    unittest.main()

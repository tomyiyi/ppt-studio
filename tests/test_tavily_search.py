#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_tavily_search.py -- tavily_search.py 单元测试（mock 网络与配置）"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tavily_search import load_keys, search, main


def _fake_response(payload):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


SAMPLE_RESPONSE = {
    "query": "Pantone 2026",
    "answer": "2026 fashion trends summary",
    "results": [
        {
            "title": "Trend Forecast 2026",
            "url": "https://example.com/trends",
            "content": "Sustainable knitwear and bold textures.",
            "score": 0.95,
        }
    ]
}


class TestTavilySearch(unittest.TestCase):
    def test_load_keys_from_env(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test-12345"}):
            with tempfile.TemporaryDirectory() as td:
                empty_file = Path(td) / "empty.json"
                keys = load_keys(key_file=empty_file)
                self.assertIn("tvly-test-12345", keys)

    def test_load_keys_from_file(self):
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as td:
                key_file = Path(td) / "tavily.json"
                key_file.write_text(json.dumps({"keys": ["key-from-file-1", "key-from-file-2"]}), encoding="utf-8")
                keys = load_keys(key_file=key_file)
                self.assertEqual(keys, ["key-from-file-1", "key-from-file-2"])

    def test_load_keys_no_keys_exits(self):
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as td:
                non_existent = Path(td) / "non_existent.json"
                with self.assertRaises(SystemExit):
                    load_keys(key_file=non_existent)

    @patch("scripts.tavily_search.urllib.request.urlopen")
    def test_search_request_payload(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(SAMPLE_RESPONSE)
        res = search("test query", "tvly-key", "advanced", 5)
        self.assertEqual(res["query"], "Pantone 2026")
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["title"], "Trend Forecast 2026")

    @patch("scripts.tavily_search.search")
    @patch("scripts.tavily_search.load_keys")
    def test_main_cli_with_base_dir_and_relative_output(self, mock_load_keys, mock_search):
        mock_load_keys.return_value = ["test-key-abc"]
        mock_search.return_value = SAMPLE_RESPONSE

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            code = main(
                ["Pantone 2026", "-o", "data/search_res.json", "--max", "5"],
                base_dir=base
            )
            self.assertEqual(code, 0)
            out_file = base / "data" / "search_res.json"
            self.assertTrue(out_file.is_file())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["query"], "Pantone 2026")
            self.assertEqual(len(data["results"]), 1)

    @patch("scripts.tavily_search.search")
    @patch("scripts.tavily_search.load_keys")
    def test_main_cli_with_base_dir_flag(self, mock_load_keys, mock_search):
        mock_load_keys.return_value = ["test-key-abc"]
        mock_search.return_value = SAMPLE_RESPONSE

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            code = main(
                ["Pantone 2026", "-o", "data/search_res_flag.json", "--max", "5", "--base-dir", str(base)]
            )
            self.assertEqual(code, 0)
            out_file = base / "data" / "search_res_flag.json"
            self.assertTrue(out_file.is_file())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["query"], "Pantone 2026")
            self.assertEqual(len(data["results"]), 1)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_xhs_sign.py —— xhs_sign 签名模块单元测试（全 mock，不碰网络/Cookie）"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---- 在 import xhs_sign 之前 stub 掉 xhs_search.load_cookies（避免读真实 Cookie 文件）----
fake_search = types.ModuleType("xhs_search")


def _fake_load_cookies(key_file=None, *args, **kwargs):
    return {"web_session": "FAKE_SESSION", "a1": "A" * 52}


fake_search.load_cookies = _fake_load_cookies
sys.modules["xhs_search"] = fake_search
sys.modules["scripts.xhs_search"] = fake_search

from scripts import xhs_sign  # noqa: E402
sys.modules["xhs_sign"] = xhs_sign


class TestEnsureDeviceCookies(unittest.TestCase):
    def test_generates_a1_when_missing(self):
        out = xhs_sign.ensure_device_cookies({"web_session": "s"})
        self.assertIn("a1", out)
        self.assertEqual(len(out["a1"]), 52)
        self.assertIn("webId", out)

    def test_keeps_existing_a1(self):
        out = xhs_sign.ensure_device_cookies({"a1": "B" * 52})
        self.assertEqual(out["a1"], "B" * 52)

    def test_does_not_mutate_input(self):
        src = {"web_session": "s"}
        xhs_sign.ensure_device_cookies(src)
        self.assertNotIn("a1", src)


class TestSignedGetHeaders(unittest.TestCase):
    def test_header_format(self):
        h = xhs_sign.signed_get_headers(
            "https://so.xiaohongshu.com/api/sns/web/v2/search/notes",
            {"keyword": "test"},
            {"a1": "A" * 52, "web_session": "s"},
        )
        # x-s 必须以 XYS_ 开头（xhshow 签名格式）
        self.assertTrue(h.get("x-s", "").startswith("XYS_"))
        # x-t 必须是毫秒时间戳（13 位数字）
        self.assertRegex(str(h.get("x-t", "")), r"^\d{13}$")
        # 搜索接口必须带 x-rap-param
        self.assertIn("x-rap-param", h)
        self.assertIn("x-s-common", h)

    def test_x_rap_disabled(self):
        h = xhs_sign.signed_get_headers(
            "https://edith.xiaohongshu.com/api/sns/web/v1/user_posted",
            {"num": "30"},
            {"a1": "A" * 52},
            x_rap=False,
        )
        self.assertTrue(h.get("x-s", "").startswith("XYS_"))
        self.assertNotIn("x-rap-param", h)


class TestSignedPostHeaders(unittest.TestCase):
    def test_post_header_format(self):
        h = xhs_sign.signed_post_headers(
            "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes",
            {"keyword": "test", "page": 1},
            {"a1": "A" * 52, "web_session": "s"},
        )
        # x-s 必须以 XYS_ 开头（搜索接口实测要求默认 xys 格式，xyw 会被 461 拒绝）
        self.assertTrue(h.get("x-s", "").startswith("XYS_"))
        self.assertRegex(str(h.get("x-t", "")), r"^\d{13}$")
        self.assertIn("x-rap-param", h)
        self.assertIn("x-s-common", h)
        self.assertEqual(h.get("Content-Type"), "application/json;charset=UTF-8")


class TestBuildSearchParams(unittest.TestCase):
    def test_params_shape(self):
        p = xhs_sign.build_search_params("秋冬穿搭", page_size=5)
        self.assertEqual(p["keyword"], "秋冬穿搭")
        self.assertEqual(p["page_size"], 5)
        self.assertIsInstance(p["page"], int)
        self.assertIn("search_id", p)
        self.assertTrue(p["search_id"])  # base36 非空


class TestApiSearchNotes(unittest.TestCase):
    @patch("xhs_sign.urllib.request.urlopen")
    def test_parses_items(self, mock_urlopen):
        import json as _json

        body = _json.dumps({
            "success": True,
            "data": {"items": [{
                "id": "abc123",
                "note_card": {
                    "display_title": "秋冬穿搭分享",
                    "user": {"nickname": "时尚博主"},
                    "interact_info": {"liked_count": "1.2万"},
                },
            }]},
        }).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        out = xhs_sign.api_search_notes(
            "秋冬穿搭", 5, {"a1": "A" * 52, "web_session": "s"})
        # 必须用 POST 发 JSON body（GET 会被服务端 404）
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "POST")
        self.assertIn(b"keyword", req.data)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "秋冬穿搭分享")
        self.assertEqual(out[0]["author"], "时尚博主")
        self.assertEqual(out[0]["liked"], "1.2万")
        self.assertIn("abc123", out[0]["url"])

    @patch("xhs_sign.urllib.request.urlopen")
    def test_api_failure_raises(self, mock_urlopen):
        import json as _json
        body = _json.dumps({"success": False, "msg": "test fail"}).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp
        with self.assertRaises(RuntimeError):
            xhs_sign.api_search_notes(
                "x", 5, {"a1": "A" * 52, "web_session": "s"})


class TestMainCLI(unittest.TestCase):
    def test_main_empty_keyword_prints_help(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = xhs_sign.main([])
        self.assertEqual(ret, 0)
        self.assertIn("小红书 API 签名搜索", buf.getvalue())

    @patch("xhs_sign.api_search_notes")
    def test_main_output_file_and_base_dir(self, mock_search):
        import tempfile
        import json as _json

        mock_search.return_value = [{"title": "t1", "author": "a1", "liked": "10", "url": "http://x"}]
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            ret = xhs_sign.main(
                ["测试关键词", "--max", "3", "-o", "data/out.json", "--base-dir", str(base_dir)]
            )
            self.assertEqual(ret, 0)
            mock_search.assert_called_once_with("测试关键词", 3, key_file=None)
            out_file = base_dir / "data" / "out.json"
            self.assertTrue(out_file.exists())
            data = _json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["title"], "t1")

    @patch("xhs_sign.api_search_notes")
    def test_main_key_file_relative_to_base_dir(self, mock_search):
        import tempfile

        mock_search.return_value = []
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            ret = xhs_sign.main(
                ["测试", "--key-file", "conf/cookie.json"],
                base_dir=base_dir,
            )
            self.assertEqual(ret, 0)
            mock_search.assert_called_once_with(
                "测试", 10, key_file=(base_dir / "conf" / "cookie.json").resolve()
            )

    @patch("xhs_sign.api_search_notes")
    def test_main_stdout_json(self, mock_search):
        import io
        from contextlib import redirect_stdout

        mock_search.return_value = [{"title": "item1"}]
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = xhs_sign.main(["关键词"])
        self.assertEqual(ret, 0)
        self.assertIn("item1", buf.getvalue())


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""xhs_search 单元测试：全部 mock，不发真实请求。"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import xhs_search


def make_html(state_obj: dict, final_url: str = "http://www.xiaohongshu.com/search_result/?keyword=x"):
    state_json = json.dumps(state_obj, ensure_ascii=False)
    html = "<html><head><title>t</title></head><body><script>window.__INITIAL_STATE__=" + state_json + "</script></body></html>"
    resp = mock.MagicMock()
    resp.geturl.return_value = final_url
    resp.read.return_value = html.encode("utf-8")
    resp.__enter__.return_value = resp
    return resp


FAKE_STATE = {
    "search": {
        "result": {
            "notes": [
                {"id": "abc123",
                 "note_card": {
                     "display_title": "2026秋冬穿搭灵感",
                     "user": {"nickname": "时尚博主A"},
                     "interact_info": {"liked_count": 1234}}},
                {"id": "def456",
                 "note_card": {
                     "display_title": "大衣怎么选",
                     "user": {"nickname": "博主B"},
                     "interact_info": {"liked_count": 567}}},
            ]
        }
    },
    "user": {"notes": [{"id": "zzz", "title": "我自己的笔记"}]},
}


class TestXhsSearch(unittest.TestCase):
    def _patch(self, state=FAKE_STATE, final_url=None):
        cookies = {"web_session": "fake", "id_token": "fake"}
        p1 = mock.patch.object(xhs_search, "load_cookies", return_value=cookies)
        resp = make_html(state, final_url or "http://www.xiaohongshu.com/search_result/?keyword=x")
        p2 = mock.patch("urllib.request.urlopen", return_value=resp)
        return p1, p2

    def test_parse_notes_basic(self):
        p1, p2 = self._patch()
        with p1, p2:
            out = xhs_search.search("穿搭", 10)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["title"], "2026秋冬穿搭灵感")
        self.assertEqual(out[0]["author"], "时尚博主A")
        self.assertEqual(out[0]["liked"], 1234)
        self.assertEqual(out[0]["url"], "https://www.xiaohongshu.com/explore/abc123")

    def test_max_limit(self):
        p1, p2 = self._patch()
        with p1, p2:
            out = xhs_search.search("穿搭", 1)
        self.assertEqual(len(out), 1)

    def test_login_redirect_raises(self):
        cookies = {"web_session": "fake"}
        with mock.patch.object(xhs_search, "load_cookies", return_value=cookies):
            resp = make_html(FAKE_STATE, "https://www.xiaohongshu.com/login?x=1")
            with mock.patch("urllib.request.urlopen", return_value=resp):
                with self.assertRaises(xhs_search.CookieExpiredError) as cm:
                    xhs_search.search("穿搭")
        self.assertIn("Cookie 失效", str(cm.exception))

    def test_no_state_raises(self):
        cookies = {"web_session": "fake"}
        with mock.patch.object(xhs_search, "load_cookies", return_value=cookies):
            resp = mock.MagicMock()
            resp.geturl.return_value = "http://www.xiaohongshu.com/search_result/?keyword=x"
            resp.read.return_value = b"<html><body>no state here</body></html>"
            resp.__enter__.return_value = resp
            with mock.patch("urllib.request.urlopen", return_value=resp):
                with self.assertRaises(xhs_search.CookieExpiredError):
                    xhs_search.search("穿搭")

    def test_undefined_js_handling(self):
        cookies = {"web_session": "fake"}
        with mock.patch.object(xhs_search, "load_cookies", return_value=cookies):
            html = ("<html><body><script>window.__INITIAL_STATE__="
                    '{"a":null,"search":{"result":{"notes":[]}}}</script></body></html>')
            resp = mock.MagicMock()
            resp.geturl.return_value = "http://www.xiaohongshu.com/search_result/?keyword=x"
            resp.read.return_value = html.encode()
            resp.__enter__.return_value = resp
            with mock.patch("urllib.request.urlopen", return_value=resp):
                out = xhs_search.search("穿搭")
        self.assertEqual(out, [])

    def test_perm_check_rejects(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"cookies": {"web_session": "x"}}, f)
            tmp = f.name
        os.chmod(tmp, 0o644)
        try:
            with mock.patch.object(xhs_search, "KEY_FILE", Path(tmp)):
                with self.assertRaises(SystemExit) as cm:
                    xhs_search.load_cookies()
            self.assertIn("600", str(cm.exception.code))
        finally:
            os.unlink(tmp)

    def test_load_cookies_custom_key_file(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"cookies": {"web_session": "test-cookie-val"}}, f)
            tmp = f.name
        os.chmod(tmp, 0o600)
        try:
            cookies = xhs_search.load_cookies(key_file=tmp)
            self.assertEqual(cookies.get("web_session"), "test-cookie-val")
        finally:
            os.unlink(tmp)

    def test_main_cli_with_base_dir_and_relative_output(self):
        import tempfile
        p1, p2 = self._patch()
        with p1, p2:
            with tempfile.TemporaryDirectory() as td:
                base = Path(td)
                code = xhs_search.main(["穿搭", "--max", "1", "-o", "data/xhs_res.json"], base_dir=base)
                self.assertEqual(code, 0)
                out_file = base / "data" / "xhs_res.json"
                self.assertTrue(out_file.is_file())
                data = json.loads(out_file.read_text(encoding="utf-8"))
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["title"], "2026秋冬穿搭灵感")

    def test_main_cli_with_base_dir_flag(self):
        import tempfile
        p1, p2 = self._patch()
        with p1, p2:
            with tempfile.TemporaryDirectory() as td:
                base = Path(td)
                code = xhs_search.main(["穿搭", "--max", "1", "-o", "data/xhs_res_flag.json", "--base-dir", str(base)])
                self.assertEqual(code, 0)
                out_file = base / "data" / "xhs_res_flag.json"
                self.assertTrue(out_file.is_file())
                data = json.loads(out_file.read_text(encoding="utf-8"))
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["title"], "2026秋冬穿搭灵感")


if __name__ == "__main__":
    unittest.main()

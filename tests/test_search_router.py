#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_router.py 测试：fallback 链语义、doctor 隔离、归一化。

全部用 mock 后端，不发起真实网络请求。
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import search_router as R


def fake_backend(name, run=None, check=None):
    return R.Backend(
        name,
        run if run is not None else MagicMock(return_value=[]),
        check if check is not None else (lambda: ("ok", "fine")),
        description=name,
    )


def item(title):
    return {"title": title, "url": "http://x/" + title, "snippet": "s",
            "source": "t", "backend": "t", "extra": {}}


class ResolveBackendsTest(unittest.TestCase):
    def test_auto_returns_all_in_priority_order(self):
        bs = R.resolve_backends("auto")
        self.assertEqual([b.name for b in bs], ["tavily", "xhs", "bili", "wiki", "commons"])

    def test_none_is_auto(self):
        self.assertEqual([b.name for b in R.resolve_backends(None)],
                         ["tavily", "xhs", "bili", "wiki", "commons"])

    def test_string_list_and_order(self):
        bs = R.resolve_backends("bili,xhs")
        self.assertEqual([b.name for b in bs], ["bili", "xhs"])

    def test_list_input(self):
        bs = R.resolve_backends(["xhs"])
        self.assertEqual([b.name for b in bs], ["xhs"])

    def test_unknown_backend(self):
        with self.assertRaises(ValueError):
            R.resolve_backends("nope")


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self._orig_backends = R.BACKENDS
        self._orig_map = R._BACKEND_MAP

    def tearDown(self):
        R.BACKENDS = self._orig_backends
        R._BACKEND_MAP = self._orig_map

    def use(self, backends):
        R.BACKENDS = backends
        R._BACKEND_MAP = {b.name: b for b in backends}
        return backends

    def test_first_success_short_circuits(self):
        r2 = MagicMock(return_value=[])
        r3 = MagicMock(return_value=[])
        self.use([fake_backend("tavily", run=lambda q, m: [item("a")]),
                  fake_backend("xhs", run=r2),
                  fake_backend("bili", run=r3)])
        res = R.search("q")
        self.assertEqual(res["backend_used"], "tavily")
        self.assertEqual(len(res["results"]), 1)
        r2.assert_not_called()
        r3.assert_not_called()

    def test_exception_falls_through_to_next(self):
        def boom(q, m):
            raise RuntimeError("tavily 挂了")
        r3 = MagicMock(return_value=[])
        self.use([fake_backend("tavily", run=boom),
                  fake_backend("xhs", run=lambda q, m: [item("b")]),
                  fake_backend("bili", run=r3)])
        res = R.search("q")
        self.assertEqual(res["backend_used"], "xhs")
        self.assertEqual(res["attempts"][0]["backend"], "tavily")
        self.assertFalse(res["attempts"][0]["ok"])
        self.assertIn("tavily 挂了", res["attempts"][0]["error"])
        self.assertTrue(res["attempts"][1]["ok"])
        r3.assert_not_called()

    def test_empty_result_continues_chain(self):
        self.use([fake_backend("tavily", run=lambda q, m: []),
                  fake_backend("xhs", run=lambda q, m: [item("c")])])
        res = R.search("q")
        self.assertEqual(res["backend_used"], "xhs")
        self.assertEqual(res["attempts"][0]["n"], 0)
        self.assertTrue(res["attempts"][0]["ok"])  # 空结果不算失败

    def test_all_raise_gives_aggregated_error(self):
        self.use([fake_backend("tavily", run=MagicMock(side_effect=RuntimeError("e1"))),
                  fake_backend("xhs", run=MagicMock(side_effect=RuntimeError("e2")))])
        with self.assertRaises(R.SearchAllBackendsFailed) as ctx:
            R.search("q")
        self.assertIn("tavily", str(ctx.exception))
        self.assertIn("xhs", str(ctx.exception))

    def test_all_empty_returns_ok_empty(self):
        self.use([fake_backend("tavily"), fake_backend("xhs")])
        res = R.search("q")
        self.assertIsNone(res["backend_used"])
        self.assertEqual(res["results"], [])
        self.assertEqual(len(res["attempts"]), 2)

    def test_no_fallback_reraises_first_error(self):
        def boom(q, m):
            raise RuntimeError("原始错误")
        self.use([fake_backend("tavily", run=boom),
                  fake_backend("xhs", run=lambda q, m: [item("z")])])
        with self.assertRaises(RuntimeError) as ctx:
            R.search("q", allow_fallback=False)
        self.assertEqual(str(ctx.exception), "原始错误")  # 不是聚合异常

    def test_no_fallback_empty_does_not_continue(self):
        r2 = MagicMock(return_value=[item("z")])
        self.use([fake_backend("tavily", run=lambda q, m: []),
                  fake_backend("xhs", run=r2)])
        res = R.search("q", allow_fallback=False)
        self.assertEqual(res["results"], [])
        r2.assert_not_called()

    def test_max_results_truncation(self):
        self.use([fake_backend("tavily",
                               run=lambda q, m: [item(str(i)) for i in range(10)])])
        res = R.search("q", max_results=3)
        self.assertEqual(len(res["results"]), 3)
        self.assertEqual(res["attempts"][0]["n"], 10)  # attempts 记原始产出


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self._orig_backends = R.BACKENDS

    def tearDown(self):
        R.BACKENDS = self._orig_backends

    def test_doctor_survives_broken_backend(self):
        def bad_check():
            raise RuntimeError("自检炸了")
        R.BACKENDS = [fake_backend("tavily", check=bad_check),
                      fake_backend("xhs", check=lambda: ("ok", "fine"))]
        rep = R.doctor()
        self.assertEqual(rep["tavily"]["status"], "error")
        self.assertIn("自检炸了", rep["tavily"]["message"])
        self.assertEqual(rep["xhs"]["status"], "ok")

    def test_doctor_reports_missing(self):
        R.BACKENDS = [fake_backend("tavily",
                                   check=lambda: ("missing", "无 key"))]
        rep = R.doctor()
        self.assertEqual(rep["tavily"]["status"], "missing")


class NormalizeTest(unittest.TestCase):
    def test_normalize_tavily(self):
        raw = {"results": [
            {"title": "T", "url": "http://u", "content": "C" * 600,
             "score": 0.9, "published_date": "2026-01-01"},
            "not-a-dict",
        ]}
        out = R.normalize_tavily(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "T")
        self.assertEqual(out[0]["backend"], "tavily")
        self.assertEqual(len(out[0]["snippet"]), 500)  # 截断
        self.assertEqual(out[0]["extra"]["score"], 0.9)

    def test_normalize_xhs(self):
        raw = [{"title": "笔记", "url": "http://xhs/1",
                "author": "阿棠", "liked": "1.2万"},
               {"title": "", "url": ""}]
        out = R.normalize_xhs(raw)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["source"], "xiaohongshu")
        self.assertIn("阿棠", out[0]["snippet"])
        self.assertIn("1.2万", out[0]["snippet"])

    def test_normalize_bili(self):
        raw = [{"title": "视频", "url": "http://bili/1",
                "description": "简介", "author": "up", "play": 100,
                "published_at": "2026-01-01"}]
        out = R.normalize_bili(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "bilibili")
        self.assertIn("简介", out[0]["snippet"])

    def test_normalize_skips_non_dict(self):
        self.assertEqual(R.normalize_xhs(["x", None]), [])
        self.assertEqual(R.normalize_bili([None]), [])


class RealBackendWiringTest(unittest.TestCase):
    """验证真实 BACKENDS 注册表结构（不调用网络）。"""

    def test_registry_names_and_priority(self):
        self.assertEqual([b.name for b in R.BACKENDS],
                         ["tavily", "xhs", "bili", "wiki", "commons"])

    def test_each_backend_has_run_and_check(self):
        for b in R.BACKENDS:
            self.assertTrue(callable(b.run))
            self.assertTrue(callable(b.check))


class NormalizeWikiTest(unittest.TestCase):
    SAMPLE = {"query": {"search": [
        {"pageid": 1, "title": "Pantone",
         "snippet": '色彩 <span class="searchmatch">标准</span>'},
        "not-a-dict",
        {"pageid": 2, "title": "", "snippet": ""},
    ]}}

    def test_normalize_wiki(self):
        out = R.normalize_wiki(self.SAMPLE, "zh")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["backend"], "wiki")
        self.assertEqual(out[0]["source"], "wikipedia(zh)")
        self.assertIn("Pantone", out[0]["url"])
        self.assertNotIn("<span", out[0]["snippet"])  # HTML 已剥离
        self.assertEqual(out[0]["extra"]["pageid"], 1)

    def test_normalize_wiki_empty(self):
        self.assertEqual(R.normalize_wiki({}), [])
        self.assertEqual(R.normalize_wiki({"query": {}}), [])


class WikiRunTest(unittest.TestCase):
    def _fake_resp(self, payload):
        import io  # noqa: F401 -- 占位，保持结构清晰
        import json as _j
        m = MagicMock()
        m.read.return_value = _j.dumps(payload).encode("utf-8")
        m.__enter__.return_value = m
        return m

    def test_zh_hit_no_en_call(self):
        payload = {"query": {"search": [{"pageid": 1, "title": "A",
                                         "snippet": "x"}]}}
        with patch("urllib.request.urlopen",
                   return_value=self._fake_resp(payload)) as uo:
            out = R._wiki_run("q", 5)
        self.assertEqual(len(out), 1)
        self.assertEqual(uo.call_count, 1)

    def test_zh_empty_falls_back_to_en(self):
        empty = {"query": {"search": []}}
        en = {"query": {"search": [{"pageid": 2, "title": "B",
                                    "snippet": "y"}]}}
        with patch("urllib.request.urlopen",
                   side_effect=[self._fake_resp(empty),
                                self._fake_resp(en)]) as uo:
            out = R._wiki_run("q", 5)
        self.assertEqual(uo.call_count, 2)
        self.assertEqual(out[0]["source"], "wikipedia(en)")

    def test_wiki_check_ok(self):
        status, _ = R._wiki_check()
        self.assertEqual(status, "ok")


"""第 23 轮测试补丁：_wiki_api_search 瞬时故障重试 1 次后成功。"""


class WikiRetryTest(unittest.TestCase):
    def _fake_resp(self, payload):
        import json as _j
        m = MagicMock()
        m.read.return_value = _j.dumps(payload).encode("utf-8")
        m.__enter__.return_value = m
        return m

    def test_transient_ssl_eof_retried_once(self):
        import ssl as _ssl
        import urllib.error as _ue
        payload = {"query": {"search": [{"pageid": 9, "title": "R",
                                         "snippet": "s"}]}}
        err = _ue.URLError(_ssl.SSLError(8, "[SSL: UNEXPECTED_EOF_WHILE_READING]"))
        with patch("urllib.request.urlopen",
                   side_effect=[err, self._fake_resp(payload)]) as uo:
            with patch("time.sleep", return_value=None):
                out = R._wiki_api_search("q", "zh", 5)
        self.assertEqual(uo.call_count, 2)
        self.assertEqual(out["query"]["search"][0]["title"], "R")

    def test_two_failures_raise(self):
        import urllib.error as _ue
        with patch("urllib.request.urlopen",
                   side_effect=_ue.URLError("boom")):
            with patch("time.sleep", return_value=None):
                with self.assertRaises(RuntimeError):
                    R._wiki_api_search("q", "zh", 5)

class NormalizeCommonsTest(unittest.TestCase):
    SAMPLE = {"query": {"pages": [
        {"title": "File:Pantone 448 C.png",
         "imageinfo": [{"url": "https://upload.wikimedia.org/x/Pantone_448_C.png?utm_source=commons.wikimedia.org",
                        "thumburl": "https://upload.wikimedia.org/x/800px-Pantone_448_C.png?utm_source=a",
                        "width": 1600, "height": 900, "mime": "image/png",
                        "extmetadata": {
                            "LicenseShortName": {"value": "Public domain"},
                            "Artist": {"value": '<a href="//x">Ali</a>'},
                            "ImageDescription": {"value": "Pantone 448 C"}}}]},
        "not-a-dict",
        {"title": "File:Broken.jpg"},  # 无 imageinfo：仍归一化，字段为空
    ]}}

    def test_normalize_commons(self):
        out = R.normalize_commons(self.SAMPLE)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["backend"], "commons")
        self.assertEqual(out[0]["source"], "wikimedia-commons")
        self.assertEqual(out[0]["title"], "Pantone 448 C.png")
        self.assertIn("commons.wikimedia.org/wiki/File%3APantone_448_C.png",
                      out[0]["url"])  # quote 编码冒号，与 wiki 后端行为一致
        self.assertIn("Public domain", out[0]["snippet"])
        self.assertNotIn("<a", out[0]["snippet"])  # Artist HTML 已剥离
        self.assertEqual(out[0]["extra"]["thumburl"],
                         "https://upload.wikimedia.org/x/800px-Pantone_448_C.png")
        self.assertEqual(out[0]["extra"]["width"], 1600)
        self.assertEqual(out[0]["extra"]["filetitle"], "File:Pantone 448 C.png")

    def test_utm_stripped_and_missing_imageinfo(self):
        out = R.normalize_commons(self.SAMPLE)
        broken = out[1]
        self.assertEqual(broken["extra"]["thumburl"], "")
        self.assertEqual(broken["extra"]["license"], "未知授权")
        self.assertIn("未知授权", broken["snippet"])  # 缺失授权信息时显式标注，而非空值

    def test_normalize_commons_empty(self):
        self.assertEqual(R.normalize_commons({}), [])
        self.assertEqual(R.normalize_commons({"query": {}}), [])

    def test_html_entities_unescaped(self):
        raw = {"query": {"pages": [{"title": "File:E.png",
                                    "imageinfo": [{"extmetadata": {
                                        "ImageDescription": {"value": "Square &amp; Fruit"},
                                        "Artist": {"value": "A &amp; B"}}}]}]}}
        out = R.normalize_commons(raw)
        self.assertIn("Square & Fruit", out[0]["snippet"])
        self.assertNotIn("&amp;", out[0]["snippet"])


class CommonsRunTest(unittest.TestCase):
    def test_run_returns_normalized(self):
        payload = {"query": {"pages": [{"title": "File:A.png",
                                        "imageinfo": [{"thumburl": "http://x/t",
                                                       "width": 10, "height": 5,
                                                       "extmetadata": {}}]}]}}
        with patch.object(R, "_commons_api_search", return_value=payload):
            out = R._commons_run("q", 5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["backend"], "commons")


class CommonsRetryTest(unittest.TestCase):
    def _fake_resp(self, payload):
        import json as _j
        m = MagicMock()
        m.read.return_value = _j.dumps(payload).encode("utf-8")
        m.__enter__.return_value = m
        return m

    def test_transient_ssl_eof_retried_once(self):
        import ssl as _ssl
        import urllib.error as _ue
        payload = {"query": {"pages": [{"title": "File:R.png"}]}}
        err = _ue.URLError(_ssl.SSLError(8, "[SSL: UNEXPECTED_EOF_WHILE_READING]"))
        with patch("urllib.request.urlopen",
                   side_effect=[err, self._fake_resp(payload)]) as uo:
            with patch("time.sleep", return_value=None):
                out = R._commons_api_search("q", 5)
        self.assertEqual(uo.call_count, 2)
        self.assertEqual(out["query"]["pages"][0]["title"], "File:R.png")

    def test_two_failures_raise(self):
        import urllib.error as _ue
        with patch("urllib.request.urlopen",
                   side_effect=_ue.URLError("boom")):
            with patch("time.sleep", return_value=None):
                with self.assertRaises(RuntimeError):
                    R._commons_api_search("q", 5)

    def test_commons_uses_shared_retry_helper(self):
        # 共享重试逻辑与 wiki 同源：确认 wiki 抽取重构后重试语义未变
        self.assertIs(R._wiki_api_search.__globals__["_wikimedia_get_json"],
                      R._commons_api_search.__globals__["_wikimedia_get_json"])

    def test_check_ok(self):
        status, msg = R._commons_check()
        self.assertEqual(status, "ok")
        self.assertIn("免凭证", msg)




if __name__ == "__main__":
    unittest.main()

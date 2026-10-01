#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_router.py 测试：fallback 链语义、doctor 隔离、归一化。

全部用 mock 后端，不发起真实网络请求。
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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
        self.assertEqual([b.name for b in bs], ["tavily", "xhs", "bili"])

    def test_none_is_auto(self):
        self.assertEqual([b.name for b in R.resolve_backends(None)],
                         ["tavily", "xhs", "bili"])

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
        self.assertEqual([b.name for b in R.BACKENDS], ["tavily", "xhs", "bili"])

    def test_each_backend_has_run_and_check(self):
        for b in R.BACKENDS:
            self.assertTrue(callable(b.run))
            self.assertTrue(callable(b.check))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_text_measure.py"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.text_measure import FontCache, measure, pil_available, _resolve_font


class TestTextMeasure(unittest.TestCase):
    def test_pil_available(self):
        # omarchy 有 PIL；无 PIL 环境下应优雅降级而非崩
        self.assertIsInstance(pil_available(), bool)

    def test_resolve_font(self):
        p = _resolve_font(None)
        # 有字体返回路径，无字体返回 None，都不抛异常
        self.assertTrue(p is None or Path(p).is_file())

    def test_measure_cjk(self):
        w = measure("2026秋冬时尚趋势", 56)
        if w is None:
            self.skipTest("无可用字体")
        # 8 个字符，56px：实测应在 400-520 之间（启发式 448）
        self.assertGreater(w, 400)
        self.assertLess(w, 520)

    def test_measure_latin(self):
        w = measure("Fashion", 56)
        if w is None:
            self.skipTest("无可用字体")
        self.assertGreater(w, 150)
        self.assertLess(w, 300)

    def test_cache_reuse(self):
        c = FontCache()
        f1 = c.get(56)
        f2 = c.get(56)
        self.assertIs(f1, f2)

    def test_measure_empty(self):
        w = measure("", 56)
        # 空字符串：getbbox 可能返回 None → getlength → 0
        self.assertTrue(w is None or w == 0)


class TestTextWidthIntegration(unittest.TestCase):
    def test_qa_text_width_pil_first(self):
        from scripts.qa_layout import text_width
        w = text_width("2026秋冬时尚趋势", 56)
        # PIL 实测 460 附近；纯启发式 448
        self.assertGreater(w, 400)
        self.assertLess(w, 520)

    def test_qa_text_width_fallback(self):
        # family 传一个不存在的，_resolve_font 兜底仍可能找到；直接测启发式分支
        from scripts import qa_layout
        w = qa_layout.text_width("ABC", 10)
        self.assertGreater(w, 0)


if __name__ == "__main__":
    unittest.main()

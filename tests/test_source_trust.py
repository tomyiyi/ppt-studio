#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_source_trust.py -- source_trust.py 单元测试"""
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_trust import (
    domain_prior,
    recency_multiplier,
    corroboration_bonus,
    score_sources,
    load_domain_trust,
    main,
)


class TestDomainPrior(unittest.TestCase):
    def setUp(self):
        self.table = {"pantone.com": 95, "vogue.com": 80}

    def test_exact_domain(self):
        score, _ = domain_prior("https://www.pantone.com/report", self.table)
        self.assertEqual(score, 95)

    def test_subdomain_fallback(self):
        score, _ = domain_prior("https://en.vogue.com/article", self.table)
        self.assertEqual(score, 80)

    def test_unknown_defaults_40(self):
        score, reason = domain_prior("https://random-xyz.net/x", self.table)
        self.assertEqual(score, 40)
        self.assertIn("默认 40", reason)

    def test_bad_url(self):
        score, _ = domain_prior("not-a-url", self.table)
        self.assertEqual(score, 40)


class TestRecency(unittest.TestCase):
    def test_recent(self):
        m, _ = recency_multiplier("2026-09-01")
        self.assertEqual(m, 1.0)

    def test_old(self):
        m, _ = recency_multiplier("2020-01-01")
        self.assertEqual(m, 0.5)

    def test_missing(self):
        m, _ = recency_multiplier(None)
        self.assertEqual(m, 1.0)

    def test_invalid(self):
        m, _ = recency_multiplier("not-a-date")
        self.assertEqual(m, 1.0)


class TestCorroboration(unittest.TestCase):
    def test_bonus_when_shared_keywords(self):
        sources = [
            {"title": "BioFluff plant-based fur Louis Vuitton", "snippet": "vegan fur vest"},
            {"title": "Louis Vuitton BioFluff partnership fur", "snippet": "plant-based materials"},
            {"title": "BioFluff vegan fur fashion week", "snippet": "Louis Vuitton collab"},
            {"title": "unrelated cooking recipe pasta", "snippet": "italian food"},
        ]
        bonus = corroboration_bonus(sources)
        self.assertEqual(bonus[0][0], 10)
        self.assertEqual(bonus[3][0], 0)


class TestScoreSources(unittest.TestCase):
    def test_grade_mapping(self):
        sources = [
            {"url": "https://www.pantone.com/x", "title": "Pantone official", "published_at": "2026-08-01"},
            {"url": "https://unknown-blog-12345.net/x", "title": "random thoughts", "published_at": "2022-01-01"},
        ]
        out = score_sources(sources)
        # pantone: 95 prior, recent → A
        self.assertEqual(out[0]["grade"], "A")
        self.assertGreaterEqual(out[0]["trust"], 80)
        # unknown + old → D
        self.assertEqual(out[1]["grade"], "D")
        self.assertLess(out[1]["trust"], 40)

    def test_reasons_present(self):
        out = score_sources([{"url": "https://www.vogue.com/x"}])
        self.assertIn("trust", out[0])
        self.assertIn("trust_reasons", out[0])
        self.assertIn("grade", out[0])
        self.assertTrue(len(out[0]["trust_reasons"]) >= 3)

    def test_old_credible_does_not_collapse(self):
        out = score_sources([{"url": "https://www.pantone.com/x", "published_at": "2020-01-01"}])
        # 老但可信：围绕中性点衰减，不应崩盘到 D
        self.assertGreaterEqual(out[0]["trust"], 60)

    def test_domain_trust_file_loads(self):
        table = load_domain_trust()
        self.assertIn("pantone.com", table)
        self.assertGreater(table["pantone.com"], 90)

    def test_load_domain_trust_custom_table(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            custom_file = Path(td) / "custom_trust.json"
            custom_file.write_text(json.dumps({"mycustomdomain.com": 88}), encoding="utf-8")
            table = load_domain_trust(custom_file)
            self.assertEqual(table.get("mycustomdomain.com"), 88)

    def test_main_cli_with_base_dir_and_relative_paths(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            in_file = base / "inputs" / "sources.json"
            in_file.parent.mkdir(parents=True, exist_ok=True)
            in_file.write_text(
                json.dumps([
                    {"url": "https://www.pantone.com/article", "title": "Pantone 2026 Trend", "published_at": "2026-09-01"}
                ]),
                encoding="utf-8"
            )
            code = main(
                ["-i", "inputs/sources.json", "-o", "outputs/scored.json"],
                base_dir=base
            )
            self.assertEqual(code, 0)
            out_file = base / "outputs" / "scored.json"
            self.assertTrue(out_file.is_file())
            scored = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(len(scored), 1)
            self.assertEqual(scored[0]["grade"], "A")
            self.assertGreaterEqual(scored[0]["trust"], 80)

    def test_main_cli_with_base_dir_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            in_file = base / "inputs" / "sources.json"
            in_file.parent.mkdir(parents=True, exist_ok=True)
            in_file.write_text(
                json.dumps([
                    {"url": "https://www.pantone.com/article", "title": "Pantone 2026 Trend", "published_at": "2026-09-01"}
                ]),
                encoding="utf-8"
            )
            code = main(
                ["-i", "inputs/sources.json", "-o", "outputs/scored.json", "--base-dir", str(base)]
            )
            self.assertEqual(code, 0)
            out_file = base / "outputs" / "scored.json"
            self.assertTrue(out_file.is_file())
            scored = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(len(scored), 1)
            self.assertEqual(scored[0]["grade"], "A")
            self.assertGreaterEqual(scored[0]["trust"], 80)


if __name__ == "__main__":
    unittest.main()

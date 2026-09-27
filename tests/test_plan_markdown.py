import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("plan_markdown", ROOT / "scripts" / "plan_markdown.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PlanMarkdownTests(unittest.TestCase):
    def test_comparison_table_contract(self):
        plan=MODULE.build_plan("x.md", "# D\n\n## Compare\n| A | B |\n| --- | --- |\n| a | b |\n| c | d |\n| e | f |".encode())
        self.assertEqual(plan["slides"][1]["blocks"],[{"type":"comparison-table","headers":["A","B"],"rows":[["a","b"],["c","d"],["e","f"]]}])
        for source in ("# D\n## X\n| A | B | C |\n| --- | --- | --- |\n| a | b | c |\n| d | e | f |", "# D\n## X\n| A | B |\n| --- | --- |\n| a | b |"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError): MODULE.build_plan("x.md",source.encode())
    def test_quote_block_and_attribution(self):
        plan=MODULE.build_plan("x.md", "# D\n\n## Principle\n> First line\n> Second line\n> — AgentFlow".encode())
        self.assertEqual(plan["slides"][1]["blocks"],[{"type":"quote","lines":["First line","Second line"],"attribution":"AgentFlow"}])
    def test_basic_slide_plan(self):
        plan = MODULE.build_plan("article.md", b"# Deck\nIntro\n\n## One\nBody\n\n## Two\nMore")
        self.assertEqual([slide["kind"] for slide in plan["slides"]], ["cover", "content", "content"])
        self.assertEqual([slide["id"] for slide in plan["slides"]], ["01", "02", "03"])

    def test_content_is_lossless_except_whitespace_normalisation(self):
        plan = MODULE.build_plan("x.md", b"# D\nCover words\n\n## S\nLine one\nline two")
        self.assertEqual(plan["slides"][0]["blocks"][0]["text"], "Cover words")
        self.assertEqual(plan["slides"][1]["blocks"][0]["text"], "Line one line two")

    def test_bullets_are_one_block(self):
        plan = MODULE.build_plan("x.md", b"# D\n\n## S\n- A\n* B\n- C")
        self.assertEqual(plan["slides"][1]["blocks"], [{"type": "bullets", "items": ["A", "B", "C"]}])

    def test_ordered_steps_require_consecutive_start_at_one(self):
        plan = MODULE.build_plan("x.md", b"# D\n\n## S\nIntro\n\n1. A\n2. B\n3. C")
        self.assertEqual(plan["slides"][1]["blocks"], [{"type":"paragraph","text":"Intro"},{"type":"steps","items":["A","B","C"]}])
        for source in (b"# D\n## S\n2. A\n3. B", b"# D\n## S\n1. A\n3. B", b"# D\n## S\n1. A\n1. B"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "ordered steps"):
                    MODULE.build_plan("x.md", source)

    def test_serialisation_is_deterministic_and_hashed(self):
        source = b"# D\n\n## S\nBody\n"
        first = MODULE.build_plan("x.md", source)
        second = MODULE.build_plan("x.md", source)
        self.assertEqual(json.dumps(first, ensure_ascii=False, indent=2), json.dumps(second, ensure_ascii=False, indent=2))
        self.assertEqual(len(first["source_sha256"]), 64)

    def test_invalid_headings_fail(self):
        for source in (b"## S", b"# A\n# B", b"# D\n### S"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    MODULE.build_plan("x.md", source)

    def test_unsupported_structures_fail(self):
        for source in (b"# D\n## S\n| a | b |",):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "unsupported markdown structure"):
                    MODULE.build_plan("x.md", source)

    def test_metric_list_contract(self):
        plan=MODULE.build_plan("x.md", b"# D\n\n## K\n\n- A: 1\n- B: 2")
        self.assertEqual(plan["slides"][1]["blocks"][0]["type"], "metric-list")
        for source in (b"# D\n## K\n- A: 1", b"# D\n## K\n- A: 1\n- B: 2\n- C: 3\n- D: 4\n- E: 5"):
            with self.assertRaisesRegex(ValueError, "metric list"):
                MODULE.build_plan("x.md", source)
        with self.assertRaisesRegex(ValueError, "mixed metric and plain"):
            MODULE.build_plan("x.md", b"# D\n## K\n- A: 1\n- ordinary bullet")


if __name__ == "__main__":
    unittest.main()

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
    def test_hierarchy_tree_contract(self):
        source=b"# D\n## Runtime\n- Runtime\n  - Planning\n  - Tools\n  - Recovery\n  - Verification"
        block=MODULE.build_plan("x.md",source)["slides"][1]["blocks"][0]
        self.assertEqual(block["type"],"hierarchy-tree")
        self.assertEqual(len(block["children"]),4)
        flat=MODULE.build_plan("x.md",b"# D\n## S\n- A\n- B")["slides"][1]["blocks"][0]
        self.assertEqual(flat["type"],"bullets")
        with self.assertRaises(ValueError): MODULE.build_plan("x.md",b"# D\n## S\n- R\n  - A\n  - B\n  - C\n  - D\n  - E")
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

    def test_faq_contract_and_strict_boundaries(self):
        for count in (2, 3, 4):
            pairs = "\n\n".join(f"Q: question {i}\nA: answer {i}" for i in range(count))
            plan = MODULE.build_plan("x.md", f"# D\n\n## FAQ\n\n{pairs}".encode())
            block = plan["slides"][1]["blocks"]
            self.assertEqual(block[0]["type"], "faq")
            self.assertEqual(len(block[0]["items"]), count)
        for count in (1, 5):
            pairs = "\n\n".join(f"Q: question {i}\nA: answer {i}" for i in range(count))
            with self.assertRaisesRegex(ValueError, "faq block requires 2-4"):
                MODULE.build_plan("x.md", f"# D\n\n## FAQ\n\n{pairs}".encode())
        invalid = (
            "# D\n## FAQ\nQ: q",
            "# D\n## FAQ\nA: a\nQ: q\nA: a",
            "# D\n## FAQ\nQ: q\nQ: q2\nA: a2",
            "# D\n## FAQ\nQ: q\nA: a\nA: a2",
            "# D\n## FAQ\nQ:\nA: a",
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(ValueError): MODULE.build_plan("x.md", source.encode())

    def test_faq_markers_are_not_stolen_from_other_structures(self):
        code = b"# D\n\n## Code\n```python\nQ: q\nA: a\nprint(1)\n```"
        self.assertEqual(MODULE.build_plan("x.md", code)["slides"][1]["blocks"][0]["type"], "code")
        prose = MODULE.build_plan("x.md", b"# D\n\n## Text\nq: ordinary\nA question: ordinary")
        self.assertNotEqual(prose["slides"][1]["blocks"][0]["type"], "faq")


if __name__ == "__main__":
    unittest.main()

def _funnel_contract(self):
    source=b"# D\n\n## Funnel\n\n1. Request => capture\n2. Plan => prepare\n3. Execute => run\n4. Verify => check"
    block=MODULE.build_plan("x.md",source)["slides"][1]["blocks"][0]
    self.assertEqual(block["type"],"funnel-stages")
    self.assertEqual(MODULE.build_plan("x.md",b"# D\n## S\n1. A\n2. B\n3. C")["slides"][1]["blocks"][0]["type"],"steps")
    for count in (2,6):
        items="\n".join(f"{i}. S{i} => D{i}" for i in range(1,count+1))
        with self.assertRaises(ValueError): MODULE.build_plan("x.md",f"# D\n## F\n{items}".encode())
PlanMarkdownTests.test_funnel_contract=_funnel_contract

def _decision_matrix_regression_test(self):
    source=b"# D\n\n## Next\n\n| Option | Impact | Effort |\n| --- | --- | --- |\n| A | High | Medium |\n| B | Medium | Low |\n| C | Low | High |"
    self.assertEqual(MODULE.build_plan("x.md", source)["slides"][1]["blocks"][0]["type"], "decision-matrix")
    with self.assertRaisesRegex(ValueError, "decision matrix impact"):
        MODULE.build_plan("x.md", source.replace(b"High | Medium", b"Critical | Medium"))
PlanMarkdownTests.test_decision_matrix_regression = _decision_matrix_regression_test


def _swimlane_contract(self):
    source=b"# D\n## Handoffs\n| Stage | Owner | Output |\n| --- | --- | --- |\n| Understand | Agent | Plan |\n| Execute | Tools | Result |\n| Verify | Agent | Accepted |"
    block=MODULE.build_plan("x.md",source)["slides"][1]["blocks"][0]
    self.assertEqual(block["type"], "swimlane-handoff")
    self.assertEqual(block["owners"], ["Agent", "Tools"])
    for rows in (2,6):
        data="\n".join(f"| S{i} | Agent | O{i} |" for i in range(rows))
        source=f"# D\n## H\n| Stage | Owner | Output |\n| --- | --- | --- |\n{data}".encode()
        with self.assertRaises(ValueError): MODULE.build_plan("x.md",source)
    source=b"# D\n## H\n| Stage | Owner | Output |\n| --- | --- | --- |\n| S1 | Agent | O1 |\n| S2 | Tools | O2 |\n| S3 | Human | O3 |\n| S4 | Runtime | O4 |"
    with self.assertRaisesRegex(ValueError, "2-3 distinct owners"):
        MODULE.build_plan("x.md",source)
PlanMarkdownTests.test_swimlane_handoff_contract=_swimlane_contract


def _trend_series_contract(self):
    source=b"# D\n## Trend\n| Period | Value |\n| --- | --- |\n| W1 | 42 |\n| W2 | 58 |\n| W3 | 71 |\n| W4 | 83 |"
    block=MODULE.build_plan("x.md",source)["slides"][1]["blocks"][0]
    self.assertEqual(block["type"], "trend-series")
    self.assertEqual(block["items"], [{"period":"W1","value":42},{"period":"W2","value":58},{"period":"W3","value":71},{"period":"W4","value":83}])
    ordinary=b"# D\n## Compare\n| Name | Score |\n| --- | --- |\n| A | High |\n| B | Low |"
    self.assertEqual(MODULE.build_plan("x.md",ordinary)["slides"][1]["blocks"][0]["type"], "comparison-table")
    cases = [
        b"# D\n## T\n| Period | Value |\n| --- | --- |\n| W1 | 1 |\n| W2 | 2 |",
        b"# D\n## T\n| Period | Value |\n| --- | --- |\n| W1 | 1 |\n| W2 | 2 |\n| W3 | 3 |\n| W4 | 4 |\n| W5 | 5 |\n| W6 | 6 |\n| W7 | 7 |",
        b"# D\n## T\n| Period | Value |\n| --- | --- |\n| W1 | -1 |\n| W2 | 2 |",
        b"# D\n## T\n| Period | Value |\n| --- | --- |\n| W1 | 1 |\n| W1 | 2 |",
        b"# D\n## T\n| Period | Value |\n| --- | --- |\n| W1 | 1% |\n| W2 | 2 |",
    ]
    for bad in cases:
        with self.subTest(source=bad):
            with self.assertRaises(ValueError): MODULE.build_plan("x.md",bad)
PlanMarkdownTests.test_trend_series_contract=_trend_series_contract


def _composition_contract(self):
    source=b"# D\n## C\n| Segment | Share |\n| --- | --- |\n| Browser | 35% |\n| Code | 30% |\n| Search | 20% |\n| Files | 15% |"
    block=MODULE.build_plan("x.md",source)["slides"][1]["blocks"][0]
    self.assertEqual(block["type"], "composition-data")
    self.assertEqual([x["share"] for x in block["items"]], [35,30,20,15])
    for bad in (b"# D\n## C\n| Segment | Share |\n| --- | --- |\n| A | 20% |\n| B | 20% |", b"# D\n## C\n| Segment | Share |\n| --- | --- |\n| A | 7% |\n| B | 93% |", b"# D\n## C\n| Segment | Share |\n| --- | --- |\n| A | 35 |\n| B | 65 |", b"# D\n## C\n| Segment | Share |\n| --- | --- |\n| A | 35% |\n| A | 65% |"):
        with self.assertRaises(ValueError): MODULE.build_plan("x.md",bad)
PlanMarkdownTests.test_composition_contract=_composition_contract

def _waterfall_contract(self):
    plan = MODULE.build_plan("x.md", b"# T\n\n| Driver | Delta |\n| --- | --- |\n| A | +2.5 |\n| B | -1 |\n| C | +3 |")
    self.assertEqual(plan["slides"][0]["blocks"][0]["type"], "waterfall-data")

PlanMarkdownTests.test_waterfall_contract=_waterfall_contract

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("assign_layout_intent", ROOT / "scripts" / "assign_layout_intent.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def plan(slides):
    return {"schema": "ppt-studio-slide-plan/v1", "slides": slides}


class AssignLayoutIntentTests(unittest.TestCase):
    def test_comparison_table_layout_and_mixed_reject(self):
        source=b"{}"; table={"type":"comparison-table","headers":["A","B"],"rows":[["a","b"],["c","d"]]}
        self.assertEqual(MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[table]}]),source)["slides"][0]["layout"],"comparison-table")
        with self.assertRaisesRegex(ValueError,"mixed comparison"):
            MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[{"type":"paragraph","text":"x"},table]}]),source)
    def test_three_card_and_four_paragraph_reject(self):
        source=b"{}"
        paragraphs=[{"type":"paragraph","text":str(i)} for i in range(3)]
        self.assertEqual(MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":paragraphs}]),source)["slides"][0]["layout"],"three-card")
        with self.assertRaisesRegex(ValueError,"at most 3"):
            MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":paragraphs+[{'type':'paragraph','text':'4'}]}]),source)
    def test_quote_layout_and_mixed_rejected(self):
        source=b"{}"; q={"type":"quote","lines":["a"]}
        self.assertEqual(MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[q]}]),source)["slides"][0]["layout"],"quote-callout")
        with self.assertRaisesRegex(ValueError,"mixed paragraph"):
            MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[{"type":"paragraph","text":"x"},q]}]),source)
    def test_empty_content_maps_to_section_divider_and_one_paragraph_stays_statement(self):
        source = b"source"
        intent = MODULE.build_intent(plan([
            {"id": "01", "kind": "content", "blocks": []},
            {"id": "02", "kind": "content", "blocks": [{"type": "paragraph", "text": "x"}]},
        ]), source)
        self.assertEqual([s["layout"] for s in intent["slides"]], ["section-divider", "statement"])
    def test_fixed_mapping(self):
        source = json.dumps(plan([
            {"id": "01", "kind": "cover", "blocks": []},
            {"id": "02", "kind": "content", "blocks": [{"type": "paragraph", "text": "x"}]},
            {"id": "03", "kind": "content", "blocks": [{"type": "bullets", "items": ["x"]}]},
            {"id": "04", "kind": "content", "blocks": [{"type": "paragraph", "text": "a"}, {"type": "paragraph", "text": "b"}]},
        ]), ensure_ascii=False, indent=2).encode() + b"\n"
        intent = MODULE.build_intent(json.loads(source), source)
        self.assertEqual([s["layout"] for s in intent["slides"]], ["cover", "statement", "statement-list", "statement-split"])

    def test_bullets_win_when_paragraph_also_exists(self):
        source = b"{}"
        intent = MODULE.build_intent(plan([{"id": "01", "kind": "content", "blocks": [
            {"type": "paragraph", "text": "x"}, {"type": "bullets", "items": ["y"]}
        ]}]), source)
        self.assertEqual(intent["slides"][0]["layout"], "statement-list")

    def test_steps_layout_and_mixed_steps_rejected(self):
        source=b"{}"
        self.assertEqual(MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[{"type":"steps","items":["a","b"]}]}]),source)["slides"][0]["layout"],"process-steps")
        with self.assertRaisesRegex(ValueError, "mixed bullets"):
            MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[{"type":"steps","items":["a","b"]},{"type":"bullets","items":["x"]}]}]),source)

    def test_output_has_no_content_copy_and_hashes_plan_bytes(self):
        source = b'{"schema":"ppt-studio-slide-plan/v1","slides":[]}'
        intent = MODULE.build_intent(plan([{"id": "01", "kind": "cover", "blocks": []}]), source)
        self.assertEqual(set(intent), {"schema", "source_plan_sha256", "slides"})
        self.assertEqual(intent["source_plan_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(set(intent["slides"][0]), {"id", "layout"})

    def test_invalid_schema_or_kind_fails(self):
        with self.assertRaises(ValueError):
            MODULE.build_intent({"schema": "bad", "slides": []}, b"{}")
        with self.assertRaises(ValueError):
            MODULE.build_intent(plan([{"id": "01", "kind": "chart", "blocks": []}]), b"{}")

    def test_duplicate_or_non_contiguous_ids_fail(self):
        for ids in (("01", "01"), ("01", "03")):
            with self.subTest(ids=ids):
                with self.assertRaisesRegex(ValueError, "unique and contiguous"):
                    MODULE.build_intent(plan([
                        {"id": ids[0], "kind": "cover", "blocks": []},
                        {"id": ids[1], "kind": "content", "blocks": []},
                    ]), b"{}")

    def test_invalid_block_fails(self):
        with self.assertRaises(ValueError):
            MODULE.build_intent(plan([{"id": "01", "kind": "content", "blocks": [{"type": "table"}]}]), b"{}")

    def test_serialisation_is_deterministic(self):
        source = b"source"
        p = plan([{"id": "01", "kind": "cover", "blocks": []}])
        first = json.dumps(MODULE.build_intent(p, source), ensure_ascii=False, indent=2) + "\n"
        second = json.dumps(MODULE.build_intent(p, source), ensure_ascii=False, indent=2) + "\n"
        self.assertEqual(first, second)

    def test_metric_highlights_layout_and_mixed_reject(self):
        source=b"{}"; metric={"type":"metric-list","items":[{"label":"A","value":"1"},{"label":"B","value":"2"}]}
        self.assertEqual(MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[metric]}]),source)["slides"][0]["layout"],"metric-highlights")
        with self.assertRaisesRegex(ValueError,"mixed metric"):
            MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[metric,{"type":"quote","lines":["x"]}]}]),source)


if __name__ == "__main__":
    unittest.main()

def _funnel_layout(self):
    source=b"{}"; block={"type":"funnel-stages","items":[{"label":"A","description":"a"},{"label":"B","description":"b"},{"label":"C","description":"c"}]}
    self.assertEqual(MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[block]}]),source)["slides"][0]["layout"],"funnel-stages")
    with self.assertRaises(ValueError): MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[block,{"type":"quote","lines":["x"]}]}]),source)
AssignLayoutIntentTests.test_funnel_layout=_funnel_layout

def _decision_matrix_layout_test(self):
    source=b"{}"; block={"type":"decision-matrix","headers":["Option","Impact","Effort"],"rows":[["A","High","Low"],["B","Low","High"]]}
    self.assertEqual(MODULE.build_intent(plan([{"id":"01","kind":"content","blocks":[block]}]),source)["slides"][0]["layout"],"decision-matrix")
AssignLayoutIntentTests.test_decision_matrix_layout = _decision_matrix_layout_test

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


if __name__ == "__main__":
    unittest.main()

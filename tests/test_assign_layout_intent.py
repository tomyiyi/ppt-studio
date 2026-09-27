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
    def test_fixed_mapping(self):
        source = json.dumps(plan([
            {"id": "01", "kind": "cover", "blocks": []},
            {"id": "02", "kind": "content", "blocks": [{"type": "paragraph", "text": "x"}]},
            {"id": "03", "kind": "content", "blocks": [{"type": "bullets", "items": ["x"]}]},
        ]), ensure_ascii=False, indent=2).encode() + b"\n"
        intent = MODULE.build_intent(json.loads(source), source)
        self.assertEqual([s["layout"] for s in intent["slides"]], ["cover", "statement", "statement-list"])

    def test_bullets_win_when_paragraph_also_exists(self):
        source = b"{}"
        intent = MODULE.build_intent(plan([{"id": "01", "kind": "content", "blocks": [
            {"type": "paragraph", "text": "x"}, {"type": "bullets", "items": ["y"]}
        ]}]), source)
        self.assertEqual(intent["slides"][0]["layout"], "statement-list")

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

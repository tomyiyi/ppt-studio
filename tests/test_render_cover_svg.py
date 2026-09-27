import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scripts.render_cover_svg import main


class RenderCoverSvgTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.spec = self.root / "spec.md"
        self.spec.write_text("""- background: #112233
- primary_text: #F7F7F9
- secondary_text: #8E8F9A
- accent: #445566
- font_family: Microsoft YaHei, Arial
- caption: 13
- body: 27
- subtitle: 27
- cover: 91
""", encoding="utf-8")
        self.plan = self.root / "plan.json"
        plan = {"schema": "ppt-studio-slide-plan/v1", "slides": [{"id": "01", "kind": "cover", "title": "智流 OS", "blocks": [{"type": "paragraph", "text": "不是更大的模型，是能真正动手的运行时。"}]}]}
        self.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.intent = self.root / "intent.json"
        intent = {"schema": "ppt-studio-layout-intent/v1", "source_plan_sha256": hashlib.sha256(self.plan.read_bytes()).hexdigest(), "slides": [{"id": "01", "layout": "cover"}]}
        self.intent.write_text(json.dumps(intent, indent=2) + "\n", encoding="utf-8")

    def run_main(self):
        out = self.root / "out"
        self.assertEqual(main([str(self.plan), str(self.intent), "--spec", str(self.spec), "-o", str(out)]), 0)
        return out / "01_cover.svg"

    def test_maps_content_and_spec_tokens(self):
        svg = self.run_main().read_text(encoding="utf-8")
        self.assertIn("智流 OS", svg)
        self.assertIn("不是更大的模型，是能真正动手的运行时。", svg)
        self.assertIn('fill="#112233"', svg)
        self.assertIn('font-size="91"', svg)

    def test_plan_hash_mismatch_fails(self):
        self.plan.write_text(self.plan.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaises(ValueError):
            main([str(self.plan), str(self.intent), "--spec", str(self.spec), "-o", str(self.root / "out")])

    def test_cover_bullets_fail(self):
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        plan["slides"][0]["blocks"] = [{"type": "bullets", "items": ["A"]}]
        self.plan.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            main([str(self.plan), str(self.intent), "--spec", str(self.spec), "-o", str(self.root / "out")])

    def test_deterministic_and_xml_contract(self):
        first = self.run_main().read_bytes()
        second = self.run_main().read_bytes()
        self.assertEqual(first, second)
        root = ElementTree.fromstring(first)
        self.assertEqual(root.attrib["viewBox"], "0 0 1280 720")
        ids = {node.attrib.get("id") for node in root.iter() if node.attrib.get("id")}
        self.assertTrue({"background", "cover-title", "cover-claim", "cover-footer"} <= ids)


if __name__ == "__main__":
    unittest.main()

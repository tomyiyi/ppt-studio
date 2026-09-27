import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scripts.render_statement_svg import main


class RenderStatementSvgTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.spec = self.root / "spec.md"
        self.spec.write_text("""- background: #112233
- primary_text: #F7F7F9
- secondary_text: #8E8F9A
- tertiary_text: #7F8090
- accent: #445566
- font_family: Microsoft YaHei, Arial
- kicker: 11
- statement: 91
- body: 27
- caption: 13
""", encoding="utf-8")
        plan = {"schema": "ppt-studio-slide-plan/v1", "slides": [
            {"id": "01", "kind": "cover", "title": "Deck", "blocks": []},
            {"id": "02", "kind": "content", "title": "Has bullets", "blocks": [{"type": "bullets", "items": ["A"]}]},
            {"id": "03", "kind": "content", "title": "自愈改变了什么", "blocks": [{"type": "paragraph", "text": "运行时会选择替代路径并继续执行。"}]},
            {"id": "04", "kind": "content", "title": "下一步", "blocks": [{"type": "paragraph", "text": "挑一个流程交给它跑两周。"}]},
        ]}
        self.plan = self.root / "plan.json"
        self.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.intent = self.root / "intent.json"
        intent = {"schema": "ppt-studio-layout-intent/v1", "source_plan_sha256": hashlib.sha256(self.plan.read_bytes()).hexdigest(), "slides": [{"id": "01", "layout": "cover"}, {"id": "02", "layout": "statement-list"}, {"id": "03", "layout": "statement"}, {"id": "04", "layout": "statement"}]}
        self.intent.write_text(json.dumps(intent, indent=2) + "\n", encoding="utf-8")

    def run_main(self):
        out = self.root / "out"
        self.assertEqual(main([str(self.plan), str(self.intent), "--spec", str(self.spec), "-o", str(out)]), 0)
        return out

    def test_only_statement_slides_are_written(self):
        out = self.run_main()
        self.assertEqual(sorted(p.name for p in out.glob("*.svg")), ["03_statement.svg", "04_statement.svg"])

    def test_content_and_page_count(self):
        svg = (self.run_main() / "03_statement.svg").read_text(encoding="utf-8")
        self.assertIn("自愈改变了什么", svg)
        self.assertIn("运行时会选择替代路径并继续执行。", svg)
        self.assertIn("03 / 04", svg)

    def test_spec_tokens_are_consumed(self):
        svg = (self.run_main() / "03_statement.svg").read_text(encoding="utf-8")
        self.assertIn('fill="#112233"', svg)
        self.assertIn('font-size="91"', svg)

    def test_bullets_are_not_silently_accepted(self):
        intent = json.loads(self.intent.read_text(encoding="utf-8"))
        intent["slides"][1]["layout"] = "statement"
        self.intent.write_text(json.dumps(intent) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            main([str(self.plan), str(self.intent), "--spec", str(self.spec), "-o", str(self.root / "out")])

    def test_title_budget_fails(self):
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        plan["slides"][2]["title"] = "x" * 29
        self.plan.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            main([str(self.plan), str(self.intent), "--spec", str(self.spec), "-o", str(self.root / "out")])

    def test_deterministic_xml_contract(self):
        first = (self.run_main() / "04_statement.svg").read_bytes()
        second = (self.run_main() / "04_statement.svg").read_bytes()
        self.assertEqual(first, second)
        root = ElementTree.fromstring(first)
        self.assertEqual(root.attrib["viewBox"], "0 0 1280 720")
        ids = {node.attrib.get("id") for node in root.iter() if node.attrib.get("id")}
        self.assertTrue({"background", "page-kicker", "statement", "statement-body", "footer"} <= ids)


if __name__ == "__main__":
    unittest.main()

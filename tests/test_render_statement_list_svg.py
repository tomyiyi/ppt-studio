import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scripts.render_statement_list_svg import main


class RenderStatementListSvgTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.spec = self.root / "spec.md"
        self.spec.write_text("""- background: #112233
- primary_text: #F7F7F9
- secondary_text: #8E8F9A
- tertiary_text: #7F8090 # comment
- accent: #445566
- font_family: Microsoft YaHei, Arial
- kicker: 11
- statement: 91
- body: 27
- caption: 13
""", encoding="utf-8")
        plan = {"schema": "ppt-studio-slide-plan/v1", "slides": [
            {"id": "01", "kind": "cover", "title": "Deck", "blocks": []},
            {"id": "02", "kind": "content", "title": "为什么旧自动化会停下来", "blocks": [{"type": "paragraph", "text": "系统仍然只能等人处理。"}, {"type": "bullets", "items": ["故障后等待人工", "分支越补越多", "维护成本持续上升"]}]},
            {"id": "03", "kind": "content", "title": "下一步", "blocks": [{"type": "paragraph", "text": "交给它跑两周。"}]},
            {"id": "04", "kind": "content", "title": "结束", "blocks": [{"type": "paragraph", "text": "完成。"}]},
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

    def test_only_list_slide_is_written(self):
        self.assertEqual([p.name for p in self.run_main().glob("*.svg")], ["02_statement_list.svg"])

    def test_content_and_geometry(self):
        svg = (self.run_main() / "02_statement_list.svg").read_text(encoding="utf-8")
        self.assertIn("为什么旧自动化会停下来", svg)
        self.assertIn("故障后等待人工", svg)
        self.assertIn("02 / 04", svg)
        self.assertIn('<circle cx="88"', svg)

    def test_spec_tokens_are_consumed(self):
        svg = (self.run_main() / "02_statement_list.svg").read_text(encoding="utf-8")
        self.assertIn('fill="#112233"', svg)
        self.assertIn('font-size="91"', svg)

    def test_invalid_bullet_count_fails(self):
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        plan["slides"][1]["blocks"][1]["items"] = ["only"]
        self.plan.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            main([str(self.plan), str(self.intent), "--spec", str(self.spec), "-o", str(self.root / "out")])

    def test_invalid_extra_paragraph_fails(self):
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        plan["slides"][1]["blocks"].insert(1, {"type": "paragraph", "text": "too much"})
        self.plan.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            main([str(self.plan), str(self.intent), "--spec", str(self.spec), "-o", str(self.root / "out")])

    def test_deterministic_xml_contract(self):
        first = (self.run_main() / "02_statement_list.svg").read_bytes()
        second = (self.run_main() / "02_statement_list.svg").read_bytes()
        self.assertEqual(first, second)
        root = ElementTree.fromstring(first)
        self.assertEqual(root.attrib["viewBox"], "0 0 1280 720")
        ids = {node.attrib.get("id") for node in root.iter() if node.attrib.get("id")}
        self.assertTrue({"background", "page-kicker", "statement", "statement-body", "bullet-list", "footer"} <= ids)


if __name__ == "__main__":
    unittest.main()

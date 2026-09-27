import hashlib, json, subprocess, sys, tempfile, unittest
from pathlib import Path

class SectionDividerTests(unittest.TestCase):
    def write_case(self, root, blocks, title="Runtime Architecture"):
        plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"content","title":title,"blocks":blocks}]}
        (root/"plan.json").write_text(json.dumps(plan)); (root/"intent.json").write_text(json.dumps({"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256((root/"plan.json").read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"section-divider"}]}))
        (root/"spec.md").write_text("- background: #000000\n- primary_text: #FFFFFF\n- secondary_text: #CCCCCC\n- accent: #FF0000\n- kicker: 16\n- statement: 56\n- caption: 16\n- font_family: Arial\n")
    def execute(self, root, out):
        return subprocess.run([sys.executable,"scripts/render_section_divider_svg.py",str(root/"plan.json"),str(root/"intent.json"),"--spec",str(root/"spec.md"),"-o",str(out)],capture_output=True,text=True)
    def test_valid_empty_content_and_deterministic(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); self.write_case(r,[]); a=r/"a"; b=r/"b"; self.assertEqual(self.execute(r,a).returncode,0); self.assertEqual(self.execute(r,b).returncode,0); x=(a/"01_section_divider.svg").read_bytes(); self.assertEqual(x,(b/"01_section_divider.svg").read_bytes()); text=x.decode(); self.assertIn("Runtime Architecture",text); self.assertIn("01 / 01",text); self.assertNotIn("statement-body",text)
    def test_non_empty_blocks_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t)
            for blocks in ([{"type":"paragraph","text":"x"}],[{"type":"bullets","items":["x"]}]):
                with self.subTest(blocks=blocks): self.write_case(r,blocks); self.assertNotEqual(self.execute(r,r/"out").returncode,0)
    def test_title_budget_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); self.write_case(r,[],"这是一个明确超过二十八个字符预算的章节标题用于拒绝测试并且禁止自动缩放换行"); self.assertNotEqual(self.execute(r,r/"out").returncode,0)
if __name__=="__main__": unittest.main()

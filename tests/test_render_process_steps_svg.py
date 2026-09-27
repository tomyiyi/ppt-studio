import hashlib, json, subprocess, sys, tempfile, unittest
from pathlib import Path
class ProcessStepsTests(unittest.TestCase):
    def write_case(self,root,blocks,title="Agent 执行流程"):
        plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"content","title":title,"blocks":blocks}]}; (root/"plan.json").write_text(json.dumps(plan)); (root/"intent.json").write_text(json.dumps({"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256((root/"plan.json").read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"process-steps"}]})); (root/"spec.md").write_text("- background: #000000\n- primary_text: #FFFFFF\n- secondary_text: #CCCCCC\n- tertiary_text: #999999\n- accent: #FF0000\n- divider: #222222\n- kicker: 16\n- statement: 56\n- body: 16\n- caption: 16\n- font_family: Arial\n")
    def execute(self,root,out): return subprocess.run([sys.executable,"scripts/render_process_steps_svg.py",str(root/"plan.json"),str(root/"intent.json"),"--spec",str(root/"spec.md"),"-o",str(out)],capture_output=True,text=True)
    def test_valid_and_deterministic(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); self.write_case(r,[{"type":"paragraph","text":"先理解，再执行。"},{"type":"steps","items":["理解目标","制定行动","调用工具","校验结果"]}]); a=r/"a"; b=r/"b"; self.assertEqual(self.execute(r,a).returncode,0); self.assertEqual(self.execute(r,b).returncode,0); x=(a/"01_process_steps.svg").read_bytes(); self.assertEqual(x,(b/"01_process_steps.svg").read_bytes()); text=x.decode(); self.assertIn("理解目标",text); self.assertIn(">01<",text); self.assertIn("01 / 01",text)
    def test_invalid_shapes_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); cases=[[{"type":"steps","items":["a"]}],[{"type":"steps","items":["a","b","c","d","e"]}],[{"type":"paragraph","text":"a"},{"type":"paragraph","text":"b"},{"type":"steps","items":["a","b"]}],[{"type":"bullets","items":["a"]},{"type":"steps","items":["b","c"]}],[{"type":"steps","items":["a"*27,"b"]}]]
            for blocks in cases:
                with self.subTest(blocks=blocks): self.write_case(r,blocks); self.assertNotEqual(self.execute(r,r/"out").returncode,0)
if __name__=="__main__": unittest.main()

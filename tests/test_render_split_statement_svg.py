import hashlib, json, tempfile, unittest
from pathlib import Path
import subprocess,sys
class SplitRendererTests(unittest.TestCase):
    def write_case(self, root, blocks):
        plan = {"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"content","title":"T","blocks":blocks}]}
        (root/"plan.json").write_text(json.dumps(plan))
        (root/"intent.json").write_text(json.dumps({"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256((root/"plan.json").read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"statement-split"}]}))
        (root/"spec.md").write_text("- background: #000000\n- primary_text: #FFFFFF\n- secondary_text: #CCCCCC\n- tertiary_text: #999999\n- accent: #FF0000\n- kicker: 16\n- statement: 56\n- body: 24\n- caption: 16\n- font_family: Arial\n")
    def test_renders_two_columns_and_stable_name(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); self.write_case(r,[{"type":"paragraph","text":"左"},{"type":"paragraph","text":"右"}])
            subprocess.run([sys.executable,"scripts/render_split_statement_svg.py",str(r/"plan.json"),str(r/"intent.json"),"--spec",str(r/"spec.md"),"-o",str(r/"out")],check=True); svg=(r/"out/01_statement_split.svg").read_text(); self.assertIn("statement-separator",svg); self.assertIn("statement-left",svg); self.assertIn("statement-right",svg)
    def test_rejects_bullet_or_long_text(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); self.write_case(r,[{"type":"bullets","items":["禁止"]},{"type":"paragraph","text":"右"}])
            self.assertNotEqual(subprocess.run([sys.executable,"scripts/render_split_statement_svg.py",str(r/"plan.json"),str(r/"intent.json"),"--spec",str(r/"spec.md"),"-o",str(r/"out")]).returncode,0)
            self.write_case(r,[{"type":"paragraph","text":"这是一段明确超过三十四个字符限制的超长文本，用来确认 statement split 渲染器会拒绝它"},{"type":"paragraph","text":"右"}])
            self.assertNotEqual(subprocess.run([sys.executable,"scripts/render_split_statement_svg.py",str(r/"plan.json"),str(r/"intent.json"),"--spec",str(r/"spec.md"),"-o",str(r/"out2")]).returncode,0)
if __name__=="__main__": unittest.main()

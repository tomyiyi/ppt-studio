import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
class QuoteTests(unittest.TestCase):
 def write(self,root,blocks):
  p={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"content","title":"Principle","blocks":blocks}]}; (root/"plan.json").write_text(json.dumps(p)); (root/"intent.json").write_text(json.dumps({"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256((root/"plan.json").read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"quote-callout"}]})); (root/"spec.md").write_text("- background: #000000\n- primary_text: #FFFFFF\n- secondary_text: #CCCCCC\n- accent: #FF0000\n- kicker: 16\n- statement: 56\n- caption: 16\n- font_family: Arial\n")
 def execute(self,r,o): return subprocess.run([sys.executable,"scripts/render_quote_callout_svg.py",str(r/"plan.json"),str(r/"intent.json"),"--spec",str(r/"spec.md"),"-o",str(o)],capture_output=True)
 def test_valid_deterministic(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t); self.write(r,[{"type":"quote","lines":["第一句","第二句"],"attribution":"AgentFlow"}]); a=r/"a"; b=r/"b"; self.assertEqual(self.execute(r,a).returncode,0); self.assertEqual(self.execute(r,b).returncode,0); x=(a/"01_quote_callout.svg").read_bytes(); self.assertEqual(x,(b/"01_quote_callout.svg").read_bytes()); self.assertIn("AgentFlow",x.decode())
 def test_invalid_shapes(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t)
   for block in ([{"type":"quote","lines":[]}],[{"type":"quote","lines":["a","b","c"]}],[{"type":"paragraph","text":"x"},{"type":"quote","lines":["a"]}],[{"type":"quote","lines":["x"*43]}]):
    with self.subTest(block=block): self.write(r,block); self.assertNotEqual(self.execute(r,r/"o").returncode,0)

import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
class ComparisonTests(unittest.TestCase):
 def write(self,r,block):
  p={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"content","title":"Compare","blocks":[block]}]};(r/"plan.json").write_text(json.dumps(p));(r/"intent.json").write_text(json.dumps({"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256((r/"plan.json").read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"comparison-table"}]}));(r/"spec.md").write_text("- background: #000000\n- surface: #12131A\n- primary_text: #FFFFFF\n- secondary_text: #CCCCCC\n- accent: #FF0000\n- divider: #222222\n- kicker: 16\n- body: 16\n- caption: 16\n- font_family: Arial\n")
 def execute(self,r,o):return subprocess.run([sys.executable,"scripts/render_comparison_table_svg.py",str(r/"plan.json"),str(r/"intent.json"),"--spec",str(r/"spec.md"),"-o",str(o)],capture_output=True)
 def test_valid_deterministic(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);b={"type":"comparison-table","headers":["Agent","传统"],"rows":[["上下文","预设"],["多工具","固定接口"],["恢复","预编码"]]};self.write(r,b);a=r/"a";c=r/"c";self.assertEqual(self.execute(r,a).returncode,0);self.assertEqual(self.execute(r,c).returncode,0);self.assertEqual((a/"01_comparison_table.svg").read_bytes(),(c/"01_comparison_table.svg").read_bytes())
 def test_invalid_shapes(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t)
   for b in ({"type":"comparison-table","headers":["A","B","C"],"rows":[["a","b","c"],["d","e","f"]]},{"type":"comparison-table","headers":["A","B"],"rows":[["a","b"]]},{"type":"comparison-table","headers":["A","B"],"rows":[["" ,"b"],["c","d"]]}):
    with self.subTest(block=b):self.write(r,b);self.assertNotEqual(self.execute(r,r/"o").returncode,0)

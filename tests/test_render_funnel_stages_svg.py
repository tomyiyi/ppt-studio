import hashlib, importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
S=importlib.util.spec_from_file_location("render_funnel_stages_svg",ROOT/"scripts/render_funnel_stages_svg.py"); M=importlib.util.module_from_spec(S); S.loader.exec_module(M)
class FunnelRendererTests(unittest.TestCase):
 def run_render(self,root,count=4):
  root.mkdir(parents=True,exist_ok=True); items=[{"label":f"S{i}","description":f"D{i}"} for i in range(count)]
  plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"02","kind":"content","title":"Execution Funnel","blocks":[{"type":"funnel-stages","items":items}]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"02","layout":"funnel-stages"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); old=sys.argv
  try: sys.argv=["x",str(pp),str(ip),"--spec",str(ROOT/"projects/agentflow-os-launch/spec_lock.md"),"-o",str(root/"o")]; M.main()
  finally: sys.argv=old
  return (root/"o"/"02_funnel_stages.svg").read_bytes()
 def test_deterministic_3_to_5(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); a=self.run_render(root/"a",3); b=self.run_render(root/"b",5); c=self.run_render(root/"c",5); self.assertIn(b"width=\"1280\"",b); self.assertEqual(b,c); self.assertNotEqual(a,b)
 def test_invalid_count_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError): self.run_render(Path(d)/"bad",2)
if __name__=='__main__': unittest.main()

import hashlib, importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location("r",ROOT/"scripts/render_swimlane_handoff_svg.py"); r=importlib.util.module_from_spec(sp); sp.loader.exec_module(r)
class SwimlaneRendererTests(unittest.TestCase):
 def test_deterministic_and_connectors(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"content","title":"Handoffs","blocks":[{"type":"swimlane-handoff","owners":["Agent","Tools"],"rows":[["Understand","Agent","Plan"],["Execute","Tools","Result"],["Verify","Agent","Accepted"]]}]}]}; p=root/"p.json"; p.write_text(json.dumps(plan)); i=root/"i.json"; i.write_text(json.dumps({"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"swimlane-handoff"}]})); spec=root/"s.txt"; spec.write_text("")
   old=sys.argv
   for name in ("a","b"):
    sys.argv=["render",str(p),str(i),"--spec",str(spec),"-o",str(root/name)]; r.main()
   sys.argv=old
   a=(root/"a/01_swimlane_handoff.svg").read_bytes(); b=(root/"b/01_swimlane_handoff.svg").read_bytes()
   self.assertEqual(a,b); self.assertIn(b"<path",a); self.assertEqual(a.count(b"<rect"),4)

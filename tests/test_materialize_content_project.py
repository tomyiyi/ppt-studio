import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import materialize_content_project as m

class Tests(unittest.TestCase):
 def test_hierarchy_tree_roster_name(self):
  self.assertEqual(m.RENDERERS["hierarchy-tree"].name,"render_hierarchy_tree_svg.py")
 def test_cover_and_three_card_roster(self):
   with tempfile.TemporaryDirectory() as n:
    root=Path(n); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","blocks":[]},{"id":"02","kind":"content","title":"T","blocks":[{"type":"paragraph","text":"a"},{"type":"paragraph","text":"b"},{"type":"paragraph","text":"c"}]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"three-card"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); a,r=m.load(pp); b,_=m.load(ip); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_three_card.svg"])
 def test_cover_and_comparison_table_roster(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","blocks":[]},{"id":"02","kind":"content","title":"P","blocks":[{"type":"comparison-table","headers":["A","B"],"rows":[["a","b"],["c","d"]]}]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"comparison-table"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); a,r=m.load(pp); b,_=m.load(ip); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_comparison_table.svg"])
 def test_cover_and_quote_roster(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","blocks":[]},{"id":"02","kind":"content","title":"P","blocks":[{"type":"quote","lines":["a"]}]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"quote-callout"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); a,r=m.load(pp); b,_=m.load(ip); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_quote_callout.svg"])
 def test_cover_and_process_steps_roster(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","blocks":[]},{"id":"02","kind":"content","title":"Flow","blocks":[{"type":"steps","items":["a","b"]}]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"process-steps"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); a,r=m.load(pp); b,_=m.load(ip); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_process_steps.svg"])
 def test_cover_and_section_divider_roster(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","blocks":[]},{"id":"02","kind":"content","title":"Runtime Architecture","blocks":[]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"section-divider"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); a,r=m.load(pp); b,_=m.load(ip); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_section_divider.svg"])
 def fixture(self,root):
  plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01"},{"id":"02"},{"id":"03"},{"id":"04"}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan))
  it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"statement-list"},{"id":"03","layout":"statement"},{"id":"04","layout":"statement-split"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); return pp,ip
 def test_files_and_hash(self):
  with tempfile.TemporaryDirectory() as n:
   p,i=self.fixture(Path(n)); a,r=m.load(p); b,_=m.load(i); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_statement_list.svg","03_statement.svg","04_statement_split.svg"])
 def test_unsupported_hash_and_nonempty(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); p,i=self.fixture(root); d=json.loads(i.read_text()); d["slides"][0]["layout"]="bad"; i.write_text(json.dumps(d))
   with self.assertRaises(ValueError): m.main([str(p),str(i),"--spec",str(p),"-o",str(root/"o")])
   p,i=self.fixture(root); p.write_text(p.read_text()+"x")
   with self.assertRaises(ValueError): m.main([str(p),str(i),"--spec",str(p),"-o",str(root/"o")])
 def test_atomic_failure_and_empty_output(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); p,i=self.fixture(root); out=root/"o"
   with patch.object(m,"run_renderer",side_effect=RuntimeError("boom")):
    with self.assertRaises(RuntimeError): m.main([str(p),str(i),"--spec",str(p),"-o",str(out)])
   self.assertFalse(out.exists()); out.mkdir(); (out/"old").write_text("x")
   with self.assertRaises(ValueError): m.main([str(p),str(i),"--spec",str(p),"-o",str(out)])
 def test_deterministic(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); p,i=self.fixture(root)
   def fake(renderer,*args): (args[-1]/({"render_cover_svg.py":"01_cover.svg","render_statement_list_svg.py":"02_statement_list.svg","render_statement_svg.py":"03_statement.svg","render_split_statement_svg.py":"04_statement_split.svg"}[renderer.name])).write_text(renderer.name)
   with patch.object(m,"run_renderer",side_effect=fake): m.main([str(p),str(i),"--spec",str(p),"-o",str(root/"a")]); m.main([str(p),str(i),"--spec",str(p),"-o",str(root/"b")])
   self.assertEqual(sorted(x.name for x in (root/"a").iterdir()),sorted(x.name for x in (root/"b").iterdir()))
 def test_cover_and_metric_highlights_roster(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","blocks":[]},{"id":"02","kind":"content","title":"K","blocks":[{"type":"metric-list","items":[{"label":"A","value":"1"},{"label":"B","value":"2"}]}]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"metric-highlights"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); a,r=m.load(pp); b,_=m.load(ip); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_metric_highlights.svg"])

 def test_cover_and_decision_matrix_roster(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","blocks":[]},{"id":"02","kind":"content","title":"Next","blocks":[{"type":"decision-matrix","headers":["Option","Impact","Effort"],"rows":[["A","High","Low"],["B","Low","High"]]}]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"decision-matrix"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); a,r=m.load(pp); b,_=m.load(ip); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_decision_matrix.svg"])

 def test_cover_and_funnel_roster(self):
  with tempfile.TemporaryDirectory() as n:
   root=Path(n); plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","blocks":[]},{"id":"02","kind":"content","title":"F","blocks":[{"type":"funnel-stages","items":[{"label":"A","description":"a"},{"label":"B","description":"b"},{"label":"C","description":"c"}]}]}]}; pp=root/"p.json"; pp.write_text(json.dumps(plan)); it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"funnel-stages"}]}; ip=root/"i.json"; ip.write_text(json.dumps(it)); a,r=m.load(pp); b,_=m.load(ip); self.assertEqual(m.expected_files(a,b,r),["01_cover.svg","02_funnel_stages.svg"])

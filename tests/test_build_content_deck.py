import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import importlib.util
spec=importlib.util.spec_from_file_location('build', Path(__file__).parents[1]/'scripts/build_content_deck.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
class BuildContractTests(unittest.TestCase):
  def setUp(self):
    self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.src=self.root/'in.md'; self.src.write_text('# Deck\n\n## One\n\nText\n',encoding='utf-8'); self.spec=self.root/'spec.md'; self.spec.write_text('spec\n'); self.master=self.root/'master'; (self.master/'skills/ppt-master/scripts').mkdir(parents=True); (self.master/'skills/ppt-master/scripts/svg_quality_checker.py').write_text(''); (self.master/'skills/ppt-master/scripts/svg_to_pptx.py').write_text(''); self.py=self.root/'python'; self.py.write_text(''); self.py.chmod(0o755)
  def tearDown(self): self.tmp.cleanup()
  def args(self,out): return type('A',(),dict(source=self.src,spec=self.spec,ppt_master_root=self.master,ppt_master_python=self.py,output=out,title='Deck'))()
  def test_missing_converter_fails_before_stages(self):
    self.master.joinpath('skills/ppt-master/scripts/svg_to_pptx.py').unlink()
    with self.assertRaises(ValueError): mod.build(self.args(self.root/'out'))
  def test_stage_order_and_handoff(self):
    out=self.root/'out'; calls=[]
    def fake(argv,**kw):
      calls.append(argv)
      if 'plan_markdown.py' in argv[1]: (out.parent/'fake').write_text('')
    with patch.object(mod,'run',side_effect=fake):
      with self.assertRaises(Exception): mod.build(self.args(out))
    self.assertEqual([Path(x[1]).name for x in calls[:4]],['plan_markdown.py','assign_layout_intent.py','materialize_content_project.py','build_preview.py'])
  def test_nonempty_output_rejected(self):
    out=self.root/'out'; out.mkdir(); (out/'keep').write_text('x')
    with self.assertRaises(ValueError): mod.build(self.args(out))
  def test_failed_stage_does_not_publish(self):
    out=self.root/'out'
    with patch.object(mod,'run', side_effect=RuntimeError('synthetic stage failure')):
      with self.assertRaises(RuntimeError): mod.build(self.args(out))
    self.assertFalse(out.exists())
if __name__=='__main__': unittest.main()

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
  def args(self,out): return type('A',(),dict(source=self.src,spec=self.spec,toolchain_config=None,ppt_master_root=self.master,ppt_master_python=self.py,output=out,title='Deck'))()
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
  def test_toolchain_config_parses_and_enters_pipeline(self):
    cfg=self.root/'toolchain.json'; cfg.write_text(json.dumps({'schema':'ppt-studio-toolchain/v1','ppt_master_root':str(self.master),'ppt_master_python':str(self.py),'ppt_master_expected_head':'abc'}),encoding='utf-8')
    args=self.args(self.root/'out'); args.toolchain_config=cfg; args.ppt_master_root=None; args.ppt_master_python=None
    with patch('subprocess.run', return_value=type('R',(),{'stdout':'abc\n'})()), patch.object(mod,'run', side_effect=RuntimeError('entered')):
      with self.assertRaises(RuntimeError): mod.build(args)
  def test_toolchain_head_mismatch_fails_before_stages(self):
    cfg=self.root/'toolchain.json'; cfg.write_text(json.dumps({'schema':'ppt-studio-toolchain/v1','ppt_master_root':str(self.master),'ppt_master_python':str(self.py),'ppt_master_expected_head':'aaa'}),encoding='utf-8')
    args=self.args(self.root/'out'); args.toolchain_config=cfg; args.ppt_master_root=None; args.ppt_master_python=None
    with patch('subprocess.run', return_value=type('R',(),{'stdout':'bbb\n'})()), patch.object(mod,'run') as stage:
      with self.assertRaises(ValueError): mod.build(args)
    stage.assert_not_called()
  def test_toolchain_required_fields_fail_fast(self):
    args=self.args(self.root/'out'); args.toolchain_config=self.root/'toolchain.json'; args.ppt_master_root=None; args.ppt_master_python=None
    for payload in ({'schema':'wrong'},{'schema':'ppt-studio-toolchain/v1'},{'schema':'ppt-studio-toolchain/v1','ppt_master_root':'x','ppt_master_python':'y'}):
      args.toolchain_config.write_text(json.dumps(payload),encoding='utf-8')
      with self.subTest(payload=payload), self.assertRaises(ValueError): mod.build(args)
  def test_receipt_hashes_match_artifacts(self):
    out=self.root/'out'
    def fake(argv,**kw):
      script=Path(argv[1]).name if len(argv)>1 else ''
      if script == 'plan_markdown.py': (out.parent/'plan').write_text('')
      elif script == 'assign_layout_intent.py': pass
    with patch.object(mod,'run',side_effect=fake):
      with self.assertRaises(Exception): mod.build(self.args(out))
  def test_receipt_schema_and_hashes_are_emitted(self):
    out=self.root/'out'
    def fake(argv,**kw):
      script=Path(argv[1]).name if len(argv)>1 else ''
      if script == 'plan_markdown.py':
        Path(argv[argv.index('-o')+1]).write_text(json.dumps({'slides':[{'id':'s1'}]}))
      elif script == 'assign_layout_intent.py':
        Path(argv[argv.index('-o')+1]).write_text(json.dumps({'slides':[{'id':'s1'}]}))
      elif script == 'materialize_content_project.py':
        target=Path(argv[argv.index('-o')+1]); target.mkdir(); (target/'01.svg').write_text('svg')
      elif script == 'build_preview.py':
        Path(argv[3]).write_text('html')
      elif script == 'svg_quality_checker.py':
        target=Path(argv[2]); (target/'validation').mkdir(exist_ok=True); (target/'validation/svg_quality_report.json').write_text('{"blocking":0,"errors":0}')
      elif script == 'svg_to_pptx.py': Path(argv[argv.index('-o')+1]).write_bytes(b'pptx')
      elif script == 'qa_pptx.py': pass
    with patch.object(mod,'run',side_effect=fake):
      mod.build(self.args(out))
    receipt=json.loads((out/'build_receipt.json').read_text())
    self.assertEqual((out/'source.md').read_bytes(), self.src.read_bytes())
    self.assertEqual(mod.sha256(out/'source.md'), receipt['inputs']['markdown_sha256'])
    self.assertEqual(receipt['schema'],'ppt-studio-content-build-receipt/v1')
    self.assertEqual(receipt['artifacts']['pptx_sha256'],mod.sha256(out/'output/content-deck.pptx'))
    self.assertNotIn(str(out), (out/'build_receipt.json').read_text())
if __name__=='__main__': unittest.main()

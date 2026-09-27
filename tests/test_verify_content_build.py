import hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import importlib.util

spec = importlib.util.spec_from_file_location('verify', Path(__file__).parents[1] / 'scripts/verify_content_build.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class VerifyBuildTests(unittest.TestCase):
  def setUp(self):
    self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.md=self.root/'source.md'; self.md.write_text('# source\n')
    for rel, data in [('spec_lock.md',b'spec'),('slide_plan.json',b'{"slides":[{"id":"s1"}]}'),('layout_intent.json',b'intent'),('preview/content-deck.html',b'html'),('validation/svg_quality_report.json',b'quality'),('output/content-deck.pptx',b'pptx'),('svg_output/01_cover.svg',b'svg')]:
      p=self.root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)
    self.receipt={'schema':'ppt-studio-content-build-receipt/v1','slides':1,'inputs':{},'toolchain':{'ppt_master_head':'a'*40},'artifacts':{'svg':{}}}
    def sha(rel): return hashlib.sha256((self.root/rel).read_bytes()).hexdigest()
    self.receipt['inputs']={'markdown_sha256':hashlib.sha256(self.md.read_bytes()).hexdigest(),'spec_sha256':sha('spec_lock.md'),'slide_plan_sha256':sha('slide_plan.json'),'layout_intent_sha256':sha('layout_intent.json')}
    self.receipt['artifacts']={'svg':{'01_cover.svg':sha('svg_output/01_cover.svg')},'html_sha256':sha('preview/content-deck.html'),'svg_quality_report_sha256':sha('validation/svg_quality_report.json'),'pptx_sha256':sha('output/content-deck.pptx')}
    (self.root/'build_receipt.json').write_text(json.dumps(self.receipt))
  def tearDown(self): self.tmp.cleanup()
  def test_valid_bundle(self): self.assertEqual(mod.verify(self.root,self.md),0)
  def test_bundled_source_is_default(self):
    self.assertEqual(mod.verify(self.root, None),0)
  def test_bundled_source_tamper_fails(self):
    self.md.write_text('# changed\n')
    with self.assertRaises(ValueError): mod.verify(self.root, None)
  def test_hash_mismatch_fails(self):
    self.md.write_text('# changed\n')
    with self.assertRaises(ValueError): mod.verify(self.root,self.md)
  def test_missing_declared_artifact_fails(self):
    (self.root/'output/content-deck.pptx').unlink()
    with self.assertRaises(ValueError): mod.verify(self.root,self.md)
  def test_svg_roster_and_unsafe_name_fail(self):
    (self.root/'svg_output/02_extra.svg').write_bytes(b'extra')
    with self.assertRaises(ValueError): mod.verify(self.root,self.md)
    (self.root/'svg_output/02_extra.svg').unlink()
    self.receipt['artifacts']['svg']['../evil.svg']=self.receipt['artifacts']['svg'].pop('01_cover.svg')
    (self.root/'build_receipt.json').write_text(json.dumps(self.receipt))
    with self.assertRaises(ValueError): mod.verify(self.root,self.md)
if __name__=='__main__': unittest.main()

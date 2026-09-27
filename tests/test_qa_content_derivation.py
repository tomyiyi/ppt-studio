import json,tempfile,unittest,subprocess
from pathlib import Path
from unittest import mock
import scripts.qa_content_derivation as subject

class DerivationTests(unittest.TestCase):
    def fixture(self,root): (root/"build_receipt.json").write_text('{"slides":4}')
    def test_all_pass_in_order(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); self.fixture(root); calls=[]
            with mock.patch.object(subject,"run",side_effect=lambda a:calls.append(a)):
                subject.qa(root,root/"cfg")
            self.assertEqual([Path(a[1]).name for a in calls],["qa_content_ir_rederive.py","qa_content_svg_rederive.py","qa_content_html_rederive.py","qa_content_pptx_rederive.py"])
            self.assertIn("--toolchain-config",calls[-1])
    def test_failure_short_circuits(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); self.fixture(root); calls=[]
            def fail(a): calls.append(a); raise subprocess.CalledProcessError(2,a)
            with mock.patch.object(subject,"run",side_effect=fail):
                with self.assertRaises(ValueError) as ctx: subject.qa(root,root/"cfg")
            self.assertIn("ir",str(ctx.exception)); self.assertEqual(len(calls),1)
    def test_pptx_failure_is_named(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); self.fixture(root); count=0
            def fail(a):
                nonlocal count; count+=1
                if count==4: raise subprocess.CalledProcessError(2,a)
            with mock.patch.object(subject,"run",side_effect=fail):
                with self.assertRaisesRegex(ValueError,"pptx"): subject.qa(root,root/"cfg")
if __name__=="__main__": unittest.main()

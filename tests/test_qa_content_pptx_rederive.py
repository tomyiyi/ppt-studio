import tempfile,unittest
from pathlib import Path
from unittest import mock
import scripts.qa_content_pptx_rederive as subject

class PPTXTests(unittest.TestCase):
    def test_head_mismatch_short_circuits(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); (r/"build_receipt.json").write_text('{"toolchain":{"ppt_studio_head":"x","ppt_master_head":"m"}}'); (r/"cfg.json").write_text('{"schema":"ppt-studio-toolchain/v1","ppt_master_expected_head":"m"}')
            with mock.patch.object(subject,"run"),mock.patch.object(subject,"git",return_value="y"):
                with self.assertRaises(ValueError): subject.rederive(r,r/"cfg.json")
    def test_matching_calls_converter_and_qa(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); (r/"build_receipt.json").write_text('{"slides":1,"toolchain":{"ppt_studio_head":"h","ppt_master_head":"m"},"artifacts":{"svg":{}}}'); (r/"spec_lock.md").write_text("x"); (r/"output").mkdir(); (r/"output/content-deck.pptx").write_bytes(b"x"); (r/"cfg.json").write_text('{"schema":"ppt-studio-toolchain/v1","ppt_master_expected_head":"m","ppt_master_root":"/m","ppt_master_python":"python"}')
            with mock.patch.object(subject,"run") as calls,mock.patch.object(subject,"git",return_value="h"),mock.patch.object(subject.subprocess,"run") as sp:
                sp.return_value.stdout="m"; subject.slides=lambda p:{"ppt/slides/slide1.xml":b"x"}; subject.rederive(r,r/"cfg.json")
            self.assertTrue(any("svg_to_pptx.py" in str(x) for x in calls.call_args_list))
    def test_slide_xml_mismatch_rejects(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t); (r/"build_receipt.json").write_text('{"slides":1,"toolchain":{"ppt_studio_head":"h","ppt_master_head":"m"},"artifacts":{"svg":{}}}'); (r/"spec_lock.md").write_text("x"); (r/"output").mkdir(); (r/"output/content-deck.pptx").write_bytes(b"x"); (r/"cfg.json").write_text('{"schema":"ppt-studio-toolchain/v1","ppt_master_expected_head":"m","ppt_master_root":"/m","ppt_master_python":"python"}')
            with mock.patch.object(subject,"run"),mock.patch.object(subject,"git",return_value="h"),mock.patch.object(subject.subprocess,"run") as sp:
                sp.return_value.stdout="m"; seen=[]
                def fake_slides(p):
                    seen.append(p); return {"ppt/slides/slide1.xml": b"x" if len(seen)==2 else b"y"}
                subject.slides=fake_slides
                with self.assertRaises(ValueError): subject.rederive(r,r/"cfg.json")
if __name__=="__main__": unittest.main()

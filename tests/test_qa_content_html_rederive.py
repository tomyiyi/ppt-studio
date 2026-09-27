import tempfile, unittest
from pathlib import Path
from unittest import mock
import scripts.qa_content_html_rederive as subject

class HTMLTests(unittest.TestCase):
    def fixture(self, root, html=b"html"):
        (root/"svg_output").mkdir(); (root/"svg_output/01.svg").write_bytes(b"svg"); (root/"preview").mkdir(); (root/"preview/content-deck.html").write_bytes(html); (root/"build_receipt.json").write_text('{"slides": 1, "toolchain": {"ppt_studio_head": "h"}, "artifacts": {"svg": {"01.svg": "x"}}}')
    def test_matching_invocation_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.fixture(root)
            def fake(argv):
                if str(subject.PREVIEW) in argv: Path(argv[3]).write_bytes(b"html")
            with mock.patch.object(subject,"run",side_effect=fake), mock.patch.object(subject,"git_output",return_value="h"), mock.patch.object(subject.subprocess,"run") as git:
                git.return_value.stdout=""; subject.rederive(root)
    def test_head_dirty_and_html_mismatch_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.fixture(root)
            with self.subTest("head"):
                with mock.patch.object(subject,"run"), mock.patch.object(subject,"git_output",return_value="x"):
                    with self.assertRaises(ValueError): subject.rederive(root)
            with self.subTest("html"):
                def fake(argv):
                    if str(subject.PREVIEW) in argv: Path(argv[3]).write_bytes(b"different")
                with mock.patch.object(subject,"run",side_effect=fake), mock.patch.object(subject,"git_output",return_value="h"), mock.patch.object(subject.subprocess,"run") as git:
                    git.return_value.stdout=""
                    with self.assertRaises(ValueError): subject.rederive(root)
    def test_verify_failure_short_circuits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.fixture(root)
            with mock.patch.object(subject,"run",side_effect=RuntimeError("reject")):
                with self.assertRaises(RuntimeError): subject.rederive(root)

if __name__=="__main__": unittest.main()

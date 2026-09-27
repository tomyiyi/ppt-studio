import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest import mock

import scripts.qa_content_svg_rederive as subject


class SVGTests(unittest.TestCase):
    def test_success_materializes_and_accepts_roster(self):
        with tempfile.TemporaryDirectory() as tmp:
            digest=hashlib.sha256(b"x").hexdigest(); root=Path(tmp); (root/"slide_plan.json").write_text("{}"); (root/"layout_intent.json").write_text("{}"); (root/"spec_lock.md").write_text("x"); (root/"build_receipt.json").write_text('{"slides": 1, "toolchain": {"ppt_studio_head": "h"}, "artifacts": {"svg": {"01_cover.svg": "'+digest+'"}}}')
            def fake_run(argv):
                if str(subject.MATERIALIZE) in argv:
                    out=Path(argv[argv.index("-o")+1]); (out/"01_cover.svg").write_bytes(b"x")
            with mock.patch.object(subject,"run",side_effect=fake_run), mock.patch.object(subject,"git_output",return_value="h"), mock.patch.object(subject.subprocess,"run") as git:
                git.return_value.stdout=""; subject.rederive(root)

    def test_svg_mismatch_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); [p.write_text("x") for p in (root/"slide_plan.json",root/"layout_intent.json",root/"spec_lock.md")]; (root/"build_receipt.json").write_text('{"slides": 1, "toolchain": {"ppt_studio_head": "h"}, "artifacts": {"svg": {"01_cover.svg": "wrong"}}}')
            def fake_run(argv):
                if str(subject.MATERIALIZE) in argv:
                    out=Path(argv[argv.index("-o")+1]); (out/"01_cover.svg").write_bytes(b"x")
            with mock.patch.object(subject,"run",side_effect=fake_run), mock.patch.object(subject,"git_output",return_value="h"), mock.patch.object(subject.subprocess,"run") as git:
                git.return_value.stdout=""
                with self.assertRaises(ValueError): subject.rederive(root)

    def test_head_mismatch_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"build_receipt.json").write_text('{"toolchain": {"ppt_studio_head": "expected"}}')
            with mock.patch.object(subject,"run"), mock.patch.object(subject,"git_output",return_value="actual"):
                with self.assertRaises(ValueError): subject.rederive(root)


if __name__=="__main__": unittest.main()

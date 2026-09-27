import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.qa_content_ir_rederive as subject


class IRRederiveTests(unittest.TestCase):
    def test_success_runs_planner_then_assigner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"source.md").write_text("x"); (root/"slide_plan.json").write_bytes(b"plan"); (root/"layout_intent.json").write_bytes(b"intent"); (root/"build_receipt.json").write_text('{"slides": 1, "toolchain": {"ppt_studio_head": "h"}}')
            calls=[]
            def fake_run(argv):
                calls.append(argv)
                if str(subject.VERIFY) in argv: return
                if str(subject.PLANNER) in argv: Path(argv[argv.index("-o")+1]).write_bytes(b"plan")
                if str(subject.ASSIGNER) in argv: Path(argv[argv.index("-o")+1]).write_bytes(b"intent")
            with mock.patch.object(subject, "run", side_effect=fake_run), mock.patch.object(subject, "git_output", return_value="h"), mock.patch.object(subject.subprocess, "run") as git:
                git.return_value.stdout=""; subject.rederive(root)
            self.assertIn(str(subject.PLANNER), calls[1]); self.assertIn(str(subject.ASSIGNER), calls[2])

    def test_plan_mismatch_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"source.md").write_text("x"); (root/"slide_plan.json").write_bytes(b"bundle"); (root/"layout_intent.json").write_bytes(b"intent"); (root/"build_receipt.json").write_text('{"slides": 1, "toolchain": {"ppt_studio_head": "h"}}')
            def fake_run(argv):
                if str(subject.PLANNER) in argv: Path(argv[argv.index("-o")+1]).write_bytes(b"different")
            with mock.patch.object(subject, "run", side_effect=fake_run), mock.patch.object(subject, "git_output", return_value="h"), mock.patch.object(subject.subprocess, "run") as git:
                git.return_value.stdout=""
                with self.assertRaises(ValueError): subject.rederive(root)

    def test_head_mismatch_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"build_receipt.json").write_text('{"slides": 1, "toolchain": {"ppt_studio_head": "expected"}}')
            with mock.patch.object(subject, "run"), mock.patch.object(subject, "git_output", return_value="actual"):
                with self.assertRaises(ValueError): subject.rederive(root)


if __name__ == "__main__": unittest.main()

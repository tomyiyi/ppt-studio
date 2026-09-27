import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("replay", Path(__file__).parents[1] / "scripts" / "replay_content_build.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ReplayContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        (self.bundle / "source.md").write_bytes(b"# deck\n")
        (self.bundle / "spec_lock.md").write_bytes(b"spec\n")
        (self.bundle / "build_receipt.json").write_text(json.dumps({"slides": 1, "inputs": {}, "toolchain": {"ppt_studio_head": "a" * 40, "ppt_master_head": "b" * 40}}))
        self.config = self.root / "toolchain.json"
        self.config.write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejects_legacy_receipt_before_build(self):
        (self.bundle / "build_receipt.json").write_text(json.dumps({"slides": 1, "toolchain": {}}))
        with patch.object(mod, "run", side_effect=lambda argv: None), patch.object(mod, "head", return_value="a" * 40):
            with self.assertRaisesRegex(ValueError, "missing valid ppt-studio HEAD"):
                mod.replay(self.bundle, self.config, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_head_mismatch_fails_before_builder(self):
        calls = []
        with patch.object(mod, "run", side_effect=lambda argv: calls.append(argv)), patch.object(mod, "head", return_value="b" * 40):
            with self.assertRaisesRegex(ValueError, "does not match current"):
                mod.replay(self.bundle, self.config, self.root / "out")
        self.assertEqual(len(calls), 1)
        self.assertIn("verify_content_build.py", calls[0][1])
        self.assertFalse((self.root / "out").exists())

    def test_success_publishes_after_build_and_verify(self):
        out = self.root / "out"
        calls = []

        def fake(argv):
            calls.append(argv)
            if "build_content_deck.py" in argv[1]:
                target = Path(argv[argv.index("-o") + 1])
                target.mkdir(exist_ok=True)
                (target / "marker").write_text("built")
                (target / "build_receipt.json").write_text(json.dumps({"slides": 1, "inputs": {}, "toolchain": {"ppt_studio_head": "a" * 40, "ppt_master_head": "b" * 40}}))

        with patch.object(mod, "run", side_effect=fake), patch.object(mod, "head", return_value="a" * 40):
            mod.replay(self.bundle, self.config, out)
        self.assertEqual((out / "marker").read_text(), "built")
        self.assertIn("verify_content_build.py", calls[0][1])
        self.assertIn("build_content_deck.py", calls[1][1])
        self.assertIn("verify_content_build.py", calls[2][1])

    def test_source_verifier_failure_does_not_build(self):
        calls = []
        with patch.object(mod, "run", side_effect=RuntimeError("source verify")) as run, patch.object(mod, "head", return_value="a" * 40):
            with self.assertRaisesRegex(RuntimeError, "source verify"):
                mod.replay(self.bundle, self.config, self.root / "out")
        self.assertEqual(len(calls), 0)
        run.assert_called_once()
        self.assertFalse((self.root / "out").exists())

    def test_identity_mismatch_does_not_publish(self):
        out = self.root / "out"
        def fake(argv):
            if "build_content_deck.py" in argv[1]:
                target = Path(argv[argv.index("-o") + 1]); target.mkdir(exist_ok=True)
                (target / "build_receipt.json").write_text(json.dumps({"slides": 2, "inputs": {}, "toolchain": {"ppt_studio_head": "a" * 40, "ppt_master_head": "b" * 40}}))
        with patch.object(mod, "run", side_effect=fake), patch.object(mod, "head", return_value="a" * 40):
            with self.assertRaisesRegex(ValueError, "replay identity mismatch"):
                mod.replay(self.bundle, self.config, out)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()

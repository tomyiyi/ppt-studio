import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("deepqa", Path(__file__).parents[1] / "scripts" / "qa_content_bundle.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class DeepQAContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = Path(self.tmp.name) / "bundle"
        (self.bundle / "preview").mkdir(parents=True)
        (self.bundle / "output").mkdir()
        (self.bundle / "build_receipt.json").write_text(json.dumps({"slides": 4}), encoding="utf-8")
        (self.bundle / "spec_lock.md").write_text("spec", encoding="utf-8")
        (self.bundle / "preview" / "content-deck.html").write_text("html", encoding="utf-8")
        (self.bundle / "output" / "content-deck.pptx").write_bytes(b"pptx")

    def tearDown(self):
        self.tmp.cleanup()

    def test_integrity_runs_before_both_qas_and_success_is_reported(self):
        events = []
        with patch.object(mod, "run_verify", side_effect=lambda bundle: events.append(("verify", bundle))), \
             patch.dict("sys.modules", {"qa_preview": type("Preview", (), {"run_qa_single_preview": staticmethod(lambda *a, **k: events.append(("html", a, k)) or True)})(),
                                        "qa_pptx": type("Pptx", (), {"run_qa_pptx": staticmethod(lambda *a, **k: events.append(("pptx", a, k)) or True)})()}):
            self.assertTrue(mod.deep_qa(self.bundle, verbose=False))
        self.assertEqual([event[0] for event in events], ["verify", "html", "pptx"])
        self.assertEqual(events[2][2]["expected_slides"], 4)
        self.assertEqual(events[2][2]["expected_media"], 0)

    def test_integrity_failure_blocks_qa(self):
        with patch.object(mod, "run_verify", side_effect=ValueError("integrity failed")):
            with self.assertRaisesRegex(ValueError, "integrity failed"):
                mod.deep_qa(self.bundle, verbose=False)

    def test_qa_failure_returns_no_success(self):
        with patch.object(mod, "run_verify"), \
             patch.dict("sys.modules", {"qa_preview": type("Preview", (), {"run_qa_single_preview": staticmethod(lambda *a, **k: False)})(),
                                        "qa_pptx": type("Pptx", (), {"run_qa_pptx": staticmethod(lambda *a, **k: True)})()}):
            with self.assertRaisesRegex(ValueError, "deep QA failed"):
                mod.deep_qa(self.bundle, verbose=False)


if __name__ == "__main__":
    unittest.main()

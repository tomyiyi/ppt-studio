import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("release", Path(__file__).parents[1] / "scripts" / "report_content_release.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ReleaseReportContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.receipt = {
            "schema": "ppt-studio-content-build-receipt/v1",
            "slides": 4,
            "inputs": {
                "markdown_sha256": "1" * 64, "spec_sha256": "2" * 64,
                "slide_plan_sha256": "3" * 64, "layout_intent_sha256": "4" * 64,
            },
            "toolchain": {"ppt_studio_head": "a" * 40, "ppt_master_head": "b" * 40},
        }
        (self.bundle / "build_receipt.json").write_text(json.dumps(self.receipt, indent=2) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_deep_qa_failure_blocks_report(self):
        output = self.root / "report.json"
        with patch.object(mod, "run_deep_qa", side_effect=ValueError("deep QA failed")):
            with self.assertRaisesRegex(ValueError, "deep QA failed"):
                mod.report(self.bundle, output)
        self.assertFalse(output.exists())

    def test_pass_report_copies_provenance_and_qa_contract(self):
        output = self.root / "report.json"
        with patch.object(mod, "run_deep_qa"):
            mod.report(self.bundle, output)
        report = json.loads(output.read_text())
        receipt_bytes = (self.bundle / "build_receipt.json").read_bytes()
        self.assertEqual(report["schema"], "ppt-studio-content-release-report/v1")
        self.assertEqual(report["slides"], 4)
        self.assertEqual(report["build_receipt_sha256"], hashlib.sha256(receipt_bytes).hexdigest())
        self.assertEqual(report["inputs"], self.receipt["inputs"])
        self.assertEqual(report["toolchain"], self.receipt["toolchain"])
        self.assertEqual(report["qa"], {"bundle_integrity": "PASS", "html_preview": "PASS", "native_pptx": "PASS"})
        self.assertFalse(any(key in report for key in ("timestamp", "hostname", "bundle_root", "report_root")))

    def test_deterministic_report_and_invalid_head_reject(self):
        first, second = self.root / "a.json", self.root / "b.json"
        with patch.object(mod, "run_deep_qa"):
            mod.report(self.bundle, first)
            mod.report(self.bundle, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        bad = json.loads((self.bundle / "build_receipt.json").read_text())
        bad["toolchain"]["ppt_studio_head"] = "invalid"
        (self.bundle / "build_receipt.json").write_text(json.dumps(bad), encoding="utf-8")
        with patch.object(mod, "run_deep_qa"):
            with self.assertRaisesRegex(ValueError, "invalid ppt-studio HEAD"):
                mod.report(self.bundle, self.root / "bad.json")


if __name__ == "__main__":
    unittest.main()

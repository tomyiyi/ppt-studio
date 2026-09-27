import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("verify_release", Path(__file__).parents[1] / "scripts" / "verify_content_release.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class VerifyReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.receipt = {
            "slides": 4,
            "inputs": {"markdown_sha256": "1" * 64, "spec_sha256": "2" * 64,
                       "slide_plan_sha256": "3" * 64, "layout_intent_sha256": "4" * 64},
            "toolchain": {"ppt_studio_head": "a" * 40, "ppt_master_head": "b" * 40},
        }
        self.receipt_path = self.bundle / "build_receipt.json"
        self.receipt_path.write_text(json.dumps(self.receipt, indent=2) + "\n", encoding="utf-8")
        self.report_path = self.root / "report.json"
        self.report_path.write_text(json.dumps({
            "schema": "ppt-studio-content-release-report/v1",
            "slides": 4,
            "build_receipt_sha256": hashlib.sha256(self.receipt_path.read_bytes()).hexdigest(),
            "inputs": self.receipt["inputs"],
            "toolchain": self.receipt["toolchain"],
            "qa": {"bundle_integrity": "PASS", "html_preview": "PASS", "native_pptx": "PASS"},
        }, indent=2) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_deep_qa_failure_short_circuits_report_checks(self):
        with patch.object(mod, "run_deep_qa", side_effect=ValueError("deep QA failed")):
            with self.assertRaisesRegex(ValueError, "deep QA failed"):
                mod.verify(self.bundle, self.report_path)

    def test_valid_report_verifies(self):
        with patch.object(mod, "run_deep_qa"):
            mod.verify(self.bundle, self.report_path)

    def test_report_mismatches_reject(self):
        cases = {
            "receipt sha": lambda r: r.__setitem__("build_receipt_sha256", "0" * 64),
            "input": lambda r: r["inputs"].__setitem__("slide_plan_sha256", "0" * 64),
            "head": lambda r: r["toolchain"].__setitem__("ppt_studio_head", "0" * 40),
            "qa": lambda r: r["qa"].__setitem__("native_pptx", "FAIL"),
            "schema": lambda r: r.__setitem__("schema", "wrong"),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                report = json.loads(self.report_path.read_text())
                mutate(report)
                path = self.root / f"{label}.json"
                path.write_text(json.dumps(report), encoding="utf-8")
                with patch.object(mod, "run_deep_qa"):
                    with self.assertRaises(ValueError):
                        mod.verify(self.bundle, path)


if __name__ == "__main__":
    unittest.main()

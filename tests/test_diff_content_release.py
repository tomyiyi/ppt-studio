import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.diff_content_release as subject


HEAD_A = "a" * 40
HEAD_B = "b" * 40


def receipt(markdown="m", svg=None):
    return {
        "slides": 4,
        "inputs": {"markdown_sha256": markdown, "spec_sha256": "s", "slide_plan_sha256": "p", "layout_intent_sha256": "l"},
        "toolchain": {"ppt_studio_head": HEAD_A, "ppt_master_head": HEAD_B},
        "artifacts": {"svg": svg or {"01.svg": "x"}, "html_sha256": "h", "svg_quality_report_sha256": "q", "pptx_sha256": "x"},
    }


class DiffReleaseTests(unittest.TestCase):
    def test_both_verifications_run_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / "a", root / "b"
            for item, value in ((a, receipt()), (b, receipt("changed", {"01.svg": "y", "02.svg": "z"}))):
                item.mkdir(); (item / "build_receipt.json").write_text(json.dumps(value), encoding="utf-8")
            out = root / "diff.json"
            with mock.patch.object(subject, "verify_release") as verify:
                subject.run(a, root / "a-report.json", b, root / "b-report.json", out)
            self.assertEqual(verify.call_count, 2)
            data = json.loads(out.read_text())
            self.assertFalse(data["same_release_identity"])
            self.assertTrue(data["changes"]["inputs"]["markdown_sha256"]["changed"])
            self.assertEqual(data["changes"]["artifacts"]["svg"]["added"], ["02.svg"])

    def test_verification_failure_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / "diff.json"
            with mock.patch.object(subject, "verify_release", side_effect=RuntimeError("reject")):
                with self.assertRaises(RuntimeError):
                    subject.run(root / "a", root / "ar", root / "b", root / "br", out)
            self.assertFalse(out.exists())

    def test_identity_is_true_for_equal_receipts(self):
        value = receipt()
        data = subject.build_diff(value, json.loads(json.dumps(value)))
        self.assertTrue(data["same_release_identity"])
        self.assertEqual(subject.changes_count(data), 0)
        self.assertEqual(data["changes"]["artifacts"]["svg"]["added"], [])
        self.assertEqual(data["changes"]["artifacts"]["svg"]["removed"], [])
        self.assertEqual(data["changes"]["artifacts"]["svg"]["modified"], [])

    def test_mixed_diff_is_deterministic(self):
        a = receipt()
        b = receipt("changed", {"01.svg": "changed", "02.svg": "new"})
        b["toolchain"]["ppt_studio_head"] = "c" * 40
        b["artifacts"]["pptx_sha256"] = "changed-pptx"
        first = subject.build_diff(a, b)
        second = subject.build_diff(json.loads(json.dumps(a)), json.loads(json.dumps(b)))
        self.assertEqual(json.dumps(first, ensure_ascii=False, indent=2), json.dumps(second, ensure_ascii=False, indent=2))
        self.assertFalse(first["same_release_identity"])
        self.assertEqual(first["changes"]["artifacts"]["svg"]["modified"], ["01.svg"])
        self.assertEqual(first["changes"]["artifacts"]["svg"]["added"], ["02.svg"])
        self.assertGreater(subject.changes_count(first), 0)


if __name__ == "__main__":
    unittest.main()

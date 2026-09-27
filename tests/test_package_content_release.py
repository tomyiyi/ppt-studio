import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import scripts.package_content_release as subject


class PackageReleaseTests(unittest.TestCase):
    def test_exact_report_is_verified_and_three_entries_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); bundle = root / "bundle"; bundle.mkdir()
            report = root / "report.json"; report.write_bytes(b'{"slides":4}\n')
            out = root / "package.zip"
            receipt = {"slides": 4, "build_receipt_sha256": "r" * 64}
            with mock.patch.object(subject, "run") as invoke:
                def fake(argv):
                    if str(subject.VERIFY) in argv:
                        staged = Path(argv[-1]); staged.write_text(json.dumps(receipt), encoding="utf-8")
                    elif str(subject.ARCHIVE) in argv:
                        Path(argv[-1]).write_bytes(b"bundle")
                invoke.side_effect = fake
                subject.package(bundle, report, out)
            with zipfile.ZipFile(out) as z:
                self.assertEqual(z.namelist(), ["bundle.zip", "release_package.json", "release_report.json"])

    def test_verification_failure_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); bundle = root / "bundle"; bundle.mkdir(); report = root / "report"; report.write_text("x")
            out = root / "package.zip"
            with mock.patch.object(subject, "run", side_effect=RuntimeError("reject")):
                with self.assertRaises(RuntimeError): subject.package(bundle, report, out)
            self.assertFalse(out.exists())

    def test_existing_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); bundle = root / "bundle"; bundle.mkdir(); report = root / "report"; report.write_text("x"); out = root / "package.zip"; out.write_bytes(b"x")
            with self.assertRaises(ValueError): subject.package(bundle, report, out)


if __name__ == "__main__":
    unittest.main()

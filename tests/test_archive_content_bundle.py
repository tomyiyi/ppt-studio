import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("archive", Path(__file__).parents[1] / "scripts" / "archive_content_bundle.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ArchiveContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "bundle"
        for relative, data in {
            "source.md": b"source", "spec_lock.md": b"spec", "slide_plan.json": b"plan",
            "layout_intent.json": b"intent", "build_receipt.json": json.dumps({"artifacts": {"svg": {"02.svg": "x", "01.svg": "y"}}}).encode(),
            "preview/content-deck.html": b"html", "validation/svg_quality_report.json": b"qa",
            "output/content-deck.pptx": b"pptx", "svg_output/01.svg": b"one", "svg_output/02.svg": b"two",
        }.items():
            path = self.bundle / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_verifies_before_publish_and_uses_canonical_roster(self):
        out = self.root / "bundle.zip"
        with patch.object(mod, "run_verify") as verify:
            mod.archive(self.bundle, out)
        verify.assert_called_once_with(self.bundle)
        with zipfile.ZipFile(out) as archive:
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            self.assertEqual({item.filename for item in archive.infolist()}, {
                "source.md", "spec_lock.md", "slide_plan.json", "layout_intent.json", "build_receipt.json",
                "preview/content-deck.html", "validation/svg_quality_report.json", "output/content-deck.pptx",
                "svg_output/01.svg", "svg_output/02.svg",
            })
            self.assertTrue(all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist()))

    def test_same_bundle_produces_identical_zip_and_existing_output_is_rejected(self):
        first, second = self.root / "a.zip", self.root / "b.zip"
        with patch.object(mod, "run_verify"):
            mod.archive(self.bundle, first)
            mod.archive(self.bundle, second)
        self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
        with self.assertRaisesRegex(ValueError, "output must be absent"):
            with patch.object(mod, "run_verify"):
                mod.archive(self.bundle, first)

    def test_verifier_failure_does_not_publish(self):
        out = self.root / "failed.zip"
        with patch.object(mod, "run_verify", side_effect=ValueError("invalid bundle")):
            with self.assertRaisesRegex(ValueError, "invalid bundle"):
                mod.archive(self.bundle, out)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()

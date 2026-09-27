import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("importer", Path(__file__).parents[1] / "scripts" / "import_content_bundle.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ImportContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.files = {
            "source.md": b"source", "spec_lock.md": b"spec", "slide_plan.json": b"plan",
            "layout_intent.json": b"intent",
            "build_receipt.json": json.dumps({"slides": 2, "artifacts": {"svg": {"01.svg": "x"}}}).encode(),
            "preview/content-deck.html": b"html", "validation/svg_quality_report.json": b"qa",
            "output/content-deck.pptx": b"pptx", "svg_output/01.svg": b"one",
        }
        self.archive = self.root / "bundle.zip"
        self._write_zip(self.archive, self.files)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _write_zip(path, files):
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as output:
            for name, data in files.items():
                output.writestr(name, data)

    def test_valid_canonical_archive_imports_atomically(self):
        target = self.root / "imported"
        with patch.object(mod, "run_verify") as verify:
            mod.import_bundle(self.archive, target)
        verify.assert_called_once()
        verified_path = verify.call_args.args[0]
        self.assertNotEqual(verified_path, target)
        self.assertFalse(verified_path.exists())
        actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
        self.assertEqual(actual, set(self.files))
        self.assertEqual((target / "source.md").read_bytes(), b"source")

    def test_unsafe_or_noncanonical_zip_is_rejected(self):
        cases = {
            "traversal": {**self.files, "../escape.txt": b"x"},
            "extra": {**self.files, "extra/debug.log": b"x"},
            "missing": {name: data for name, data in self.files.items() if name != "source.md"},
        }
        for label, files in cases.items():
            with self.subTest(label=label):
                archive = self.root / f"{label}.zip"
                self._write_zip(archive, files)
                target = self.root / f"{label}-target"
                with patch.object(mod, "run_verify") as verify:
                    with self.assertRaises(ValueError):
                        mod.import_bundle(archive, target)
                verify.assert_not_called()
                self.assertFalse(target.exists())

    def test_post_extract_verifier_failure_does_not_publish(self):
        target = self.root / "failed"
        with patch.object(mod, "run_verify", side_effect=ValueError("invalid bundle")):
            with self.assertRaisesRegex(ValueError, "invalid bundle"):
                mod.import_bundle(self.archive, target)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()

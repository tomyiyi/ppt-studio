import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.diff_content_release_package as subject


class DiffPackageTests(unittest.TestCase):
    def test_package_verification_precedes_import_and_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); a=root/"a.zip"; b=root/"b.zip"; a.write_bytes(b"a"); b.write_bytes(b"b"); out=root/"d.json"
            calls=[]
            def fake_run(argv):
                calls.append(argv)
                if str(subject.DIFF_RELEASE) in argv:
                    Path(argv[argv.index("-o") + 1]).write_text("{}")
            with mock.patch.object(subject, "run", side_effect=fake_run):
                with mock.patch.object(subject, "extract", side_effect=lambda p,r: (r/"bundle", r/"report.json", r/"bundle.zip")):
                    (root/"a").mkdir(); (root/"b").mkdir(); subject.diff(a,b,out)
            self.assertIn(str(subject.VERIFY_PACKAGE), calls[0]); self.assertIn(str(subject.VERIFY_PACKAGE), calls[1])
            self.assertIn(str(subject.DIFF_RELEASE), calls[-1])

    def test_verification_failure_short_circuits_and_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); a=root/"a.zip"; b=root/"b.zip"; a.write_bytes(b"a"); b.write_bytes(b"b"); out=root/"d.json"
            with mock.patch.object(subject, "run", side_effect=RuntimeError("reject")):
                with self.assertRaises(RuntimeError): subject.diff(a,b,out)
            self.assertFalse(out.exists())

    def test_existing_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); a=root/"a.zip"; b=root/"b.zip"; out=root/"d.json"; a.write_bytes(b"a"); b.write_bytes(b"b"); out.write_text("x")
            with self.assertRaises(ValueError): subject.diff(a,b,out)


if __name__ == "__main__": unittest.main()

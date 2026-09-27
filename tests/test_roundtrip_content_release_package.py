import tempfile
import unittest
import zipfile
import json
from pathlib import Path
from unittest import mock

import scripts.roundtrip_content_release_package as subject


class RoundtripTests(unittest.TestCase):
    def test_source_verification_short_circuits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"source.zip"; source.write_bytes(b"x"); out=root/"out.zip"
            with mock.patch.object(subject, "run", side_effect=RuntimeError("reject")):
                with self.assertRaises(RuntimeError): subject.roundtrip(source,out)
            self.assertFalse(out.exists())

    def test_successful_orchestration_publishes_exact_rebuilt_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"source.zip"; out=root/"out.zip"
            with zipfile.ZipFile(source,"w") as z:
                z.writestr("bundle.zip",b"bundle"); z.writestr("release_report.json",b'{"slides":4}'); z.writestr("release_package.json",json.dumps({"slides":4}).encode())
            def fake_run(argv):
                if str(subject.PACKAGE) in argv:
                    Path(argv[argv.index("-o")+1]).write_bytes(source.read_bytes())
            with mock.patch.object(subject, "run", side_effect=fake_run):
                subject.roundtrip(source, out)
            self.assertEqual(out.read_bytes(), source.read_bytes())

    def test_rebuilt_byte_mismatch_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"source.zip"; out=root/"out.zip"
            with zipfile.ZipFile(source,"w") as z:
                z.writestr("bundle.zip",b"bundle"); z.writestr("release_report.json",b'{"slides":4}'); z.writestr("release_package.json",json.dumps({"slides":4}).encode())
            def fake_run(argv):
                if str(subject.PACKAGE) in argv: Path(argv[argv.index("-o")+1]).write_bytes(b"different")
            with mock.patch.object(subject, "run", side_effect=fake_run):
                with self.assertRaises(ValueError): subject.roundtrip(source,out)
            self.assertFalse(out.exists())


if __name__ == "__main__": unittest.main()

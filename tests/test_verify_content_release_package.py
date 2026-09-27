import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import scripts.verify_content_release_package as subject


def make_package(path: Path, report: bytes = b'{"slides": 4, "build_receipt_sha256": "r"}'):
    bundle = b"bundle"
    manifest = {
        "schema": subject.SCHEMA,
        "slides": 4,
        "build_receipt_sha256": "r",
        "bundle_archive_sha256": hashlib.sha256(bundle).hexdigest(),
        "release_report_sha256": hashlib.sha256(report).hexdigest(),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
        for name, data in (("bundle.zip", bundle), ("release_package.json", json.dumps(manifest).encode()), ("release_report.json", report)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)); info.create_system = 3; info.external_attr = 0o100644 << 16; z.writestr(info, data)


class VerifyPackageTests(unittest.TestCase):
    def test_valid_package_runs_import_then_release_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "p.zip"; make_package(package)
            calls = []
            with mock.patch.object(subject, "run", side_effect=lambda argv: calls.append(argv)):
                subject.verify(package)
            self.assertIn(str(subject.IMPORT), calls[0]); self.assertIn(str(subject.VERIFY), calls[1])

    def test_outer_corruption_short_circuits_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind in ("extra", "compression", "bundle_archive_sha256", "release_report_sha256"):
                with self.subTest(kind=kind):
                    package = Path(tmp) / f"{kind}.zip"; make_package(package)
                    with zipfile.ZipFile(package) as z: data = {n: z.read(n) for n in z.namelist()}
                    manifest = json.loads(data["release_package.json"])
                    if kind == "extra": data["extra"] = b"x"
                    elif kind == "compression": pass
                    elif kind == "bundle_archive_sha256": manifest[kind] = "0" * 64
                    else: manifest[kind] = "0" * 64
                    data["release_package.json"] = json.dumps(manifest).encode()
                    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED if kind == "compression" else zipfile.ZIP_STORED) as z:
                        for n, v in data.items(): z.writestr(n, v)
                    with mock.patch.object(subject, "run") as run:
                        with self.assertRaises(ValueError): subject.verify(package)
                        run.assert_not_called()

    def test_rebound_manifest_still_propagates_release_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "p.zip"; report = b'{"slides": 4, "build_receipt_sha256": "r", "stale": true}'
            make_package(package, report)
            with mock.patch.object(subject, "run", side_effect=[None, RuntimeError("stale")]):
                with self.assertRaises(RuntimeError): subject.verify(package)


if __name__ == "__main__": unittest.main()

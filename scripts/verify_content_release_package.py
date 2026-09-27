#!/usr/bin/env python3
"""Read-only verification of a canonical three-entry release package."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMPORT = REPO / "scripts" / "import_content_bundle.py"
VERIFY = REPO / "scripts" / "verify_content_release.py"
SCHEMA = "ppt-studio-content-release-package/v1"
ENTRIES = ["bundle.zip", "release_package.json", "release_report.json"]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def inspect_outer(package: Path) -> tuple[bytes, bytes, dict, int]:
    try:
        with zipfile.ZipFile(package) as outer:
            if outer.namelist() != ENTRIES:
                raise ValueError("release package entries mismatch")
            infos = {info.filename: info for info in outer.infolist()}
            for name in ENTRIES:
                info = infos[name]
                if info.is_dir() or info.compress_type != zipfile.ZIP_STORED:
                    raise ValueError("release package entry contract mismatch")
                if info.date_time != (1980, 1, 1, 0, 0, 0):
                    raise ValueError("release package timestamp mismatch")
                if info.external_attr >> 16 != 0o100644:
                    raise ValueError("release package mode mismatch")
            bundle = outer.read("bundle.zip")
            report = outer.read("release_report.json")
            manifest = json.loads(outer.read("release_package.json").decode("utf-8"))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid release package: {exc}") from exc
    if set(manifest) != {"schema", "slides", "build_receipt_sha256", "bundle_archive_sha256", "release_report_sha256"}:
        raise ValueError("release package manifest schema mismatch")
    if manifest["schema"] != SCHEMA:
        raise ValueError("release package manifest schema mismatch")
    if manifest["bundle_archive_sha256"] != sha256_bytes(bundle):
        raise ValueError("release package mismatch: bundle_archive_sha256")
    if manifest["release_report_sha256"] != sha256_bytes(report):
        raise ValueError("release package mismatch: release_report_sha256")
    try:
        report_obj = json.loads(report.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid release report: {exc}") from exc
    if manifest["slides"] != report_obj.get("slides"):
        raise ValueError("release package mismatch: slides")
    if manifest["build_receipt_sha256"] != report_obj.get("build_receipt_sha256"):
        raise ValueError("release package mismatch: build_receipt_sha256")
    return bundle, report, manifest, int(manifest["slides"])


def run(argv: list[str]) -> None:
    subprocess.run(argv, cwd=REPO, check=True)


def verify(package: Path) -> None:
    bundle_bytes, report_bytes, _manifest, slides = inspect_outer(package.resolve())
    with tempfile.TemporaryDirectory(prefix="release-package-verify-") as tmp:
        root = Path(tmp)
        bundle_zip = root / "bundle.zip"
        report = root / "release_report.json"
        bundle_zip.write_bytes(bundle_bytes)
        report.write_bytes(report_bytes)
        imported = root / "bundle"
        run([sys.executable, str(IMPORT), str(bundle_zip), "-o", str(imported)])
        run([sys.executable, str(VERIFY), str(imported), str(report)])
    print(f"CONTENT_RELEASE_PACKAGE_VERIFIED slides={slides} entries=3")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args(argv)
    try:
        verify(args.package)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify canonical byte-for-byte roundtrip of a release package."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY_PACKAGE = REPO / "scripts" / "verify_content_release_package.py"
VERIFY_RELEASE = REPO / "scripts" / "verify_content_release.py"
IMPORT = REPO / "scripts" / "import_content_bundle.py"
PACKAGE = REPO / "scripts" / "package_content_release.py"


def run(argv: list[str]) -> None:
    subprocess.run(argv, cwd=REPO, check=True)


def roundtrip(source: Path, output: Path) -> None:
    source, output = source.resolve(), output.resolve()
    if not source.is_file():
        raise ValueError(f"missing source package: {source}")
    if output.exists():
        raise ValueError(f"output must be absent: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    rebuilt = staging / "rebuilt.zip"
    try:
        run([sys.executable, str(VERIFY_PACKAGE), str(source)])
        extracted = staging / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(source) as outer:
            bundle_zip = extracted / "bundle.zip"
            report = extracted / "release_report.json"
            bundle_zip.write_bytes(outer.read("bundle.zip"))
            report.write_bytes(outer.read("release_report.json"))
        imported = staging / "imported"
        run([sys.executable, str(IMPORT), str(bundle_zip), "-o", str(imported)])
        run([sys.executable, str(VERIFY_RELEASE), str(imported), str(report)])
        run([sys.executable, str(PACKAGE), str(imported), str(report), "-o", str(rebuilt)])
        if rebuilt.read_bytes() != source.read_bytes():
            raise ValueError("release package roundtrip mismatch")
        os.replace(rebuilt, output)
        slides = 0
        with zipfile.ZipFile(output) as outer:
            import json
            slides = json.loads(outer.read("release_package.json"))["slides"]
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"CONTENT_RELEASE_PACKAGE_ROUNDTRIP_VERIFIED slides={slides}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("source_package", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        roundtrip(args.source_package, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

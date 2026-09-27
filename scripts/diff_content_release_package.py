#!/usr/bin/env python3
"""Orchestrate deterministic diffing of two verified release packages."""
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
DIFF_RELEASE = REPO / "scripts" / "diff_content_release.py"
IMPORT = REPO / "scripts" / "import_content_bundle.py"


def run(argv: list[str]) -> None:
    subprocess.run(argv, cwd=REPO, check=True)


def extract(package: Path, root: Path) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as outer:
        bundle_zip = root / "bundle.zip"
        report = root / "release_report.json"
        bundle_zip.write_bytes(outer.read("bundle.zip"))
        report.write_bytes(outer.read("release_report.json"))
    imported = root / "bundle"
    run([sys.executable, str(IMPORT), str(bundle_zip), "-o", str(imported)])
    return imported, report, bundle_zip


def diff(package_a: Path, package_b: Path, output: Path) -> None:
    package_a, package_b, output = package_a.resolve(), package_b.resolve(), output.resolve()
    if output.exists():
        raise ValueError(f"output must be absent: {output}")
    if not package_a.is_file() or not package_b.is_file():
        raise ValueError("release package is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    temporary = staging / "diff.json"
    try:
        run([sys.executable, str(VERIFY_PACKAGE), str(package_a)])
        run([sys.executable, str(VERIFY_PACKAGE), str(package_b)])
        a, report_a, _ = extract(package_a, staging / "a")
        b, report_b, _ = extract(package_b, staging / "b")
        run([sys.executable, str(DIFF_RELEASE), str(a), str(report_a), str(b), str(report_b), "-o", str(temporary)])
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"CONTENT_RELEASE_PACKAGE_DIFF_REPORTED output={output.name}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("package_a", type=Path)
    parser.add_argument("package_b", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        diff(args.package_a, args.package_b, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

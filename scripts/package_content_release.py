#!/usr/bin/env python3
"""Package a verified content release into a deterministic outer ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "scripts" / "verify_content_release.py"
ARCHIVE = REPO / "scripts" / "archive_content_bundle.py"
SCHEMA = "ppt-studio-content-release-package/v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str]) -> None:
    subprocess.run(argv, cwd=REPO, check=True)


def package(bundle: Path, report: Path, output: Path) -> None:
    bundle, report, output = bundle.resolve(), report.resolve(), output.resolve()
    if not bundle.is_dir():
        raise ValueError(f"missing bundle: {bundle}")
    if not report.is_file():
        raise ValueError(f"missing release report: {report}")
    if output.exists():
        raise ValueError(f"output must be absent: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    temporary = output.parent / f".{output.name}.tmp"
    try:
        staged_report = staging / "release_report.json"
        shutil.copyfile(report, staged_report)
        run([sys.executable, str(VERIFY), str(bundle), str(staged_report)])
        staged_bundle = staging / "bundle.zip"
        run([sys.executable, str(ARCHIVE), str(bundle), "-o", str(staged_bundle)])
        verified = json.loads(staged_report.read_text(encoding="utf-8"))
        manifest = {
            "schema": SCHEMA,
            "slides": verified["slides"],
            "build_receipt_sha256": verified["build_receipt_sha256"],
            "bundle_archive_sha256": sha256(staged_bundle),
            "release_report_sha256": sha256(staged_report),
        }
        (staging / "release_package.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as outer:
            for name in ("bundle.zip", "release_package.json", "release_report.json"):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                outer.writestr(info, (staging / name).read_bytes())
        os.replace(temporary, output)
        print(f"CONTENT_RELEASE_PACKAGED slides={manifest['slides']} files=3")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("release_report", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        package(args.bundle_root, args.release_report, args.output)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

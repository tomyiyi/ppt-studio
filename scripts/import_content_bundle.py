#!/usr/bin/env python3
"""Safely import a canonical content-bundle ZIP into a verified directory."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "scripts" / "verify_content_build.py"


def run_verify(bundle: Path) -> None:
    subprocess.run([sys.executable, str(VERIFY), str(bundle)], cwd=REPO, check=True)


def expected_roster(receipt_bytes: bytes) -> set[str]:
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    svg = receipt.get("artifacts", {}).get("svg")
    if not isinstance(svg, dict):
        raise ValueError("receipt artifacts.svg must be an object")
    names = set()
    for name in svg:
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError("unsafe SVG filename")
        names.add(f"svg_output/{name}")
    names.update({
        "source.md", "spec_lock.md", "slide_plan.json", "layout_intent.json", "build_receipt.json",
        "preview/content-deck.html", "validation/svg_quality_report.json", "output/content-deck.pptx",
    })
    return names


def validate_entries(infos: list[zipfile.ZipInfo]) -> list[zipfile.ZipInfo]:
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if not name or name.endswith("/") or "\\" in name or path.is_absolute() or "" in path.parts or ".." in path.parts:
            raise ValueError(f"unsafe ZIP path: {name!r}")
        if name in seen:
            raise ValueError(f"duplicate ZIP entry: {name}")
        seen.add(name)
        mode = (info.external_attr >> 16) & 0o170000
        if mode in (0o040000, 0o120000) or (mode and mode != 0o100000):
            raise ValueError(f"non-regular ZIP entry: {name}")
        if info.compress_type != zipfile.ZIP_STORED:
            raise ValueError(f"unsupported ZIP compression: {name}")
    return infos


def import_bundle(archive: Path, target: Path) -> None:
    archive = archive.resolve()
    target = target.resolve()
    if not archive.is_file():
        raise ValueError(f"missing archive: {archive}")
    if target.exists():
        raise ValueError(f"target must be absent: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        with zipfile.ZipFile(archive) as source:
            infos = validate_entries(source.infolist())
            by_name = {info.filename: info for info in infos}
            receipt_info = by_name.get("build_receipt.json")
            if receipt_info is None:
                raise ValueError("missing canonical entry: build_receipt.json")
            expected = expected_roster(source.read(receipt_info))
            actual = set(by_name)
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                raise ValueError(f"canonical roster mismatch missing={missing} extra={extra}")
            for name in sorted(expected):
                destination = (temporary / name).resolve()
                if temporary not in destination.parents:
                    raise ValueError(f"unsafe extraction destination: {name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read(by_name[name]))
        run_verify(temporary)
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    receipt = json.loads((target / "build_receipt.json").read_text(encoding="utf-8"))
    print(f"CONTENT_BUNDLE_IMPORTED slides={receipt['slides']} files={len(expected)}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        import_bundle(args.archive, args.output)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

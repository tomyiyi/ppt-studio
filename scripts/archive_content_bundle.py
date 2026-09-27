#!/usr/bin/env python3
"""Export a verified content bundle as a canonical portable ZIP."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "scripts" / "verify_content_build.py"


def run_verify(bundle: Path) -> None:
    subprocess.run([sys.executable, str(VERIFY), str(bundle)], cwd=REPO, check=True)


def roster(bundle: Path) -> list[Path]:
    receipt = json.loads((bundle / "build_receipt.json").read_text(encoding="utf-8"))
    svg = receipt.get("artifacts", {}).get("svg")
    if not isinstance(svg, dict):
        raise ValueError("receipt artifacts.svg must be an object")
    names = []
    for name in svg:
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError("unsafe SVG filename")
        names.append(Path("svg_output") / name)
    paths = [
        Path("source.md"), Path("spec_lock.md"), Path("slide_plan.json"),
        Path("layout_intent.json"), Path("build_receipt.json"),
        Path("preview/content-deck.html"),
        Path("validation/svg_quality_report.json"),
        Path("output/content-deck.pptx"),
        *names,
    ]
    return sorted(paths, key=lambda path: path.as_posix())


def archive(bundle: Path, output: Path) -> None:
    bundle = bundle.resolve()
    output = output.resolve()
    if not bundle.is_dir():
        raise ValueError(f"missing source bundle: {bundle}")
    if output.exists():
        raise ValueError(f"output must be absent: {output}")
    run_verify(bundle)
    files = roster(bundle)
    if any((bundle / path).is_symlink() for path in files):
        raise ValueError("canonical bundle file must not be a symlink")
    if any(not (bundle / path).is_file() for path in files):
        raise ValueError("canonical bundle file is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive_file:
            for relative in files:
                info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive_file.writestr(info, (bundle / relative).read_bytes())
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(f"CONTENT_BUNDLE_ARCHIVED files={len(files)}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("source_bundle", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        archive(args.source_bundle, args.output)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

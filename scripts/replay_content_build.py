#!/usr/bin/env python3
"""Replay a verified content bundle with the same builder identity."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "scripts" / "verify_content_build.py"
BUILD = REPO / "scripts" / "build_content_deck.py"


def run(argv: list[str]) -> None:
    subprocess.run(argv, cwd=REPO, check=True)


def head() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_head(value: object) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise ValueError("source bundle is missing valid ppt-studio HEAD")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("source bundle is missing valid ppt-studio HEAD") from exc
    return value


def identity(receipt: dict) -> tuple:
    inputs = receipt.get("inputs")
    toolchain = receipt.get("toolchain")
    if not isinstance(inputs, dict) or not isinstance(toolchain, dict):
        raise ValueError("replay identity mismatch")
    return (
        receipt.get("slides"),
        inputs.get("markdown_sha256"),
        inputs.get("spec_sha256"),
        inputs.get("slide_plan_sha256"),
        inputs.get("layout_intent_sha256"),
        toolchain.get("ppt_studio_head"),
        toolchain.get("ppt_master_head"),
    )


def replay(source_bundle: Path, toolchain_config: Path, output: Path) -> None:
    source_bundle = source_bundle.resolve()
    toolchain_config = toolchain_config.resolve()
    output = output.resolve()
    if not source_bundle.is_dir():
        raise ValueError(f"missing source bundle: {source_bundle}")
    if not toolchain_config.is_file():
        raise ValueError(f"missing toolchain config: {toolchain_config}")
    if output.exists():
        raise ValueError(f"output must be absent: {output}")
    source = source_bundle / "source.md"
    spec = source_bundle / "spec_lock.md"
    receipt_path = source_bundle / "build_receipt.json"
    if not source.is_file() or not spec.is_file() or not receipt_path.is_file():
        raise ValueError("source bundle must contain source.md, spec_lock.md, and build_receipt.json")

    # Verify before creating any target or invoking the builder.
    run([sys.executable, str(VERIFY), str(source_bundle)])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    toolchain = receipt.get("toolchain")
    expected = require_head(toolchain.get("ppt_studio_head") if isinstance(toolchain, dict) else None)
    actual = head()
    if actual != expected:
        raise ValueError("source bundle builder HEAD does not match current ppt-studio HEAD")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.replay-", dir=output.parent))
    try:
        run([
            sys.executable,
            str(BUILD),
            str(source),
            "--spec", str(spec),
            "--toolchain-config", str(toolchain_config),
            "-o", str(temporary),
        ])
        run([sys.executable, str(VERIFY), str(temporary)])
        new_receipt = json.loads((temporary / "build_receipt.json").read_text(encoding="utf-8"))
        if identity(receipt) != identity(new_receipt):
            raise ValueError("replay identity mismatch")
        os.replace(temporary, output)
    except BaseException:
        if temporary.exists():
            import shutil
            shutil.rmtree(temporary)
        raise
    print(f"CONTENT_BUILD_REPLAYED slides={receipt.get('slides')}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("source_bundle", type=Path)
    parser.add_argument("--toolchain-config", required=True, type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        replay(args.source_bundle, args.toolchain_config, args.output)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

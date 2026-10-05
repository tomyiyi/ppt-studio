#!/usr/bin/env python3
"""Run the PPT test suite as explicit fast/process gates."""

from __future__ import annotations

import argparse
import subprocess
import sys
import os
from pathlib import Path

PROCESS_MODULES = {"tests.test_prepare_agnes_image"}


def discovered_modules(root: Path | str) -> list[str]:
    root_p = Path(root).resolve()
    tests_dir = root_p / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(
        ".".join(path.relative_to(root_p).with_suffix("").parts)
        for path in tests_dir.glob("test_*.py")
    )


def run_gate(name: str, modules: list[str], root: Path | str) -> int:
    if not modules:
        print(f"{name.upper()}_GATE=PASS (no modules)")
        return 0
    root_p = Path(root).resolve()
    runner = os.environ.get("PPT_TEST_PYTHON", sys.executable)
    proc = subprocess.run(
        [runner, "-m", "unittest", *modules, "-q"],
        cwd=root_p,
        text=True,
    )
    print(f"{name.upper()}_GATE_RC={proc.returncode}")
    return proc.returncode


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the PPT test suite as explicit fast/process gates."
    )
    parser.add_argument(
        "mode",
        choices=["fast", "process", "all"],
        help="运行模式 (fast, process, all)",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: PPT_TEST_ROOT 或仓库根目录)",
    )
    args = parser.parse_args(argv)

    root = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (
            Path(base_dir).resolve()
            if base_dir
            else Path(os.environ.get("PPT_TEST_ROOT", Path(__file__).resolve().parent.parent)).resolve()
        )
    )
    modules = discovered_modules(root)
    fast = [module for module in modules if module not in PROCESS_MODULES]
    process = [module for module in modules if module in PROCESS_MODULES]

    if args.mode == "fast":
        return run_gate("fast", fast, root)
    if args.mode == "process":
        return run_gate("process", process, root)

    fast_rc = run_gate("fast", fast, root)
    process_rc = run_gate("process", process, root)
    overall = 0 if fast_rc == 0 and process_rc == 0 else 1
    print(f"OVERALL={'PASS' if overall == 0 else 'FAIL'}")
    return overall


if __name__ == "__main__":
    raise SystemExit(main())

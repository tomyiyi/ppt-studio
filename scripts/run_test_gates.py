#!/usr/bin/env python3
"""Run the PPT test suite as explicit fast/process gates."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

PROCESS_MODULES = {"tests.test_prepare_agnes_image"}


def discovered_modules(root: Path) -> list[str]:
    return sorted(
        ".".join(path.relative_to(root).with_suffix("").parts)
        for path in (root / "tests").glob("test_*.py")
    )


def run_gate(name: str, modules: list[str], root: Path) -> int:
    if not modules:
        print(f"{name.upper()}_GATE=PASS (no modules)")
        return 0
    runner = os.environ.get("PPT_TEST_PYTHON", sys.executable)
    proc = subprocess.run(
        [runner, "-m", "unittest", *modules, "-q"],
        cwd=root,
        text=True,
    )
    print(f"{name.upper()}_GATE_RC={proc.returncode}")
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    mode = (argv or sys.argv[1:])
    if len(mode) != 1 or mode[0] not in {"fast", "process", "all"}:
        print("usage: run_test_gates.py {fast|process|all}", file=sys.stderr)
        return 2

    root = Path(os.environ.get("PPT_TEST_ROOT", Path(__file__).resolve().parent.parent))
    modules = discovered_modules(root)
    fast = [module for module in modules if module not in PROCESS_MODULES]
    process = [module for module in modules if module in PROCESS_MODULES]

    if mode[0] == "fast":
        return run_gate("fast", fast, root)
    if mode[0] == "process":
        return run_gate("process", process, root)

    fast_rc = run_gate("fast", fast, root)
    process_rc = run_gate("process", process, root)
    overall = 0 if fast_rc == 0 and process_rc == 0 else 1
    print(f"OVERALL={'PASS' if overall == 0 else 'FAIL'}")
    return overall


if __name__ == "__main__":
    raise SystemExit(main())

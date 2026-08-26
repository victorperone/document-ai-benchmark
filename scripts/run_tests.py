#!/usr/bin/env python3
"""
Fast regression test runner.

Usage:
    python scripts/run_tests.py

Steps:
    1. Compile scripts/, src/, tests/, parser_tests/ — catches syntax errors.
    2. Run all test_*.py files under tests/ with unittest discover.
    3. Run all test_*.py files under parser_tests/ with unittest discover.

Returns 0 only if all steps pass with zero failures.
"""
from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_discover(start_dir: str) -> int:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            start_dir,
            "-p",
            "test_*.py",
            "-v",
        ],
        cwd=str(ROOT),
    ).returncode


def main() -> int:
    print("=" * 60)
    print("STEP 1 — Compile")
    print("=" * 60)

    compile_ok = all(
        compileall.compile_dir(
            str(ROOT / directory),
            quiet=1,
        )
        for directory in (
            "scripts",
            "src",
            "tests",
            "parser_tests",
        )
    )

    if not compile_ok:
        print("\nCompile FAILED")
        return 1

    print("Compile OK\n")

    print("=" * 60)
    print("STEP 2 — Unit tests (tests/)")
    print("=" * 60)

    rc_tests = _run_discover("tests")

    print()
    print("=" * 60)
    print("STEP 3 — Parser tests (parser_tests/)")
    print("=" * 60)

    rc_parser = _run_discover("parser_tests")

    if rc_tests != 0 or rc_parser != 0:
        print("\nTests FAILED")
        return 1

    print("\nAll tests PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

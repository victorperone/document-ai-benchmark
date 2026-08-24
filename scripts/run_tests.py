#!/usr/bin/env python3
"""
Fast regression test runner.

Usage:
    python scripts/run_tests.py

Steps:
    1. Compile scripts/, src/, tests/, parser_tests/ — catches syntax errors.
    2. Run all test_*.py files under tests/ with unittest discover.

Returns 0 only if both steps pass.
"""
from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
    print("STEP 2 — Tests")
    print("=" * 60)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
            "-v",
        ],
        cwd=str(ROOT),
    )

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Common regression test runner.

Usage:
    python3 scripts/run_tests.py

Steps:
    1. Compile scripts/, src/, tests/, parser_tests/.
    2. Run all test_*.py files under tests/.

Parser-specific tests are intentionally not executed with the
orchestrator Python because each parser has an isolated dependency
environment.

Run parser-specific tests with:

    python3 scripts/run_parser_tests.py <parser>

Example:

    python3 scripts/run_parser_tests.py docling
"""

from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_discover(
    start_dir: str,
) -> int:
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
    print("STEP 1 - Compile")
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
        print()
        print("Compile FAILED")
        return 1

    print("Compile OK")
    print()

    print("=" * 60)
    print("STEP 2 - Common unit tests (tests/)")
    print("=" * 60)

    rc_tests = _run_discover(
        "tests"
    )

    if rc_tests != 0:
        print()
        print("Tests FAILED")
        return 1

    print()
    print("Common tests PASSED")
    print(
        "Parser-specific tests must run in "
        "their parser environment."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
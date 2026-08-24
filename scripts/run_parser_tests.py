#!/usr/bin/env python3
"""
Run parser-specific tests inside the parser Docker service.

Usage:
    python3 scripts/run_parser_tests.py docling

Parser-specific tests live under:

    parser_tests/<parser>/

The parser test directory is mounted read-only into the container only
for the duration of the test run.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARSER_TEST_ROOT = ROOT / "parser_tests"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run parser-specific tests inside "
            "the parser Docker service."
        )
    )
    parser.add_argument(
        "parser",
        help=(
            "Parser/service name, for example "
            "'docling'."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    parser_name = args.parser
    test_directory = PARSER_TEST_ROOT / parser_name

    if not test_directory.is_dir():
        print(
            "Parser test directory does not exist: "
            f"{test_directory}"
        )
        return 2

    command = [
        "docker",
        "compose",
        "run",
        "--rm",
        "--volume",
        (
            f"{PARSER_TEST_ROOT.resolve()}:"
            "/app/parser_tests:ro"
        ),
        "--entrypoint",
        "python",
        parser_name,
        "-m",
        "unittest",
        "discover",
        "-s",
        f"parser_tests/{parser_name}",
        "-t",
        ".",
        "-p",
        "test_*.py",
        "-v",
    ]

    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        check=False,
    )

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

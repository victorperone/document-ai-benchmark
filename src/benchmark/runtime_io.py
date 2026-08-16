from __future__ import annotations

import argparse
import contextlib
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

from src.benchmark.artifact_policy import (
    ALL_ARTIFACTS,
)


def add_runtime_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """
    Add runtime-only CLI arguments shared by parser adapters.

    These options must not alter parsing quality.
    """

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Show parser progress and parser messages "
            "in the terminal. Parsing/output content "
            "must remain identical."
        ),
    )

    parser.add_argument(
        "--artifacts",
        nargs="+",
        default=None,
        metavar="ARTIFACT",
        help=(
            "Artifacts to persist. "
            "Default: document.md run.log. "
            "Use 'all' for every artifact. "
            "Valid explicit names: "
            + ", ".join(
                ALL_ARTIFACTS
            )
            + ". Comma-separated values are "
            "also accepted."
        ),
    )


class _TeeStream:
    """
    Write to the terminal and a secondary stream.

    This allows verbose parser/progress output to remain visible
    while simultaneously preserving it in run.log.
    """

    def __init__(
        self,
        primary: TextIO,
        secondary: TextIO,
    ) -> None:
        self.primary = primary
        self.secondary = secondary

    def write(
        self,
        data: str,
    ) -> int:
        primary_result = (
            self.primary.write(
                data
            )
        )

        self.secondary.write(
            data
        )

        return (
            primary_result
            if isinstance(
                primary_result,
                int,
            )
            else len(data)
        )

    def flush(
        self,
    ) -> None:
        self.primary.flush()
        self.secondary.flush()

    def isatty(
        self,
    ) -> bool:
        try:
            return bool(
                self.primary.isatty()
            )
        except Exception:
            return False

    @property
    def encoding(
        self,
    ) -> str | None:
        return getattr(
            self.primary,
            "encoding",
            None,
        )


@contextlib.contextmanager
def parser_output_context(
    *,
    run_log_path: Path,
    keep_run_log: bool,
    verbose: bool,
):
    """
    Route parser stdout/stderr according to runtime policy.

    keep_run_log=True, verbose=False:
        parser output -> run.log

    keep_run_log=True, verbose=True:
        parser output -> terminal + run.log

    keep_run_log=False, verbose=True:
        parser output -> terminal

    keep_run_log=False, verbose=False:
        parser output -> /dev/null
    """

    with ExitStack() as stack:
        log_file: TextIO | None = None

        if keep_run_log:
            run_log_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            log_file = stack.enter_context(
                run_log_path.open(
                    "w",
                    encoding="utf-8",
                )
            )

        if verbose:
            if log_file is None:
                stdout_target = (
                    sys.stdout
                )
                stderr_target = (
                    sys.stderr
                )

            else:
                stdout_target = (
                    _TeeStream(
                        sys.stdout,
                        log_file,
                    )
                )

                stderr_target = (
                    _TeeStream(
                        sys.stderr,
                        log_file,
                    )
                )

        else:
            if log_file is not None:
                stdout_target = (
                    log_file
                )
                stderr_target = (
                    log_file
                )

            else:
                devnull = (
                    stack.enter_context(
                        open(
                            os.devnull,
                            "w",
                            encoding="utf-8",
                        )
                    )
                )

                stdout_target = (
                    devnull
                )
                stderr_target = (
                    devnull
                )

        stack.enter_context(
            contextlib.redirect_stdout(
                stdout_target
            )
        )

        stack.enter_context(
            contextlib.redirect_stderr(
                stderr_target
            )
        )

        yield

"""Shared native-Windows functional smoke used by each isolated parser suite."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.parser_deep_smoke import (
    FIXTURE_ROOT,
    ROOT,
    validate_job,
    verify_fixture,
    verify_model,
)
from src.benchmark.process_tree import run_process_tree


FUNCTIONAL_ENV = "BENCHMARK_WINDOWS_FUNCTIONAL"


def make_functional_test_case(
    parser: str,
    profile: str,
) -> type[unittest.TestCase]:
    enabled = os.environ.get(FUNCTIONAL_ENV) == "1"

    @unittest.skipUnless(
        enabled,
        f"set {FUNCTIONAL_ENV}=1 only in the native Windows readiness gate",
    )
    class FunctionalDeepSmokeTest(unittest.TestCase):
        def test_real_offline_inference(self) -> None:
            self.assertEqual(
                os.name,
                "nt",
                "functional parser smoke is valid only on native Windows",
            )
            verify_fixture()
            verify_model(parser)

            environment = os.environ.copy()
            environment.update(
                {
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                    "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                    "DO_NOT_TRACK": "1",
                }
            )
            timeout = int(
                environment.get("BENCHMARK_FUNCTIONAL_TIMEOUT_SECONDS", "3600")
            )
            self.assertGreater(timeout, 0)

            with TemporaryDirectory(prefix=f"document-ai-{parser}-") as temporary:
                output_root = Path(temporary)
                command = [
                    sys.executable,
                    str(ROOT / "scripts" / "run_batch.py"),
                    "--parser",
                    parser,
                    "--profile",
                    profile,
                    "--runtime",
                    "host",
                    "--input-dir",
                    str(FIXTURE_ROOT),
                    "--output-root",
                    str(output_root),
                    "--artifacts",
                    "all",
                    "--force",
                    "--no-summary",
                    "--job-timeout-seconds",
                    str(timeout),
                ]
                result = run_process_tree(
                    command,
                    cwd=ROOT,
                    env=environment,
                    timeout=timeout + 360,
                    capture_output=True,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    (result.stderr or result.stdout or "no subprocess output")[-4000:],
                )
                validate_job(parser, profile, output_root)

            verify_model(parser)

    FunctionalDeepSmokeTest.__name__ = (
        parser.title().replace("_", "") + "FunctionalDeepSmokeTests"
    )
    FunctionalDeepSmokeTest.__qualname__ = FunctionalDeepSmokeTest.__name__
    return FunctionalDeepSmokeTest

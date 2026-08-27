"""Tests for mineru_v2 CLI command contract (run_mineru_native)."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock, patch

from src.parsers.mineru_v2 import run_mineru_native

PARSER_NAME = "mineru"


def _run_native_dry(
    method: str = "auto",
    backend: str = "pipeline",
    threads: int | None = None,
    verbose: bool = False,
) -> list[str]:
    """Run run_mineru_native with a fake subprocess and return the command array."""
    captured_commands: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        captured_commands.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        input_path = Path(f.name)

    try:
        with patch("subprocess.run", side_effect=_fake_run):
            try:
                run_mineru_native(
                    input_path=input_path,
                    method=method,
                    backend=backend,
                    threads=threads,
                    verbose=verbose,
                )
            except (FileNotFoundError, RuntimeError, TypeError):
                # subprocess succeeded (command captured) but no real output
                # files exist in the temp dir — expected in dry-run mode.
                pass
    finally:
        input_path.unlink(missing_ok=True)

    return captured_commands[0] if captured_commands else []


class TestCliCommandStructure(unittest.TestCase):
    def test_command_starts_with_mineru(self):
        cmd = _run_native_dry()
        self.assertEqual(cmd[0], "mineru")

    def test_command_has_backend_flag(self):
        cmd = _run_native_dry(backend="pipeline")
        self.assertIn("-b", cmd)
        idx = cmd.index("-b")
        self.assertEqual(cmd[idx + 1], "pipeline")

    def test_command_has_method_flag(self):
        cmd = _run_native_dry(method="auto")
        self.assertIn("-m", cmd)
        idx = cmd.index("-m")
        self.assertEqual(cmd[idx + 1], "auto")

    def test_command_has_input_flag(self):
        cmd = _run_native_dry()
        self.assertIn("-p", cmd)

    def test_command_has_output_flag(self):
        cmd = _run_native_dry()
        self.assertIn("-o", cmd)


class TestCliBackendPropagation(unittest.TestCase):
    def test_pipeline_backend_propagated(self):
        cmd = _run_native_dry(backend="pipeline")
        idx = cmd.index("-b")
        self.assertEqual(cmd[idx + 1], "pipeline")

    def test_ocr_method_propagated(self):
        cmd = _run_native_dry(method="ocr")
        idx = cmd.index("-m")
        self.assertEqual(cmd[idx + 1], "ocr")

    def test_txt_method_propagated(self):
        cmd = _run_native_dry(method="txt")
        idx = cmd.index("-m")
        self.assertEqual(cmd[idx + 1], "txt")


class TestInvalidMethodRejected(unittest.TestCase):
    def test_invalid_method_raises(self):
        with NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            input_path = Path(f.name)
        try:
            with self.assertRaises((ValueError, SystemExit)):
                run_mineru_native(
                    input_path=input_path,
                    method="invalid_method",
                    backend="pipeline",
                    threads=None,
                    verbose=False,
                )
        finally:
            input_path.unlink(missing_ok=True)

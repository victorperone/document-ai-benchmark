"""
Unit tests for run_batch.run_parser_preflight() and the
parser_preflight_ready guard inside run_batch.run_preflight().

subprocess.run is mocked — no Docker, no models, no inference.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._support import load_run_batch_module

_run_batch = load_run_batch_module()

_COMPOSE_BASE = ["docker", "compose"]
_PARSER = "pymupdf"
_PROFILE = "native"


def _completed(
    *,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _preflight_line(
    *,
    ok: bool,
    parser: str = _PARSER,
    profile: str = _PROFILE,
    checks: list | None = None,
) -> str:
    if checks is None:
        if ok:
            checks = [{"name": "adapter", "status": "pass"}]
        else:
            checks = [{"name": "model PP-FormulaNet_plus-L", "status": "fail", "detail": "missing"}]
    payload = json.dumps({
        "schema_version": 1,
        "parser": parser,
        "profile": profile,
        "ok": ok,
        "checks": checks,
    })
    return f"PREFLIGHT_JSON={payload}"


def _call_preflight(mock_result: subprocess.CompletedProcess) -> dict:
    with patch.object(_run_batch.subprocess, "run", return_value=mock_result):
        return _run_batch.run_parser_preflight(_COMPOSE_BASE, _PARSER, _PROFILE)


def _is_protocol_error(result: dict) -> bool:
    checks = result.get("checks", [])
    return (
        not result.get("ok", True)
        and any(c.get("name") == "parser preflight protocol" for c in checks)
    )


class TestRunParserPreflightPass(unittest.TestCase):

    def test_valid_pass_result_ok_true(self) -> None:
        """Valid PASS JSON with returncode 0 is accepted as-is."""
        stdout = f"some startup text\n{_preflight_line(ok=True)}"
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertTrue(result["ok"])

    def test_valid_pass_original_checks_preserved(self) -> None:
        """Original checks survive; no 'parser preflight protocol' injected."""
        stdout = _preflight_line(ok=True)
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        names = [c["name"] for c in result["checks"]]
        self.assertIn("adapter", names)
        self.assertNotIn("parser preflight protocol", names)

    def test_valid_fail_result_ok_false(self) -> None:
        """Valid FAIL JSON with returncode 1 is accepted; ok is False."""
        stdout = _preflight_line(ok=False)
        result = _call_preflight(_completed(returncode=1, stdout=stdout))
        self.assertFalse(result["ok"])

    def test_valid_fail_model_check_preserved(self) -> None:
        """The original fail check (e.g. missing model) is kept intact."""
        stdout = _preflight_line(ok=False)
        result = _call_preflight(_completed(returncode=1, stdout=stdout))
        names = [c["name"] for c in result["checks"]]
        self.assertIn("model PP-FormulaNet_plus-L", names)
        self.assertNotIn("parser preflight protocol", names)


class TestRunParserPreflightMissingProtocol(unittest.TestCase):

    def test_no_protocol_line_is_error(self) -> None:
        """stdout without PREFLIGHT_JSON= → protocol error result."""
        stdout = "some parser output\nno protocol line here"
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))

    def test_invalid_json_is_error(self) -> None:
        """PREFLIGHT_JSON={not-json → protocol error result."""
        stdout = "PREFLIGHT_JSON={not-json"
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))

    def test_empty_stdout_is_error(self) -> None:
        """Empty stdout → protocol error result."""
        result = _call_preflight(_completed(returncode=0, stdout=""))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))


class TestRunParserPreflightMismatch(unittest.TestCase):

    def test_parser_mismatch_is_error(self) -> None:
        """JSON parser='docling' when 'pymupdf' was requested → protocol error."""
        stdout = _preflight_line(ok=True, parser="docling", profile=_PROFILE)
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))

    def test_profile_mismatch_is_error(self) -> None:
        """JSON profile='ocr_auto_rapidtess' when 'native' requested → protocol error."""
        stdout = _preflight_line(ok=True, parser=_PARSER, profile="ocr_auto_rapidtess")
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))

    def test_invalid_schema_version_is_error(self) -> None:
        """schema_version=999 → validate_result() rejects → protocol error."""
        payload = json.dumps({
            "schema_version": 999,
            "parser": _PARSER,
            "profile": _PROFILE,
            "ok": True,
            "checks": [],
        })
        stdout = f"PREFLIGHT_JSON={payload}"
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))


class TestRunParserPreflightExitCodeCoherence(unittest.TestCase):

    def test_ok_true_with_exit_1_is_error(self) -> None:
        """JSON ok=true but process exits 1 → protocol error (exit code mismatch)."""
        stdout = _preflight_line(ok=True)
        result = _call_preflight(_completed(returncode=1, stdout=stdout))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))

    def test_ok_false_with_exit_0_is_error(self) -> None:
        """JSON ok=false but process exits 0 → protocol error (exit code mismatch)."""
        stdout = _preflight_line(ok=False)
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))

    def test_ok_inconsistent_with_checks_is_error(self) -> None:
        """ok=true with a fail check → validate_result() raises → protocol error."""
        payload = json.dumps({
            "schema_version": 1,
            "parser": _PARSER,
            "profile": _PROFILE,
            "ok": True,
            "checks": [{"name": "forced failure", "status": "fail"}],
        })
        stdout = f"PREFLIGHT_JSON={payload}"
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertFalse(result["ok"])
        self.assertTrue(_is_protocol_error(result))


class TestRunParserPreflightProtocolLines(unittest.TestCase):

    def test_last_preflight_json_line_is_used(self) -> None:
        """When multiple PREFLIGHT_JSON= lines appear, the last one is used."""
        old_line = _preflight_line(ok=False)
        final_line = _preflight_line(ok=True)
        stdout = f"warning line\n{old_line}\nmore text\n{final_line}"
        result = _call_preflight(_completed(returncode=0, stdout=stdout))
        self.assertTrue(result["ok"])


class TestRunPreflightComposeFail(unittest.TestCase):
    """run_preflight() must skip run_parser_preflight when compose config fails."""

    def test_compose_fail_skips_parser_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp)
            output_root = Path(tmp) / "outputs"
            docs = [Path(tmp) / "dummy.pdf"]
            jobs_spec = [(_PARSER, _PROFILE)]

            docker_ok = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="24.0.7", stderr=""
            )
            compose_fail = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="compose config error"
            )

            with patch.object(_run_batch.shutil, "which", return_value="/usr/bin/docker"), \
                 patch.object(
                     _run_batch.subprocess, "run",
                     side_effect=[docker_ok, compose_fail],
                 ), \
                 patch.object(
                     _run_batch, "run_parser_preflight",
                 ) as mock_parser_preflight:
                ok = _run_batch.run_preflight(
                    jobs_spec,
                    docs,
                    input_dir,
                    output_root,
                    _COMPOSE_BASE,
                    None,
                )

            self.assertFalse(ok)
            mock_parser_preflight.assert_not_called()


if __name__ == "__main__":
    unittest.main()

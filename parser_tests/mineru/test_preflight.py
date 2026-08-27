"""Tests for mineru_v2.preflight_profile (preflight contract)."""
from __future__ import annotations

import importlib.metadata
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from src.parsers import mineru_v2

PARSER_NAME = "mineru"


class _PreflightHelper(unittest.TestCase):
    """Base with a helper to run preflight under controlled mock conditions."""

    def _run_preflight(
        self,
        profile_name: str,
        *,
        mineru_on_path: bool = True,
        mineru_pkg_present: bool = True,
        torch_present: bool = True,
        model_source: str | None = "local",
        config_json_present: bool = True,
        pipeline_dir_exists: bool = True,
        hf_home: str | None = None,
    ) -> dict:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            pipeline_dir = tmp_path / "pipeline_models"
            if pipeline_dir_exists:
                pipeline_dir.mkdir()

            config_path = tmp_path / "mineru.json"
            if config_json_present:
                config_data = {
                    "models-dir": {
                        "auto": str(pipeline_dir),
                    }
                }
                config_path.write_text(json.dumps(config_data), encoding="utf-8")

            env_overrides: dict[str, str] = {}
            if model_source is not None:
                env_overrides["MINERU_MODEL_SOURCE"] = model_source
            if config_json_present:
                env_overrides["MINERU_TOOLS_CONFIG_JSON"] = str(config_path)
            if hf_home is not None:
                env_overrides["HF_HOME"] = hf_home

            def _fake_meta_version(name: str) -> str:
                if name == "mineru":
                    if not mineru_pkg_present:
                        raise importlib.metadata.PackageNotFoundError(name)
                    return "3.4.4"
                if name == "torch":
                    if not torch_present:
                        raise importlib.metadata.PackageNotFoundError(name)
                    return "2.4.0"
                raise importlib.metadata.PackageNotFoundError(name)

            fake_metadata = MagicMock()
            fake_metadata.version = _fake_meta_version
            fake_metadata.PackageNotFoundError = importlib.metadata.PackageNotFoundError

            fake_shutil = MagicMock()
            fake_shutil.which = lambda _: "mineru" if mineru_on_path else None

            base_env = {k: v for k, v in os.environ.items() if k not in {
                "MINERU_MODEL_SOURCE", "MINERU_TOOLS_CONFIG_JSON", "HF_HOME"
            }}
            base_env.update(env_overrides)

            with (
                patch.object(mineru_v2, "shutil", fake_shutil),
                patch.object(mineru_v2, "metadata", fake_metadata),
                patch.dict(os.environ, base_env, clear=True),
            ):
                return mineru_v2.preflight_profile(profile_name)

    def _find_check(self, result: dict, name: str) -> dict | None:
        matches = [c for c in result.get("checks", []) if c.get("name") == name]
        return matches[0] if matches else None


class TestPreflightCliCheck(_PreflightHelper):
    def test_mineru_on_path_passes(self):
        result = self._run_preflight("auto")
        cli_check = self._find_check(result, "mineru CLI")
        self.assertIsNotNone(cli_check)
        self.assertEqual(cli_check["status"], "pass")

    def test_mineru_absent_fails(self):
        result = self._run_preflight("auto", mineru_on_path=False)
        self.assertFalse(result["ok"])

    def test_result_has_ok_and_checks(self):
        result = self._run_preflight("auto")
        self.assertIn("ok", result)
        self.assertIn("checks", result)
        self.assertIsInstance(result["checks"], list)


class TestPreflightModelSource(_PreflightHelper):
    def test_model_source_local_passes(self):
        result = self._run_preflight("auto", model_source="local")
        check = self._find_check(result, "MINERU_MODEL_SOURCE")
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_model_source_not_local_fails(self):
        result = self._run_preflight("auto", model_source="huggingface")
        self.assertFalse(result["ok"])

    def test_model_source_unset_fails(self):
        result = self._run_preflight("auto", model_source=None, config_json_present=False)
        self.assertFalse(result["ok"])


class TestPreflightConfigJson(_PreflightHelper):
    def test_config_absent_fails(self):
        result = self._run_preflight("auto", config_json_present=False)
        self.assertFalse(result["ok"])

    def test_config_present_with_pipeline_dir_passes(self):
        result = self._run_preflight("auto")
        check = self._find_check(result, "MINERU_TOOLS_CONFIG_JSON")
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_pipeline_dir_missing_fails(self):
        result = self._run_preflight("auto", pipeline_dir_exists=False)
        self.assertFalse(result["ok"])


class TestPreflightFullCpuLocal(_PreflightHelper):
    def test_full_cpu_local_passes(self):
        result = self._run_preflight("full_cpu_local")
        self.assertTrue(result["ok"], result)

    def test_full_cpu_local_cli_absent_fails(self):
        result = self._run_preflight("full_cpu_local", mineru_on_path=False)
        self.assertFalse(result["ok"])

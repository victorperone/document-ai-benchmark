"""Tests for Windows setup scripts structure (section 43.3)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts" / "windows"

EXPECTED_SETUP_SCRIPTS = [
    "setup_unstructured.ps1",
    "setup_xberg.ps1",
]

EXPECTED_PREPARATION_SCRIPTS = [
    "prepare_unstructured_models.ps1",
    "prepare_docling_models.ps1",
]

EXPECTED_SUPPORT_SCRIPTS = [
    "_helpers.ps1",
    "check_envs.ps1",
    "setup_envs.ps1",
    "run_host_parser_tests.ps1",
]


class TestSetupScriptsExist(unittest.TestCase):
    def test_all_setup_scripts_exist(self):
        for name in EXPECTED_SETUP_SCRIPTS:
            with self.subTest(script=name):
                path = SCRIPTS_DIR / name
                self.assertTrue(path.exists(), f"Missing: {path}")

    def test_preparation_scripts_exist(self):
        for name in EXPECTED_PREPARATION_SCRIPTS:
            with self.subTest(script=name):
                path = SCRIPTS_DIR / name
                self.assertTrue(path.exists(), f"Missing: {path}")

    def test_support_scripts_exist(self):
        for name in EXPECTED_SUPPORT_SCRIPTS:
            with self.subTest(script=name):
                path = SCRIPTS_DIR / name
                self.assertTrue(path.exists(), f"Missing: {path}")


class TestSetupUnstructuredStructure(unittest.TestCase):
    """
    Structural checks for the installation script.

    Runtime offline and telemetry environment variables are intentionally
    defined and tested through runtime_specs, not through this setup script.
    """
    @classmethod
    def setUpClass(cls):
        path = SCRIPTS_DIR / "setup_unstructured.ps1"
        cls.available = path.exists()
        cls.text = path.read_text(encoding="utf-8") if cls.available else ""

    def test_checks_windows_long_paths(self):
        self.assertIn("Assert-WindowsLongPathsEnabled", self.text)

    def setUp(self):
        if not self.available:
            self.skipTest("setup_unstructured.ps1 not found")

    def test_creates_venv(self):
        self.assertIn(".venvs", self.text)

    def test_references_requirements_file(self):
        self.assertIn("unstructured.txt", self.text)

    def test_has_smoke_test(self):
        self.assertIn("import unstructured", self.text.replace("'", '"'))



class TestSetupXbergStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = SCRIPTS_DIR / "setup_xberg.ps1"
        cls.available = path.exists()
        cls.text = path.read_text(encoding="utf-8") if cls.available else ""

    def setUp(self):
        if not self.available:
            self.skipTest("setup_xberg.ps1 not found")

    def test_creates_venv(self):
        self.assertIn(".venvs", self.text)

    def test_references_requirements_file(self):
        self.assertIn("xberg.txt", self.text)

    def test_has_smoke_test(self):
        self.assertIn("xberg", self.text.lower())

    def test_smoke_test_tests_native_module(self):
        self.assertTrue(
            "xberg._xberg" in self.text or "xberg.extract" in self.text,
            "Smoke test does not verify native module",
        )


class TestCheckEnvsStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = SCRIPTS_DIR / "check_envs.ps1"
        cls.available = path.exists()
        cls.text = path.read_text(encoding="utf-8") if cls.available else ""

    def setUp(self):
        if not self.available:
            self.skipTest("check_envs.ps1 not found")

    def test_includes_unstructured(self):
        self.assertIn("unstructured", self.text.lower())

    def test_includes_xberg(self):
        self.assertIn("xberg", self.text.lower())

    def test_references_core(self):
        self.assertIn("core", self.text.lower())


class TestHelpersPs1Structure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = SCRIPTS_DIR / "_helpers.ps1"
        cls.available = path.exists()
        cls.text = path.read_text(encoding="utf-8") if cls.available else ""

    def setUp(self):
        if not self.available:
            self.skipTest("_helpers.ps1 not found")

    def test_has_invoke_native_checked(self):
        self.assertIn("Invoke-NativeChecked", self.text)

    def test_has_long_path_check(self):
        self.assertIn("Assert-WindowsLongPathsEnabled", self.text)
        self.assertIn("LongPathsEnabled", self.text)
        self.assertIn(
            r"HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem",
            self.text,
        )


class TestInvokePythonScriptChecked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (SCRIPTS_DIR / "_helpers.ps1").read_text(encoding="utf-8")

    def test_helper_exists(self):
        self.assertIn("function Invoke-PythonScriptChecked", self.text)

    def test_helper_writes_utf8_without_bom(self):
        self.assertIn("System.Text.UTF8Encoding($false)", self.text)

    def test_helper_uses_finally(self):
        self.assertIn("finally", self.text)
        self.assertIn("Remove-Item", self.text)

    def test_helper_delegates_native_exit_check(self):
        self.assertIn("Invoke-NativeChecked", self.text)


class TestUnstructuredSetupHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (
            SCRIPTS_DIR / "setup_unstructured.ps1"
        ).read_text(encoding="utf-8")

    def _position(self, token: str) -> int:
        position = self.text.find(token)
        self.assertGreaterEqual(position, 0, f"Missing token: {token!r}")
        return position

    def test_has_required_header(self):
        self.assertTrue(
            self.text.startswith("#Requires -Version 5.1"),
            "Script must begin with #Requires -Version 5.1",
        )
        self.assertIn("Set-StrictMode -Version Latest", self.text)
        self.assertIn("$ErrorActionPreference = 'Stop'", self.text)

    def test_definitions_precede_use(self):
        self.assertLess(
            self._position("$VenvPath ="),
            self._position("Test-Path $VenvPath"),
        )
        self.assertLess(
            self._position("$ReqFile ="),
            self._position("Test-Path $ReqFile"),
        )
        self.assertLess(
            self._position('. "$PSScriptRoot\\_helpers.ps1"'),
            self._position("Assert-WindowsLongPathsEnabled"),
        )

    def test_install_check_smoke_order(self):
        install = self._position("'-m', 'pip', 'install'")
        pip_check = self._position("'-m', 'pip', 'check'")
        smoke = self._position("$Smoke = @'")
        invoke = self._position("Invoke-PythonScriptChecked")

        self.assertLess(install, pip_check)
        self.assertLess(pip_check, smoke)
        self.assertLess(smoke, invoke)

    def test_multiline_smoke_is_not_passed_to_c(self):
        self.assertNotRegex(
            self.text,
            re.compile(
                r"@\(\s*['\"]+-c['\"]+"
                r"\s*,\s*\$[Ss]moke",
                re.IGNORECASE,
            ),
        )


class TestUnstructuredModelPreparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (
            SCRIPTS_DIR / "prepare_unstructured_models.ps1"
        ).read_text(encoding="utf-8")

    def test_all_resources_are_present(self):
        for token in (
            "en_core_web_sm",
            'get_model("yolox")',
            "table-transformer-structure-recognition",
            "load_agent",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_acquisition_precedes_offline_validation(self):
        acquisition = self.text.find("PHASE 1")
        offline = self.text.find("PHASE 2")
        manifest = self.text.find("PHASE 3")

        self.assertGreaterEqual(acquisition, 0, "PHASE 1 marker missing")
        self.assertLess(acquisition, offline, "PHASE 1 must precede PHASE 2")
        self.assertLess(offline, manifest, "PHASE 2 must precede PHASE 3")

    def test_offline_variables_exist(self):
        self.assertIn("HF_HUB_OFFLINE", self.text)
        self.assertIn("TRANSFORMERS_OFFLINE", self.text)

    def test_offline_socket_guard_exists(self):
        self.assertIn(
            "Network access attempted during offline validation",
            self.text,
        )
        self.assertIn("socket.create_connection", self.text)

    def test_manifest_is_certified(self):
        for token in (
            "offline_validation",
            "schema_version",
            "sha256",
            "unstructured_models_manifest.json",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_force_is_not_dead_parameter(self):
        self.assertRegex(
            self.text,
            re.compile(r"if\s*\(\$Force\)", re.IGNORECASE),
        )


class TestDoclingModelPreparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (
            SCRIPTS_DIR / "prepare_docling_models.ps1"
        ).read_text(encoding="utf-8")

    def _position(self, token: str) -> int:
        position = self.text.find(token)
        self.assertGreaterEqual(position, 0, f"Missing token: {token!r}")
        return position

    def test_has_required_header(self):
        self.assertTrue(
            self.text.startswith("#Requires -Version 5.1"),
            "Script must begin with #Requires -Version 5.1",
        )
        self.assertIn("Set-StrictMode -Version Latest", self.text)
        self.assertIn("$ErrorActionPreference = 'Stop'", self.text)

    def test_acquisition_precedes_offline_validation(self):
        p1 = self.text.find("PHASE 1")
        p2 = self.text.find("PHASE 2")
        p3 = self.text.find("PHASE 3")
        self.assertGreaterEqual(p1, 0, "PHASE 1 marker missing")
        self.assertLess(p1, p2, "PHASE 1 must precede PHASE 2")
        self.assertLess(p2, p3, "PHASE 2 must precede PHASE 3")

    def test_offline_variables_exist(self):
        self.assertIn("HF_HUB_OFFLINE", self.text)
        self.assertIn("TRANSFORMERS_OFFLINE", self.text)

    def test_offline_validation_delegates_to_python_helper(self):
        self.assertIn("validate_docling_models.py", self.text)
        self.assertIn("Invoke-NativeChecked", self.text)

    def test_hf_env_is_docling_specific(self):
        self.assertIn("HF_HOME", self.text)
        self.assertIn("HF_HUB_CACHE", self.text)
        self.assertIn("HF_XET_CACHE", self.text)
        self.assertIn(r"models\docling\huggingface", self.text)

    def test_env_isolation_with_finally(self):
        self.assertIn("OriginalEnvironment", self.text)
        self.assertIn("finally", self.text)

    def test_force_parameter_is_used(self):
        self.assertRegex(
            self.text,
            re.compile(r"if\s*\(\$Force\b", re.IGNORECASE),
        )

    def test_validate_only_skips_acquisition(self):
        self.assertIn("ValidateOnly", self.text)
        self.assertIn("if (-not $ValidateOnly)", self.text)

    def test_manifest_checked_after_generation(self):
        self.assertIn("docling_models_manifest.json", self.text)
        self.assertIn("Test-Path $ManifestPath", self.text)

    def test_download_api_uses_torch_pt(self):
        self.assertIn('rapidocr_models=["torch:pt"]', self.text)

    def test_download_force_false_by_default(self):
        self.assertIn("force=False", self.text)

    def test_uses_invoke_python_script_checked(self):
        self.assertIn("Invoke-PythonScriptChecked", self.text)

    def test_docling_version_checked(self):
        self.assertIn("2.122.0", self.text)
        self.assertIn("importlib.metadata", self.text)

    def test_disk_space_reported(self):
        self.assertIn("Get-PSDrive", self.text)

    def test_telemetry_disabled(self):
        self.assertIn("HF_HUB_DISABLE_TELEMETRY", self.text)
        self.assertIn("DO_NOT_TRACK", self.text)
        self.assertIn("SCARF_NO_ANALYTICS", self.text)

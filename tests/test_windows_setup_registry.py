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

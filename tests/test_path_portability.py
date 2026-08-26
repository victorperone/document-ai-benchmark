"""
Tests for src.benchmark.execution_paths path resolution.

All platform-specific behaviour is verified via sys.platform mocking —
no real venv or Windows filesystem required.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.execution_paths import (
    RUNTIME_DOCKER,
    RUNTIME_HOST,
    project_root,
    resolve_data_root,
    resolve_model_root,
    resolve_output_root,
    resolve_venv_bin_dir,
    resolve_venv_python,
)


class TestProjectRoot(unittest.TestCase):

    def test_returns_path(self):
        self.assertIsInstance(project_root(), Path)

    def test_is_absolute(self):
        self.assertTrue(project_root().is_absolute())


class TestResolveOutputRoot(unittest.TestCase):

    def test_docker_returns_container_path(self):
        self.assertEqual(resolve_output_root(RUNTIME_DOCKER), Path("/outputs"))

    def test_host_returns_project_outputs(self):
        result = resolve_output_root(RUNTIME_HOST)
        self.assertEqual(result, project_root() / "outputs" / "host")

    def test_invalid_runtime_raises(self):
        with self.assertRaises(ValueError):
            resolve_output_root("invalid")


class TestResolveDataRoot(unittest.TestCase):

    def test_docker_returns_container_path(self):
        self.assertEqual(resolve_data_root(RUNTIME_DOCKER), Path("/data"))

    def test_host_returns_project_data(self):
        self.assertEqual(resolve_data_root(RUNTIME_HOST), project_root() / "data")

    def test_invalid_runtime_raises(self):
        with self.assertRaises(ValueError):
            resolve_data_root("native")


class TestResolveModelRoot(unittest.TestCase):

    def test_docker_docling_returns_container_path(self):
        result = resolve_model_root(RUNTIME_DOCKER, "docling")
        self.assertEqual(result, Path("/home/appuser/.cache/docling/models"))

    def test_docker_paddleocr_returns_container_path(self):
        result = resolve_model_root(RUNTIME_DOCKER, "paddleocr")
        self.assertEqual(result, Path("/home/appuser/.paddlex/official_models"))

    def test_docker_liteparse_returns_container_path(self):
        result = resolve_model_root(RUNTIME_DOCKER, "liteparse")
        self.assertEqual(result, Path("/models/liteparse/smolvlm"))

    def test_host_uses_project_model_path(self):
        result = resolve_model_root(RUNTIME_HOST, "docling")
        self.assertEqual(result, project_root() / "models" / "docling" / "docling" / "models")

    def test_host_pymupdf_returns_project_path(self):
        result = resolve_model_root(RUNTIME_HOST, "pymupdf")
        self.assertEqual(result, project_root() / "models" / "pymupdf")

    def test_host_path_does_not_start_with_container_prefix(self):
        result = resolve_model_root(RUNTIME_HOST, "mineru")
        # On WSL the path is absolute under /, but it must be project-relative
        self.assertTrue(str(result).startswith(str(project_root())))

    def test_docker_unknown_parser_raises(self):
        with self.assertRaises(ValueError):
            resolve_model_root(RUNTIME_DOCKER, "unknown_parser")

    def test_invalid_runtime_raises(self):
        with self.assertRaises(ValueError):
            resolve_model_root("native", "docling")


class TestResolveVenvPythonLinux(unittest.TestCase):

    def test_linux_uses_bin_python(self):
        with patch.object(sys, "platform", "linux"):
            py = resolve_venv_python("pymupdf")
        self.assertIn("bin", py.parts)
        self.assertEqual(py.name, "python")

    def test_linux_no_exe_suffix(self):
        with patch.object(sys, "platform", "linux"):
            py = resolve_venv_python("docling")
        self.assertFalse(str(py).endswith(".exe"))

    def test_linux_bin_dir_is_bin(self):
        with patch.object(sys, "platform", "linux"):
            bd = resolve_venv_bin_dir("pymupdf")
        self.assertEqual(bd.name, "bin")


class TestResolveVenvPythonWindows(unittest.TestCase):

    def test_windows_uses_scripts(self):
        with patch.object(sys, "platform", "win32"):
            py = resolve_venv_python("pymupdf")
        self.assertIn("Scripts", py.parts)

    def test_windows_has_exe_suffix(self):
        with patch.object(sys, "platform", "win32"):
            py = resolve_venv_python("docling")
        self.assertTrue(str(py).endswith("python.exe"))

    def test_windows_liteparse_uses_standard_venv_python(self):
        with patch.object(sys, "platform", "win32"):
            py = resolve_venv_python("liteparse")

        self.assertEqual(py.name, "python.exe")
        self.assertIn("Scripts", py.parts)
        self.assertNotEqual(py.name, "python3.11.exe")

    def test_windows_bin_dir_is_scripts(self):
        with patch.object(sys, "platform", "win32"):
            bd = resolve_venv_bin_dir("pymupdf")
        self.assertEqual(bd.name, "Scripts")


class TestResolveVenvPythonUnderProjectRoot(unittest.TestCase):

    def test_venv_python_is_under_project_root(self):
        with patch.object(sys, "platform", "linux"):
            py = resolve_venv_python("docling")
        self.assertTrue(str(py).startswith(str(project_root())))

    def test_venv_python_contains_parser_name(self):
        with patch.object(sys, "platform", "linux"):
            py = resolve_venv_python("mineru")
        self.assertIn("mineru", str(py))


if __name__ == "__main__":
    unittest.main()

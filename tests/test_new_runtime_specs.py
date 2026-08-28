"""Tests for Unstructured and Xberg entries in PARSER_RUNTIME_SPECS."""
from __future__ import annotations

import unittest

from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS, ParserRuntimeSpec

RUNTIME_HOST = "host"
RUNTIME_DOCKER = "docker"


class TestUnstructuredSpec(unittest.TestCase):
    def setUp(self):
        self.spec: ParserRuntimeSpec = PARSER_RUNTIME_SPECS["unstructured"]

    def test_spec_exists(self):
        self.assertIn("unstructured", PARSER_RUNTIME_SPECS)

    def test_module(self):
        self.assertEqual(self.spec.module, "src.parsers.unstructured_v2")

    def test_host_only(self):
        self.assertIn(RUNTIME_HOST, self.spec.supported_runtimes)
        self.assertNotIn(RUNTIME_DOCKER, self.spec.supported_runtimes)

    def test_model_args_contain_model_root(self):
        self.assertIn("--model-root", self.spec.model_args)
        self.assertIn("{model_root}", self.spec.model_args)

    def test_offline_env_vars(self):
        env = self.spec.model_env
        self.assertIn("HF_HUB_OFFLINE", env)
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertIn("TRANSFORMERS_OFFLINE", env)
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")

    def test_telemetry_env_vars(self):
        env = self.spec.model_env
        self.assertIn("DO_NOT_TRACK", env)
        self.assertEqual(env["DO_NOT_TRACK"], "1")
        self.assertIn("SCARF_NO_ANALYTICS", env)
        self.assertEqual(env["SCARF_NO_ANALYTICS"], "1")

    def test_hf_home_env(self):
        env = self.spec.model_env
        self.assertIn("HF_HOME", env)
        self.assertIn("{model_root}", env["HF_HOME"])

    def test_preflight_kwargs_model_root(self):
        self.assertIn("model_root_override", self.spec.preflight_kwargs)
        self.assertIn("{model_root}", self.spec.preflight_kwargs["model_root_override"])

    def test_full_cpu_does_not_force_single_omp_thread(self):
        env = self.spec.model_env
        self.assertNotEqual(env.get("OMP_THREAD_LIMIT"), "1")


class TestXbergSpec(unittest.TestCase):
    def setUp(self):
        self.spec: ParserRuntimeSpec = PARSER_RUNTIME_SPECS["xberg"]

    def test_spec_exists(self):
        self.assertIn("xberg", PARSER_RUNTIME_SPECS)

    def test_module(self):
        self.assertEqual(self.spec.module, "src.parsers.xberg_v2")

    def test_host_only(self):
        self.assertIn(RUNTIME_HOST, self.spec.supported_runtimes)
        self.assertNotIn(RUNTIME_DOCKER, self.spec.supported_runtimes)

    def test_model_args_contain_model_root(self):
        self.assertIn("--model-root", self.spec.model_args)
        self.assertIn("{model_root}", self.spec.model_args)

    def test_offline_env_vars(self):
        env = self.spec.model_env
        self.assertIn("HF_HUB_OFFLINE", env)
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertIn("TRANSFORMERS_OFFLINE", env)
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")

    def test_hf_home_env(self):
        env = self.spec.model_env
        self.assertIn("HF_HOME", env)
        self.assertIn("{model_root}", env["HF_HOME"])

    def test_preflight_kwargs_model_root(self):
        self.assertIn("model_root_override", self.spec.preflight_kwargs)
        self.assertIn("{model_root}", self.spec.preflight_kwargs["model_root_override"])


class TestVenvPaths(unittest.TestCase):
    """Venv paths resolve correctly for both new parsers."""

    def _resolve_venv_python(self, parser_name: str) -> object:
        from src.benchmark.execution_paths import resolve_venv_python
        return resolve_venv_python(parser_name)

    def test_unstructured_venv_python_path(self):
        path = self._resolve_venv_python("unstructured")
        self.assertIn("unstructured", str(path))

    def test_xberg_venv_python_path(self):
        path = self._resolve_venv_python("xberg")
        self.assertIn("xberg", str(path))


class TestStandardParsersBothRuntimes(unittest.TestCase):
    """Regression: existing parsers must still support both runtimes."""

    _STANDARD = ["docling", "pymupdf", "liteparse", "mineru", "paddleocr"]

    def test_standard_parsers_support_docker(self):
        for name in self._STANDARD:
            with self.subTest(parser=name):
                spec = PARSER_RUNTIME_SPECS.get(name)
                self.assertIsNotNone(spec, f"{name} not found in PARSER_RUNTIME_SPECS")
                self.assertIn(RUNTIME_DOCKER, spec.supported_runtimes)

    def test_standard_parsers_support_host(self):
        for name in self._STANDARD:
            with self.subTest(parser=name):
                spec = PARSER_RUNTIME_SPECS.get(name)
                self.assertIsNotNone(spec)
                self.assertIn(RUNTIME_HOST, spec.supported_runtimes)

    def test_supported_runtimes_is_frozenset(self):
        for name, spec in PARSER_RUNTIME_SPECS.items():
            with self.subTest(parser=name):
                self.assertIsInstance(spec.supported_runtimes, frozenset)

"""
Direct tests for PARSER_RUNTIME_SPECS entries in runtime_specs.py.

Verifies module names, model_args, model_env, and preflight_kwargs
for each parser without importing the parsers themselves.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS, ParserRuntimeSpec


class TestParserRuntimeSpecsPresence(unittest.TestCase):

    def test_all_parsers_present(self) -> None:
        expected = {"pymupdf", "docling", "paddleocr", "liteparse", "mineru", "unstructured", "xberg"}
        self.assertEqual(set(PARSER_RUNTIME_SPECS.keys()), expected)

    def test_all_specs_are_frozen_dataclass(self) -> None:
        for name, spec in PARSER_RUNTIME_SPECS.items():
            with self.subTest(parser=name):
                self.assertIsInstance(spec, ParserRuntimeSpec)
                with self.assertRaises((AttributeError, TypeError)):
                    spec.module = "mutated"  # type: ignore[misc]


class TestPymupdfSpec(unittest.TestCase):

    def setUp(self) -> None:
        self.spec = PARSER_RUNTIME_SPECS["pymupdf"]

    def test_module(self) -> None:
        self.assertEqual(self.spec.module, "src.parsers.pymupdf_v2")

    def test_no_model_args(self) -> None:
        self.assertEqual(self.spec.model_args, ())

    def test_no_model_env(self) -> None:
        self.assertEqual(self.spec.model_env, {})

    def test_no_preflight_kwargs(self) -> None:
        self.assertEqual(self.spec.preflight_kwargs, {})


class TestDoclingSpec(unittest.TestCase):

    def setUp(self) -> None:
        self.spec = PARSER_RUNTIME_SPECS["docling"]

    def test_module(self) -> None:
        self.assertEqual(self.spec.module, "src.parsers.docling_v2")

    def test_model_args_flag(self) -> None:
        self.assertIn("--model-artifacts-path", self.spec.model_args)

    def test_model_args_placeholder(self) -> None:
        self.assertIn("{model_root}", self.spec.model_args)

    def test_no_model_env(self) -> None:
        self.assertEqual(self.spec.model_env, {})

    def test_preflight_kwargs_key(self) -> None:
        self.assertIn("model_artifacts_override", self.spec.preflight_kwargs)

    def test_preflight_kwargs_placeholder(self) -> None:
        self.assertEqual(
            self.spec.preflight_kwargs["model_artifacts_override"], "{model_root}"
        )


class TestPaddleocrSpec(unittest.TestCase):

    def setUp(self) -> None:
        self.spec = PARSER_RUNTIME_SPECS["paddleocr"]

    def test_module(self) -> None:
        self.assertEqual(self.spec.module, "src.parsers.paddleocr_v2")

    def test_model_args_flag(self) -> None:
        self.assertIn("--model-root", self.spec.model_args)

    def test_model_args_placeholder(self) -> None:
        self.assertIn("{model_root}", self.spec.model_args)

    def test_model_source_check_disabled(self) -> None:
        self.assertEqual(
            self.spec.model_env.get(
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"
            ),
            "True",
        )

    def test_preflight_kwargs_key(self) -> None:
        self.assertIn("model_root_override", self.spec.preflight_kwargs)

    def test_preflight_kwargs_placeholder(self) -> None:
        self.assertEqual(
            self.spec.preflight_kwargs["model_root_override"], "{model_root}"
        )


class TestLiteparseSpec(unittest.TestCase):

    def setUp(self) -> None:
        self.spec = PARSER_RUNTIME_SPECS["liteparse"]

    def test_module(self) -> None:
        self.assertEqual(self.spec.module, "src.parsers.liteparse_v2")

    def test_model_args_flag(self) -> None:
        self.assertIn("--model-artifacts-path", self.spec.model_args)

    def test_model_args_placeholder(self) -> None:
        self.assertIn("{model_root}", self.spec.model_args)

    def test_preflight_kwargs_key(self) -> None:
        self.assertIn("model_artifacts_override", self.spec.preflight_kwargs)

    def test_preflight_kwargs_placeholder(self) -> None:
        self.assertEqual(
            self.spec.preflight_kwargs["model_artifacts_override"], "{model_root}"
        )


class TestMineruSpec(unittest.TestCase):

    def setUp(self) -> None:
        self.spec = PARSER_RUNTIME_SPECS["mineru"]

    def test_module(self) -> None:
        self.assertEqual(self.spec.module, "src.parsers.mineru_v2")

    def test_no_model_args(self) -> None:
        self.assertEqual(self.spec.model_args, ())

    def test_model_env_source(self) -> None:
        self.assertEqual(self.spec.model_env.get("MINERU_MODEL_SOURCE"), "local")

    def test_model_env_hf_home(self) -> None:
        self.assertIn("HF_HOME", self.spec.model_env)
        self.assertIn("{model_root}", self.spec.model_env["HF_HOME"])

    def test_no_preflight_kwargs(self) -> None:
        self.assertEqual(self.spec.preflight_kwargs, {})


if __name__ == "__main__":
    unittest.main()

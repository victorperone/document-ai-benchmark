"""Tests for paddleocr_v2 build_pipeline_kwargs API contract."""
from __future__ import annotations

import unittest
from pathlib import Path

from src.benchmark.config import get_profile
from src.parsers.paddleocr_v2 import (
    PROFILE_BOOL_KEYS,
    build_pipeline_kwargs,
    required_model_keys,
    MODEL_NAMES,
    MODEL_DIRECTORY_CANDIDATES,
)

PARSER_NAME = "paddleocr"


def _fake_model_paths(profile: dict) -> dict[str, Path]:
    """Build a dict of fake Path objects for all required model keys."""
    keys = required_model_keys(profile)
    paths = {}
    for key in keys:
        model_name = MODEL_NAMES[key]
        candidates = MODEL_DIRECTORY_CANDIDATES.get(model_name, (model_name,))
        paths[key] = Path("/fake/models") / candidates[0]
    return paths


class TestBuildPipelineKwargsStructure(unittest.TestCase):
    def _kwargs_for(self, profile_name: str) -> dict:
        p = get_profile(PARSER_NAME, profile_name)
        return build_pipeline_kwargs(_fake_model_paths(p), p)

    def test_kwargs_is_dict(self):
        self.assertIsInstance(self._kwargs_for("default"), dict)

    def test_layout_model_dir_present(self):
        kwargs = self._kwargs_for("default")
        self.assertIn("layout_detection_model_dir", kwargs)

    def test_text_detection_model_dir_present(self):
        kwargs = self._kwargs_for("default")
        self.assertIn("text_detection_model_dir", kwargs)

    def test_text_recognition_model_dir_present(self):
        kwargs = self._kwargs_for("default")
        self.assertIn("text_recognition_model_dir", kwargs)

    def test_use_table_recognition_bool(self):
        kwargs = self._kwargs_for("default")
        self.assertIn("use_table_recognition", kwargs)
        self.assertIsInstance(kwargs["use_table_recognition"], bool)


class TestFullCpuLocalKwargs(unittest.TestCase):
    def _kwargs(self) -> dict:
        p = get_profile(PARSER_NAME, "full_cpu_local")
        return build_pipeline_kwargs(_fake_model_paths(p), p)

    def test_use_seal_recognition_true(self):
        self.assertTrue(self._kwargs()["use_seal_recognition"])

    def test_use_formula_recognition_true(self):
        self.assertTrue(self._kwargs()["use_formula_recognition"])

    def test_use_chart_recognition_true(self):
        self.assertTrue(self._kwargs()["use_chart_recognition"])

    def test_format_block_content_in_kwargs(self):
        kwargs = self._kwargs()
        self.assertIn("format_block_content", kwargs)
        self.assertTrue(kwargs["format_block_content"])

    def test_seal_model_dirs_present_when_seal_enabled(self):
        kwargs = self._kwargs()
        self.assertIn("seal_text_detection_model_dir", kwargs)
        self.assertIn("seal_text_recognition_model_dir", kwargs)


class TestFormatBlockContentConditionality(unittest.TestCase):
    def test_format_block_content_not_added_when_false(self):
        p = get_profile(PARSER_NAME, "default")
        p_copy = dict(p)
        p_copy["format_block_content"] = False
        kwargs = build_pipeline_kwargs(_fake_model_paths(p_copy), p_copy)
        self.assertNotIn("format_block_content", kwargs)

    def test_format_block_content_added_when_true(self):
        p = get_profile(PARSER_NAME, "default")
        p_copy = dict(p)
        p_copy["format_block_content"] = True
        kwargs = build_pipeline_kwargs(_fake_model_paths(p_copy), p_copy)
        self.assertIn("format_block_content", kwargs)
        self.assertTrue(kwargs["format_block_content"])

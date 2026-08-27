"""Tests for host suites in benchmark_profiles.json (section 43.4)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config" / "benchmark_profiles.json"

EXPECTED_HOST_SUITES = [
    "unstructured_host_fast",
    "unstructured_host_auto",
    "unstructured_host_hi_res",
    "unstructured_host_ocr",
    "xberg_host_native",
    "xberg_host_ocr",
]

HOST_ONLY_PARSERS = {"unstructured", "xberg"}


class TestHostSuitesExist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.available = CONFIG_PATH.exists()
        if cls.available:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cls.suites = data.get("suites", {})
        else:
            cls.suites = {}

    def setUp(self):
        if not self.available:
            self.skipTest("benchmark_profiles.json not found")

    def test_all_host_suites_exist(self):
        for name in EXPECTED_HOST_SUITES:
            with self.subTest(suite=name):
                self.assertIn(name, self.suites, f"Suite '{name}' missing from config")

    def test_each_suite_has_parsers_key(self):
        for name in EXPECTED_HOST_SUITES:
            if name in self.suites:
                with self.subTest(suite=name):
                    self.assertIn("parsers", self.suites[name])

    def test_each_suite_has_runtime_key(self):
        for name in EXPECTED_HOST_SUITES:
            if name in self.suites:
                with self.subTest(suite=name):
                    self.assertIn("runtime", self.suites[name])

    def test_host_suites_use_host_runtime(self):
        for name in EXPECTED_HOST_SUITES:
            if name in self.suites:
                with self.subTest(suite=name):
                    self.assertEqual(self.suites[name]["runtime"], "host")

    def test_parsers_list_is_non_empty(self):
        for name in EXPECTED_HOST_SUITES:
            if name in self.suites:
                with self.subTest(suite=name):
                    parsers = self.suites[name].get("parsers", [])
                    self.assertGreater(len(parsers), 0)

    def test_suite_parsers_have_name_and_profile(self):
        for suite_name in EXPECTED_HOST_SUITES:
            if suite_name in self.suites:
                for entry in self.suites[suite_name].get("parsers", []):
                    with self.subTest(suite=suite_name, entry=entry):
                        self.assertIn("name", entry)
                        self.assertIn("profile", entry)


class TestDockerRejectsHostOnlyParsers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.available = CONFIG_PATH.exists()
        if cls.available:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cls.suites = data.get("suites", {})
        else:
            cls.suites = {}

    def setUp(self):
        if not self.available:
            self.skipTest("benchmark_profiles.json not found")

    def _get_docker_suites(self):
        return {
            name: spec for name, spec in self.suites.items()
            if spec.get("runtime") == "docker"
        }

    def test_unstructured_not_in_docker_suites(self):
        docker_suites = self._get_docker_suites()
        for suite_name, spec in docker_suites.items():
            with self.subTest(suite=suite_name):
                parsers = [p["name"] for p in spec.get("parsers", [])]
                self.assertNotIn(
                    "unstructured", parsers,
                    f"unstructured (host-only) found in docker suite '{suite_name}'",
                )

    def test_xberg_not_in_docker_suites(self):
        docker_suites = self._get_docker_suites()
        for suite_name, spec in docker_suites.items():
            with self.subTest(suite=suite_name):
                parsers = [p["name"] for p in spec.get("parsers", [])]
                self.assertNotIn(
                    "xberg", parsers,
                    f"xberg (host-only) found in docker suite '{suite_name}'",
                )


class TestRuntimeSpecRejectsDockerForHostOnly(unittest.TestCase):
    def test_unstructured_supported_runtimes_host_only(self):
        from src.benchmark.runtime_specs import PARSER_SPECS
        spec = next((s for s in PARSER_SPECS if s.name == "unstructured"), None)
        if spec is None:
            self.skipTest("unstructured spec not found")
        self.assertIn("host", spec.supported_runtimes)
        self.assertNotIn("docker", spec.supported_runtimes)

    def test_xberg_supported_runtimes_host_only(self):
        from src.benchmark.runtime_specs import PARSER_SPECS
        spec = next((s for s in PARSER_SPECS if s.name == "xberg"), None)
        if spec is None:
            self.skipTest("xberg spec not found")
        self.assertIn("host", spec.supported_runtimes)
        self.assertNotIn("docker", spec.supported_runtimes)

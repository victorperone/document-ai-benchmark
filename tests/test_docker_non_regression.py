"""Tests confirming Docker parsers are unaffected by host-only additions (section 43.5)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config" / "benchmark_profiles.json"
DOCKER_COMPOSE_PATH = Path(__file__).parent.parent / "compose.yaml"

DOCKER_PARSERS = {"pymupdf", "docling", "paddleocr", "liteparse", "mineru"}
HOST_ONLY_PARSERS = {"unstructured", "xberg"}


class TestDockerParsersUnchanged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.available = CONFIG_PATH.exists()
        if cls.available:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cls.suites = data.get("suites", {})
            cls.profiles = data.get("parsers", {})
        else:
            cls.suites = {}
            cls.profiles = {}

    def setUp(self):
        if not self.available:
            self.skipTest("benchmark_profiles.json not found")

    def test_docker_parsers_still_have_profiles(self):
        for parser in DOCKER_PARSERS:
            with self.subTest(parser=parser):
                self.assertIn(parser, self.profiles, f"'{parser}' lost its profiles entry")

    def test_docker_parsers_have_at_least_one_suite(self):
        parser_in_suites = set()

        for entries in self.suites.values():
            for parser_name, _profile_name in entries:
                parser_in_suites.add(parser_name)

        for parser in DOCKER_PARSERS:
            with self.subTest(parser=parser):
                self.assertIn(
                    parser,
                    parser_in_suites,
                    f"'{parser}' is not referenced by any suite",
                )


class TestDockerComposeHasNoHostOnlyParsers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.available = DOCKER_COMPOSE_PATH.exists()
        cls.text = (
            DOCKER_COMPOSE_PATH.read_text(encoding="utf-8")
            if cls.available else ""
        )

    def setUp(self):
        if not self.available:
            self.fail("compose.yaml not found")

    def test_unstructured_service_absent(self):
        # Should not have a docker service for unstructured (host-only)
        self.assertNotIn("unstructured:", self.text,
                         "compose.yaml has an unstructured service (should be host-only)")

    def test_xberg_service_absent(self):
        self.assertNotIn("xberg:", self.text,
                         "compose.yaml has an xberg service (should be host-only)")

    def test_docker_parser_services_still_present(self):
        # At minimum, some Docker parser service should exist
        found = any(parser in self.text for parser in DOCKER_PARSERS)
        self.assertTrue(found, "No Docker parser services found in compose.yaml")


class TestRuntimeSpecDockerParsersUnchanged(unittest.TestCase):
    def test_docker_parsers_support_docker_runtime(self):
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS

        for parser_name in DOCKER_PARSERS:
            with self.subTest(parser=parser_name):
                self.assertIn(
                    parser_name,
                    PARSER_RUNTIME_SPECS,
                    f"'{parser_name}' is missing from PARSER_RUNTIME_SPECS",
                )

                spec = PARSER_RUNTIME_SPECS[parser_name]

                self.assertIn(
                    "docker",
                    spec.supported_runtimes,
                    f"'{parser_name}' lost docker runtime support",
                )

    def test_host_only_parsers_reject_docker(self):
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS

        for parser_name in HOST_ONLY_PARSERS:
            with self.subTest(parser=parser_name):
                self.assertIn(
                    parser_name,
                    PARSER_RUNTIME_SPECS,
                    f"'{parser_name}' is missing from PARSER_RUNTIME_SPECS",
                )

                spec = PARSER_RUNTIME_SPECS[parser_name]

                self.assertNotIn(
                    "docker",
                    spec.supported_runtimes,
                    f"'{parser_name}' incorrectly supports docker",
                )

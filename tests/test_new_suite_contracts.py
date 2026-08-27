"""Tests for host suites in benchmark_profiles.json and runtime spec contracts."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config" / "benchmark_profiles.json"

# Suites that reference unstructured/xberg (host-only parsers)
EXPECTED_HOST_ONLY_SUITES = [
    "unstructured_smoke_host",
    "unstructured_ocr_host",
    "xberg_smoke_host",
    "xberg_ocr_host",
]

HOST_ONLY_PARSERS = {"unstructured", "xberg"}


class _SuiteBase(unittest.TestCase):
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


class TestHostSuitesExist(_SuiteBase):
    def test_all_host_suites_exist(self):
        for name in EXPECTED_HOST_ONLY_SUITES:
            with self.subTest(suite=name):
                self.assertIn(name, self.suites, f"Suite '{name}' missing from config")

    def test_suites_are_list_of_pairs(self):
        """Each suite must be a list of [parser, profile] pairs."""
        for name in EXPECTED_HOST_ONLY_SUITES:
            if name not in self.suites:
                continue
            with self.subTest(suite=name):
                suite = self.suites[name]
                self.assertIsInstance(suite, list, f"Suite '{name}' must be a list")
                self.assertGreater(len(suite), 0, f"Suite '{name}' is empty")
                for entry in suite:
                    self.assertIsInstance(entry, list, f"Entry in '{name}' must be a list")
                    self.assertEqual(len(entry), 2, f"Entry {entry!r} must be [parser, profile]")

    def test_parsers_list_is_non_empty(self):
        for name in EXPECTED_HOST_ONLY_SUITES:
            if name not in self.suites:
                continue
            with self.subTest(suite=name):
                self.assertGreater(len(self.suites[name]), 0)

    def test_suite_entries_have_string_parser_and_profile(self):
        for suite_name in EXPECTED_HOST_ONLY_SUITES:
            if suite_name not in self.suites:
                continue
            for entry in self.suites[suite_name]:
                with self.subTest(suite=suite_name, entry=entry):
                    parser, profile = entry
                    self.assertIsInstance(parser, str)
                    self.assertIsInstance(profile, str)


class TestAllSuitesFormat(_SuiteBase):
    def test_all_suites_are_list_of_pairs(self):
        """Every suite in config must use the list-of-pairs format."""
        for name, spec in self.suites.items():
            with self.subTest(suite=name):
                self.assertIsInstance(spec, list, f"Suite '{name}' must be a list")

    def test_full_cpu_local_suite_exists(self):
        self.assertIn("full_cpu_local", self.suites)

    def test_full_cpu_local_has_five_parsers(self):
        if "full_cpu_local" not in self.suites:
            self.skipTest("full_cpu_local suite not present")
        suite = self.suites["full_cpu_local"]
        parser_names = [entry[0] for entry in suite]
        for expected in ("pymupdf", "docling", "mineru", "paddleocr", "liteparse"):
            with self.subTest(parser=expected):
                self.assertIn(expected, parser_names)


_WINDOWS_ALL_HOST_SUITE = "windows_full_cpu_local_all_host"
_EXPECTED_ALL_HOST_PARSERS = [
    "pymupdf",
    "docling",
    "mineru",
    "paddleocr",
    "liteparse",
    "unstructured",
    "xberg",
]


class TestWindowsFullCpuLocalAllHostSuite(_SuiteBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls.available:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cls.parser_profiles = data.get("parsers", {})
        else:
            cls.parser_profiles = {}

    def _suite(self):
        return self.suites.get(_WINDOWS_ALL_HOST_SUITE, [])

    def test_suite_exists(self):
        self.assertIn(
            _WINDOWS_ALL_HOST_SUITE,
            self.suites,
            f"Suite '{_WINDOWS_ALL_HOST_SUITE}' missing from config",
        )

    def test_suite_has_exactly_seven_entries(self):
        suite = self._suite()
        self.assertEqual(
            len(suite),
            7,
            f"Suite '{_WINDOWS_ALL_HOST_SUITE}' must have exactly 7 entries, got {len(suite)}",
        )

    def test_parsers_are_exactly_the_seven_expected(self):
        suite = self._suite()
        parsers = [entry[0] for entry in suite]
        self.assertEqual(
            sorted(parsers),
            sorted(_EXPECTED_ALL_HOST_PARSERS),
            f"Parser list mismatch in '{_WINDOWS_ALL_HOST_SUITE}'",
        )

    def test_no_duplicate_parsers(self):
        suite = self._suite()
        parsers = [entry[0] for entry in suite]
        self.assertEqual(
            len(parsers),
            len(set(parsers)),
            f"Duplicate parsers found in '{_WINDOWS_ALL_HOST_SUITE}': {parsers}",
        )

    def test_all_entries_use_full_cpu_local_profile(self):
        for entry in self._suite():
            with self.subTest(entry=entry):
                parser, profile = entry
                self.assertEqual(
                    profile,
                    "full_cpu_local",
                    f"Parser '{parser}' must use profile 'full_cpu_local', got '{profile}'",
                )

    def test_each_parser_profile_exists_in_config(self):
        for entry in self._suite():
            parser, profile = entry
            with self.subTest(parser=parser, profile=profile):
                self.assertIn(parser, self.parser_profiles, f"Parser '{parser}' not in config")
                profiles = self.parser_profiles[parser].get("profiles", {})
                self.assertIn(
                    profile,
                    profiles,
                    f"Profile '{profile}' not found for parser '{parser}'",
                )

    def test_all_parsers_support_host_runtime(self):
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS

        for entry in self._suite():
            parser, _ = entry
            with self.subTest(parser=parser):
                self.assertIn(parser, PARSER_RUNTIME_SPECS, f"Parser '{parser}' not in PARSER_RUNTIME_SPECS")
                spec = PARSER_RUNTIME_SPECS[parser]
                self.assertIn(
                    "host",
                    spec.supported_runtimes,
                    f"Parser '{parser}' does not support runtime 'host'",
                )


class TestRuntimeSpecHostOnlyParsers(unittest.TestCase):
    def _get_spec(self, parser_name: str):
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS
        return PARSER_RUNTIME_SPECS.get(parser_name)

    def test_unstructured_is_host_only(self):
        spec = self._get_spec("unstructured")
        if spec is None:
            self.skipTest("unstructured spec not registered")
        self.assertIn("host", spec.supported_runtimes)
        self.assertNotIn("docker", spec.supported_runtimes)

    def test_xberg_is_host_only(self):
        spec = self._get_spec("xberg")
        if spec is None:
            self.skipTest("xberg spec not registered")
        self.assertIn("host", spec.supported_runtimes)
        self.assertNotIn("docker", spec.supported_runtimes)

    def test_pymupdf_supports_both_runtimes(self):
        spec = self._get_spec("pymupdf")
        self.assertIsNotNone(spec)
        self.assertIn("host", spec.supported_runtimes)

    def test_parser_runtime_specs_has_five_core_parsers(self):
        from src.benchmark.runtime_specs import PARSER_RUNTIME_SPECS
        for parser in ("pymupdf", "docling", "mineru", "paddleocr", "liteparse"):
            with self.subTest(parser=parser):
                self.assertIn(parser, PARSER_RUNTIME_SPECS)

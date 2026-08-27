"""Tests for validate_runtime_support in scripts.run_batch."""
from __future__ import annotations

import unittest

from scripts.run_batch import validate_runtime_support

RUNTIME_HOST = "host"
RUNTIME_DOCKER = "docker"


class TestValidateRuntimeSupportHostOnly(unittest.TestCase):
    def test_unstructured_docker_raises(self):
        with self.assertRaises(SystemExit) as ctx:
            validate_runtime_support([("unstructured", {})], RUNTIME_DOCKER)
        msg = str(ctx.exception)
        self.assertIn("unstructured", msg)
        self.assertIn("docker", msg)

    def test_xberg_docker_raises(self):
        with self.assertRaises(SystemExit) as ctx:
            validate_runtime_support([("xberg", {})], RUNTIME_DOCKER)
        msg = str(ctx.exception)
        self.assertIn("xberg", msg)
        self.assertIn("docker", msg)

    def test_unstructured_host_passes(self):
        validate_runtime_support([("unstructured", {})], RUNTIME_HOST)

    def test_xberg_host_passes(self):
        validate_runtime_support([("xberg", {})], RUNTIME_HOST)

    def test_mixed_batch_docker_raises_for_host_only(self):
        with self.assertRaises(SystemExit) as ctx:
            validate_runtime_support(
                [("docling", {}), ("unstructured", {}), ("xberg", {})],
                RUNTIME_DOCKER,
            )
        msg = str(ctx.exception)
        self.assertIn("unstructured", msg)
        self.assertIn("xberg", msg)

    def test_error_message_lists_supported_runtimes(self):
        with self.assertRaises(SystemExit) as ctx:
            validate_runtime_support([("unstructured", {})], RUNTIME_DOCKER)
        msg = str(ctx.exception)
        self.assertIn("host", msg)

    def test_unknown_parser_does_not_raise(self):
        validate_runtime_support([("unknown_parser_xyz", {})], RUNTIME_DOCKER)

    def test_empty_jobs_does_not_raise(self):
        validate_runtime_support([], RUNTIME_DOCKER)
        validate_runtime_support([], RUNTIME_HOST)


class TestValidateRuntimeSupportStandardParsers(unittest.TestCase):
    """Standard parsers (docling, pymupdf, etc.) must work in both runtimes."""

    _STANDARD = ["docling", "pymupdf", "liteparse", "mineru", "paddleocr"]

    def test_standard_parsers_host_passes(self):
        for parser in self._STANDARD:
            with self.subTest(parser=parser):
                validate_runtime_support([(parser, {})], RUNTIME_HOST)

    def test_standard_parsers_docker_passes(self):
        for parser in self._STANDARD:
            with self.subTest(parser=parser):
                validate_runtime_support([(parser, {})], RUNTIME_DOCKER)

    def test_all_standard_batch_docker_passes(self):
        jobs = [(p, {}) for p in self._STANDARD]
        validate_runtime_support(jobs, RUNTIME_DOCKER)

    def test_all_standard_batch_host_passes(self):
        jobs = [(p, {}) for p in self._STANDARD]
        validate_runtime_support(jobs, RUNTIME_HOST)

    def test_mixed_host_only_and_standard_host_passes(self):
        """Batch containing host-only + standard parsers must pass under RUNTIME_HOST."""
        jobs = [
            ("docling", {}), ("pymupdf", {}), ("liteparse", {}),
            ("mineru", {}), ("paddleocr", {}),
            ("unstructured", {}), ("xberg", {}),
        ]
        validate_runtime_support(jobs, RUNTIME_HOST)

    def test_dry_run_runtime_guard_fires(self):
        """Guard must reject host-only parsers under docker regardless of dry-run flag.

        The guard is called before any Docker or dry-run path; this test confirms
        validate_runtime_support itself raises, which is what run_batch calls before
        constructing any Docker command (dry-run or otherwise).
        """
        with self.assertRaises(SystemExit) as ctx:
            validate_runtime_support([("unstructured", {})], RUNTIME_DOCKER)
        msg = str(ctx.exception)
        self.assertIn("unstructured", msg)
        self.assertIn("docker", msg)

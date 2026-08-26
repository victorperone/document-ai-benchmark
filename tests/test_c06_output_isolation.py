"""
C-06: Output isolation tests — Docker and host runtimes must write to
separate directory trees and must not interfere with each other's
skip/resume logic.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.execution_paths import (
    RUNTIME_DOCKER,
    RUNTIME_HOST,
    project_root,
    resolve_output_root,
)
from src.benchmark.paths import build_output_paths


class TestOutputRootIsolation(unittest.TestCase):
    """Tests 1–3: Root path separation between runtimes."""

    def test_docker_output_root_is_legacy(self):
        """Docker runtime keeps the original /outputs root (no /host suffix)."""
        result = resolve_output_root(RUNTIME_DOCKER)
        self.assertEqual(result, Path("/outputs"))
        self.assertNotIn("host", result.parts)

    def test_host_output_root_has_host_prefix(self):
        """Host runtime output root ends with .../outputs/host."""
        result = resolve_output_root(RUNTIME_HOST)
        self.assertTrue(
            str(result).endswith("/outputs/host")
            or str(result).endswith("\\outputs\\host"),
            f"Expected path ending in outputs/host, got {result}",
        )

    def test_docker_and_host_produce_different_paths(self):
        """Same parser/document/profile must map to distinct directories."""
        docker_root = resolve_output_root(RUNTIME_DOCKER)
        host_root = resolve_output_root(RUNTIME_HOST)

        docker_paths = build_output_paths(
            docker_root, "pymupdf", "sample_doc", "native", create=False
        )
        host_paths = build_output_paths(
            host_root, "pymupdf", "sample_doc", "native", create=False
        )

        self.assertNotEqual(docker_paths.output_dir, host_paths.output_dir)
        self.assertNotEqual(docker_paths.metrics_json, host_paths.metrics_json)


class TestNonInterference(unittest.TestCase):
    """Tests 4–5: Existing outputs in one runtime must not affect the other."""

    def test_host_metrics_not_under_docker_root(self):
        """Host metrics.json path must not be inside the Docker output tree."""
        docker_root = resolve_output_root(RUNTIME_DOCKER)
        host_root = resolve_output_root(RUNTIME_HOST)

        host_paths = build_output_paths(
            host_root, "docling", "report", "ocr", create=False
        )

        # Docker resume/skip checks metrics.json under docker_root.
        # Host metrics path must be outside that subtree.
        self.assertFalse(
            str(host_paths.metrics_json).startswith(str(docker_root)),
            "Host metrics.json must not be inside Docker output root",
        )

    def test_docker_metrics_not_under_host_root(self):
        """Docker metrics.json path must not be inside the host output tree."""
        docker_root = resolve_output_root(RUNTIME_DOCKER)
        host_root = resolve_output_root(RUNTIME_HOST)

        docker_paths = build_output_paths(
            docker_root, "docling", "report", "ocr", create=False
        )

        self.assertFalse(
            str(docker_paths.metrics_json).startswith(str(host_root)),
            "Docker metrics.json must not be inside host output root",
        )


class TestSourceInventoryIsolation(unittest.TestCase):
    """Test 6: Source inventory for host runs sits under outputs/host."""

    def test_source_inventory_host_under_host_prefix(self):
        """Source inventory path for host is under outputs/host/_source_inventory/."""
        host_root = resolve_output_root(RUNTIME_HOST)
        source_inventory_dir = host_root / "_source_inventory"

        # Must be under the host output root
        self.assertTrue(
            str(source_inventory_dir).startswith(str(host_root)),
        )
        # Must include _source_inventory segment
        self.assertEqual(source_inventory_dir.name, "_source_inventory")
        # Must be under project root, not under /outputs
        self.assertTrue(
            str(source_inventory_dir).startswith(str(project_root())),
        )


class TestHostOutputStructure(unittest.TestCase):
    """Test 7: Host results land under outputs/host."""

    def test_host_parser_output_under_host_root(self):
        """Parser output for host runtime is under outputs/host/{parser}/..."""
        host_root = resolve_output_root(RUNTIME_HOST)
        paths = build_output_paths(
            host_root, "liteparse", "invoice_2024", "native", create=False
        )

        self.assertTrue(str(paths.output_dir).startswith(str(host_root)))
        self.assertIn("liteparse", str(paths.output_dir))
        self.assertIn("invoice_2024", str(paths.output_dir))

    def test_host_output_dir_structure(self):
        """Host output dir follows host/{parser}/{document}/{profile} layout."""
        host_root = resolve_output_root(RUNTIME_HOST)
        paths = build_output_paths(
            host_root, "pymupdf", "mydoc", "ocr", create=False
        )
        parts = paths.output_dir.parts

        # After host_root parts, must be parser / document / profile
        host_root_parts = host_root.parts
        relative_parts = parts[len(host_root_parts):]
        self.assertEqual(relative_parts, ("pymupdf", "mydoc", "ocr"))


class TestDockerBehaviorUnchanged(unittest.TestCase):
    """Test 8: Docker output paths are unchanged from the original layout."""

    def test_docker_output_dir_follows_legacy_layout(self):
        """Docker output dir is /outputs/{parser}/{document}/{profile}."""
        docker_root = resolve_output_root(RUNTIME_DOCKER)
        paths = build_output_paths(
            docker_root, "pymupdf", "mydoc", "ocr", create=False
        )
        expected = Path("/outputs") / "pymupdf" / "mydoc" / "ocr"
        self.assertEqual(paths.output_dir, expected)

    def test_docker_root_does_not_contain_host(self):
        """Docker output root must not contain 'host' segment."""
        docker_root = resolve_output_root(RUNTIME_DOCKER)
        self.assertNotIn("host", docker_root.parts)

    def test_docker_metrics_json_path(self):
        """Docker metrics.json path is /outputs/{parser}/{doc}/{profile}/metrics.json."""
        docker_root = resolve_output_root(RUNTIME_DOCKER)
        paths = build_output_paths(
            docker_root, "docling", "contract", "native", create=False
        )
        expected = Path("/outputs/docling/contract/native/metrics.json")
        self.assertEqual(paths.metrics_json, expected)


if __name__ == "__main__":
    unittest.main()

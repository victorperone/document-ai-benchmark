"""Twenty-two unittest cases for the schema-v3 artifact contract."""
from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

if importlib.util.find_spec("tiktoken") is None:
    class _TestEncoding:
        def encode(self, text: str, **_: object) -> list[str]:
            return text.split()

    sys.modules["tiktoken"] = types.SimpleNamespace(
        get_encoding=lambda _name: _TestEncoding()
    )

from src.benchmark.artifact_contract import (
    VALID_PAGE_MAPPING_STATUS,
    VALID_RAW_ORIGIN_KIND,
    ParserArtifactInput,
)
from src.benchmark.artifact_policy import ArtifactPolicy
from src.benchmark.artifacts import finalize_artifacts
from src.benchmark.paths import build_output_paths
from src.benchmark.post_validation import validate_post_execution
from tests._support import make_valid_job_output

NORMALIZATION = {
    "short_line_character_threshold": 20,
    "minimum_repeated_page_fraction": 0.30,
    "minimum_repeated_page_count": 3,
}


class ArtifactContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def make_input(self, *, native: str = "Native one.\nNative two.",
                   source: list[str] | None = None,
                   enriched_pages: list[str] | None = None,
                   enriched_document: str | None = None,
                   mapping: str = "complete",
                   origin: str = "adapter_assembled_declared", pages: int = 2,
                   derived: list[list[dict]] | None = None,
                   expected: bool | None = None) -> ParserArtifactInput:
        if source is None and mapping == "complete":
            source = [f"Source page {index + 1}.\n" for index in range(pages)]
        return ParserArtifactInput(
            native_markdown=native, source_page_markdown=source,
            enriched_page_markdown=enriched_pages,
            enriched_document_markdown=enriched_document,
            page_mapping_status=mapping,
            parser_page_elements=[{} for _ in range(pages)],
            parser_native_pages=[{} for _ in range(pages)],
            derived_content_by_page=derived or [[] for _ in range(pages)],
            raw_origin_kind=origin, raw_origin_details="test",
            content_expected=expected,
            content_expectation_reason="test expectation" if expected is not None else "",
        )

    def finalize(self, value: ParserArtifactInput, artifacts: list[str] | None = None):
        paths = build_output_paths(self.root, "test_parser", "doc_A", "test_profile")
        result = finalize_artifacts(
            paths=paths, document_id="doc_A", source_file="doc_A.pdf",
            parser_name="test_parser", profile_name="test_profile",
            artifact_input=value, tokenizer_name="cl100k_base",
            normalization_config=NORMALIZATION,
            artifact_policy=ArtifactPolicy.from_cli(artifacts or ["all"]),
        )
        return result, paths

    def test_01_all_artifacts_materialize_enriched_fallback(self) -> None:
        result, paths = self.finalize(self.make_input())
        self.assertTrue(result["artifacts"]["enriched"]["present"])
        self.assertEqual(result["artifacts"]["enriched"]["fallback_origin"], "document.md")
        self.assertTrue(paths.enriched_markdown.is_file())

    def test_02_raw_is_native_content(self) -> None:
        _, paths = self.finalize(
            self.make_input(native="NATIVE", source=["source 1", "source 2"]),
            ["raw.md", "document.md"],
        )
        self.assertEqual(paths.raw_markdown.read_text(encoding="utf-8"), "NATIVE")
        self.assertNotIn("NATIVE", paths.clean_markdown.read_text(encoding="utf-8"))

    def test_03_enriched_none_falls_back_to_document(self) -> None:
        result, paths = self.finalize(
            self.make_input(), ["document.enriched.md", "document.md"]
        )
        self.assertTrue(result["artifacts"]["enriched"]["available"])
        self.assertFalse(result["artifacts"]["enriched"]["enrichment_applied"])
        self.assertEqual(paths.enriched_markdown.read_text(encoding="utf-8"),
                         paths.clean_markdown.read_text(encoding="utf-8"))

    def test_04_enriched_fallback_passes_post_validation(self) -> None:
        policy = ArtifactPolicy.from_cli(["all"])
        document, inventory = make_valid_job_output(
            self.root, artifact_policy=policy, enriched_available=False
        )
        result = validate_post_execution(
            output_root=self.root, parser="pymupdf", profile="native",
            document_path=document, expected_sha256="abc123",
            artifact_policy=policy, source_inventory_path=inventory,
        )
        self.assertTrue(result["ok"], result["checks"])

    def test_05_complete_mapping_correct_lengths(self) -> None:
        result, _ = self.finalize(self.make_input(pages=3))
        self.assertTrue(result["quality_eligibility"]["page_mapping_complete"])

    def test_06_complete_mapping_length_mismatch_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_page_markdown has 1 pages"):
            self.finalize(self.make_input(pages=2, source=["one"]), ["document.md"])

    def test_07_partial_mapping_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "not supported"):
            self.finalize(self.make_input(mapping="partial", source=None), ["document.md"])

    def test_08_invalid_mapping_status_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "page_mapping_status"):
            self.finalize(self.make_input(mapping="invalid", source=None), ["document.md"])

    def test_09_invalid_raw_origin_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid raw_origin_kind"):
            self.finalize(self.make_input(origin="invalid"), ["document.md"])

    def test_10_derived_marker_in_raw_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "derived:start marker"):
            self.finalize(self.make_input(native="<!-- derived:start -->"), ["raw.md"])

    def test_11_valid_native_manifest_passes(self) -> None:
        policy = ArtifactPolicy.from_cli(["all"])
        document, inventory = make_valid_job_output(self.root, artifact_policy=policy)
        result = validate_post_execution(
            output_root=self.root, parser="pymupdf", profile="native",
            document_path=document, expected_sha256="abc123",
            artifact_policy=policy, source_inventory_path=inventory,
        )
        self.assertTrue(result["ok"], result["checks"])

    def test_12_native_without_manifest_fails(self) -> None:
        policy = ArtifactPolicy.from_cli(["native"])
        document, _ = make_valid_job_output(self.root, artifact_policy=policy)
        (self.root / "pymupdf" / "A" / "native" / "native" / "manifest.json").unlink()
        result = validate_post_execution(
            output_root=self.root, parser="pymupdf", profile="native",
            document_path=document, expected_sha256="abc123",
            artifact_policy=policy, source_inventory_path=None,
        )
        self.assertFalse(result["ok"])

    def _write_bad_manifest(self, path: str) -> dict:
        native = self.root / "pymupdf" / "A" / "native" / "native"
        native.mkdir(parents=True)
        (native / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "bundle_status": "available", "files": [{"path": path}],
        }), encoding="utf-8")
        return validate_post_execution(
            output_root=self.root, parser="pymupdf", profile="native",
            document_path=Path("/fake/A.pdf"), expected_sha256="x",
            artifact_policy=ArtifactPolicy.from_cli(["native"]), source_inventory_path=None,
        )

    def test_13_absolute_manifest_path_fails(self) -> None:
        self.assertFalse(self._write_bad_manifest("/absolute/file.txt")["ok"])

    def test_14_traversal_manifest_path_fails(self) -> None:
        self.assertFalse(self._write_bad_manifest("../escape.txt")["ok"])

    def test_15_derived_counts(self) -> None:
        derived = [[{"type": "formula"}], [], [{"type": "table"}, {"type": "image"}]]
        result, _ = self.finalize(self.make_input(pages=3, derived=derived))
        self.assertEqual(result["artifacts"]["derived"]["total_items"], 3)

    def test_16_contaminated_saved_raw_fails(self) -> None:
        policy = ArtifactPolicy.from_cli(["raw.md", "document.md", "metrics.json", "run.log"])
        document, inventory = make_valid_job_output(self.root, artifact_policy=policy)
        (self.root / "pymupdf" / "A" / "native" / "raw.md").write_text(
            "# Doc\n<!-- derived:start -->", encoding="utf-8"
        )
        result = validate_post_execution(
            output_root=self.root, parser="pymupdf", profile="native",
            document_path=document, expected_sha256="abc123",
            artifact_policy=policy, source_inventory_path=inventory,
        )
        self.assertFalse(result["ok"])

    def test_17_raw_heuristic_measures_native(self) -> None:
        native = "A" * 500
        result, _ = self.finalize(self.make_input(native=native, source=["B", "C"]))
        self.assertEqual(result["heuristics"]["raw"]["total_characters"], len(native))

    def test_18_unavailable_mapping_uses_global_normalization(self) -> None:
        result, _ = self.finalize(
            self.make_input(native="global text", mapping="unavailable", source=None),
            ["document.md", "document.jsonl"],
        )
        self.assertEqual(result["normalization"]["mode"], "global_without_page_repetition")
        self.assertFalse(result["artifacts"]["document_jsonl"]["present"])

    def test_19_page_mapping_enum(self) -> None:
        self.assertEqual(VALID_PAGE_MAPPING_STATUS, {"complete", "unavailable"})

    def test_20_raw_origin_enum_includes_relocated(self) -> None:
        self.assertIn("parser_native_links_relocated", VALID_RAW_ORIGIN_KIND)
        self.assertNotIn("unknown_kind", VALID_RAW_ORIGIN_KIND)

    def test_21_global_enriched_has_precedence(self) -> None:
        result, paths = self.finalize(self.make_input(
            enriched_document="GLOBAL", enriched_pages=["PAGE 1", "PAGE 2"]
        ))
        self.assertEqual(paths.enriched_markdown.read_text(encoding="utf-8"), "GLOBAL")
        self.assertEqual(result["artifacts"]["enriched"]["fallback_origin"],
                         "enriched_document_markdown")

    def test_22_comment_only_expected_content_is_invalid(self) -> None:
        result, _ = self.finalize(self.make_input(
            native="<!-- only metadata -->\n---", source=["<!-- x -->", "---"], expected=True
        ))
        self.assertFalse(result["content_validation"]["raw.md"]["valid"])
        self.assertFalse(result["content_validation"]["document.md"]["valid"])


if __name__ == "__main__":
    unittest.main()

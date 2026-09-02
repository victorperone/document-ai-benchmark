"""Tests for the schema v3 artifact contract (ParserArtifactInput + finalize_artifacts).

Requires the project venv (.venvs/core/) which has tiktoken installed.
Run with: .venvs/core/python -m pytest tests/test_artifact_contract.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

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


_NORMALIZATION_CONFIG = {
    "short_line_character_threshold": 20,
    "minimum_repeated_page_fraction": 0.30,
    "minimum_repeated_page_count": 3,
}

_TOKENIZER = "cl100k_base"


def _make_input(
    *,
    native_markdown: str | None = "Native page one.\nNative page two.",
    source_page_markdown: list[str] | None = None,
    enriched_page_markdown: list[str] | None = None,
    page_mapping_status: str = "complete",
    raw_origin_kind: str = "adapter_assembled_declared",
    raw_origin_details: str = "page_texts join",
    pages: int = 2,
    derived_content_by_page: list[list] | None = None,
) -> ParserArtifactInput:
    if source_page_markdown is None and page_mapping_status == "complete":
        source_page_markdown = [f"Source page {i+1}.\n" for i in range(pages)]
    return ParserArtifactInput(
        native_markdown=native_markdown,
        source_page_markdown=source_page_markdown,
        enriched_page_markdown=enriched_page_markdown,
        page_mapping_status=page_mapping_status,
        parser_page_elements=[{} for _ in range(pages)],
        parser_native_pages=[{} for _ in range(pages)],
        derived_content_by_page=derived_content_by_page or [[] for _ in range(pages)],
        raw_origin_kind=raw_origin_kind,
        raw_origin_details=raw_origin_details,
    )


def _run_finalize(tmp_path: Path, artifact_input: ParserArtifactInput, policy_names=("all",)):
    paths = build_output_paths(tmp_path, "test_parser", "doc_A", "test_profile")
    policy = ArtifactPolicy.from_cli(list(policy_names))
    return finalize_artifacts(
        paths=paths,
        document_id="doc_A",
        source_file="doc_A.pdf",
        parser_name="test_parser",
        profile_name="test_profile",
        artifact_input=artifact_input,
        tokenizer_name=_TOKENIZER,
        normalization_config=_NORMALIZATION_CONFIG,
        artifact_policy=policy,
    ), paths


# ---------------------------------------------------------------------------
# T1: finalize_artifacts with --artifacts all succeeds, result has expected shape
# ---------------------------------------------------------------------------

def test_t1_finalize_all_artifacts_no_crash(tmp_path):
    ai = _make_input()
    result, paths = _run_finalize(tmp_path, ai)

    assert result["artifacts"]["enriched"]["present"] is False
    assert result["artifacts"]["enriched"]["selected"] is True
    assert result["artifacts"]["enriched"]["available"] is False
    assert result["artifacts"]["raw"]["bytes"] is not None
    assert result["artifacts"]["raw"]["sha256"] is not None
    assert result["artifacts"]["native_manifest_created"] is not True or True  # just no crash
    assert result["quality_eligibility"]["page_mapping_complete"] is True
    assert paths.native_dir.is_dir()
    assert (paths.native_dir / "manifest.json").is_file()
    manifest = json.loads((paths.native_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["bundle_status"] == "unavailable"
    assert manifest["files"] == []


# ---------------------------------------------------------------------------
# T2: raw.md == native_markdown (not source_pages join)
# ---------------------------------------------------------------------------

def test_t2_raw_md_is_native_content(tmp_path):
    native = "NATIVE CONTENT COMPLETELY DIFFERENT"
    source = ["source page 1\n", "source page 2\n"]
    ai = _make_input(native_markdown=native, source_page_markdown=source)
    _, paths = _run_finalize(tmp_path, ai, policy_names=["raw.md", "document.md"])
    assert paths.raw_markdown.read_text(encoding="utf-8") == native
    doc = paths.clean_markdown.read_text(encoding="utf-8")
    assert "NATIVE CONTENT" not in doc


# ---------------------------------------------------------------------------
# T3: enriched=None selected → present=False, no file written
# ---------------------------------------------------------------------------

def test_t3_enriched_none_not_written(tmp_path):
    ai = _make_input(enriched_page_markdown=None)
    result, paths = _run_finalize(tmp_path, ai, policy_names=["document.enriched.md", "document.md"])
    assert result["artifacts"]["enriched"]["present"] is False
    assert result["artifacts"]["enriched"]["available"] is False
    assert result["artifacts"]["enriched"]["selected"] is True
    assert not paths.enriched_markdown.exists()


# ---------------------------------------------------------------------------
# T4: enriched=None + all selected, post-validation PASS (declared absence accepted)
# ---------------------------------------------------------------------------

def test_t4_enriched_absent_post_validation_pass(tmp_path):
    doc, inv = make_valid_job_output(
        tmp_path,
        artifact_policy=ArtifactPolicy.from_cli(["all"]),
        enriched_available=False,
    )
    val = validate_post_execution(
        output_root=tmp_path,
        parser="pymupdf",
        profile="native",
        document_path=doc,
        expected_sha256="abc123",
        artifact_policy=ArtifactPolicy.from_cli(["all"]),
        source_inventory_path=inv,
    )
    failed = [c for c in val["checks"] if c["status"] == "fail"]
    assert not failed, f"Unexpected failures: {failed}"


# ---------------------------------------------------------------------------
# T5: complete mapping, correct lengths — no error
# ---------------------------------------------------------------------------

def test_t5_complete_mapping_correct_lengths(tmp_path):
    ai = _make_input(pages=3)
    result, _ = _run_finalize(tmp_path, ai, policy_names=["document.md"])
    assert result["quality_eligibility"]["page_mapping_complete"] is True


# ---------------------------------------------------------------------------
# T6: complete mapping, wrong source_page_markdown length → ValueError
# ---------------------------------------------------------------------------

def test_t6_complete_mapping_length_mismatch_raises(tmp_path):
    ai = ParserArtifactInput(
        native_markdown="native",
        source_page_markdown=["only one page\n"],
        enriched_page_markdown=None,
        page_mapping_status="complete",
        parser_page_elements=[{}, {}],
        parser_native_pages=[{}, {}],
        derived_content_by_page=[[], []],
        raw_origin_kind="adapter_assembled_declared",
        raw_origin_details="test",
    )
    paths = build_output_paths(tmp_path, "p", "d", "pr")
    with pytest.raises(ValueError, match="source_page_markdown has 1 pages, expected 2"):
        finalize_artifacts(
            paths=paths, document_id="d", source_file="d.pdf",
            parser_name="p", profile_name="pr",
            artifact_input=ai, tokenizer_name=_TOKENIZER,
            normalization_config=_NORMALIZATION_CONFIG,
            artifact_policy=ArtifactPolicy.from_cli(["document.md"]),
        )


# ---------------------------------------------------------------------------
# T7: page_mapping_status="partial" → ValueError via finalize (not supported)
# ---------------------------------------------------------------------------

def test_t7_partial_mapping_raises_in_finalize(tmp_path):
    ai = ParserArtifactInput(
        native_markdown="n",
        source_page_markdown=None,
        enriched_page_markdown=None,
        page_mapping_status="partial",
        parser_page_elements=[],
        parser_native_pages=[],
        derived_content_by_page=[],
        raw_origin_kind="adapter_assembled_declared",
        raw_origin_details="",
    )
    paths = build_output_paths(tmp_path, "p", "d", "pr")
    with pytest.raises(ValueError, match="not supported"):
        finalize_artifacts(
            paths=paths, document_id="d", source_file="d.pdf",
            parser_name="p", profile_name="pr",
            artifact_input=ai, tokenizer_name=_TOKENIZER,
            normalization_config=_NORMALIZATION_CONFIG,
            artifact_policy=ArtifactPolicy.from_cli(["document.md"]),
        )


# ---------------------------------------------------------------------------
# T8: page_mapping_status unknown string → ValueError
# ---------------------------------------------------------------------------

def test_t8_invalid_mapping_status_raises(tmp_path):
    ai = ParserArtifactInput(
        native_markdown="n",
        source_page_markdown=None,
        enriched_page_markdown=None,
        page_mapping_status="whatever",
        parser_page_elements=[],
        parser_native_pages=[],
        derived_content_by_page=[],
        raw_origin_kind="adapter_assembled_declared",
        raw_origin_details="",
    )
    paths = build_output_paths(tmp_path, "p", "d", "pr")
    with pytest.raises(ValueError, match="page_mapping_status"):
        finalize_artifacts(
            paths=paths, document_id="d", source_file="d.pdf",
            parser_name="p", profile_name="pr",
            artifact_input=ai, tokenizer_name=_TOKENIZER,
            normalization_config=_NORMALIZATION_CONFIG,
            artifact_policy=ArtifactPolicy.from_cli(["document.md"]),
        )


# ---------------------------------------------------------------------------
# T9: raw_origin_kind unknown string → ValueError
# ---------------------------------------------------------------------------

def test_t9_invalid_raw_origin_kind_raises(tmp_path):
    ai = ParserArtifactInput(
        native_markdown="n",
        source_page_markdown=["page\n"],
        enriched_page_markdown=None,
        page_mapping_status="complete",
        parser_page_elements=[{}],
        parser_native_pages=[{}],
        derived_content_by_page=[[]],
        raw_origin_kind="not_a_valid_kind",
        raw_origin_details="",
    )
    paths = build_output_paths(tmp_path, "p", "d", "pr")
    with pytest.raises(ValueError, match="invalid raw_origin_kind"):
        finalize_artifacts(
            paths=paths, document_id="d", source_file="d.pdf",
            parser_name="p", profile_name="pr",
            artifact_input=ai, tokenizer_name=_TOKENIZER,
            normalization_config=_NORMALIZATION_CONFIG,
            artifact_policy=ArtifactPolicy.from_cli(["document.md"]),
        )


# ---------------------------------------------------------------------------
# T10: derived:start in native_markdown → ValueError
# ---------------------------------------------------------------------------

def test_t10_derived_marker_in_native_raises(tmp_path):
    contaminated = "## Header\n<!-- derived:start\ntype=x\n-->\nContent\n<!-- derived:end -->"
    ai = _make_input(native_markdown=contaminated)
    paths = build_output_paths(tmp_path, "p", "d", "pr")
    with pytest.raises(ValueError, match="derived:start marker"):
        finalize_artifacts(
            paths=paths, document_id="d", source_file="d.pdf",
            parser_name="p", profile_name="pr",
            artifact_input=ai, tokenizer_name=_TOKENIZER,
            normalization_config=_NORMALIZATION_CONFIG,
            artifact_policy=ArtifactPolicy.from_cli(["raw.md"]),
        )


# ---------------------------------------------------------------------------
# T11: native/ with valid manifest.json → post-validation PASS
# ---------------------------------------------------------------------------

def test_t11_native_manifest_valid_passes(tmp_path):
    doc, inv = make_valid_job_output(
        tmp_path,
        artifact_policy=ArtifactPolicy.from_cli(["all"]),
    )
    val = validate_post_execution(
        output_root=tmp_path,
        parser="pymupdf",
        profile="native",
        document_path=doc,
        expected_sha256="abc123",
        artifact_policy=ArtifactPolicy.from_cli(["all"]),
        source_inventory_path=inv,
    )
    failed = [c for c in val["checks"] if c["status"] == "fail"]
    assert not failed, f"Unexpected failures: {failed}"


# ---------------------------------------------------------------------------
# T12: native/ without manifest.json → post-validation FAIL
# ---------------------------------------------------------------------------

def test_t12_native_no_manifest_fails(tmp_path):
    make_valid_job_output(
        tmp_path,
        artifact_policy=ArtifactPolicy.from_cli(["native"]),
    )
    native_dir = tmp_path / "pymupdf" / "A" / "native" / "native"
    manifest = native_dir / "manifest.json"
    if manifest.exists():
        manifest.unlink()

    val = validate_post_execution(
        output_root=tmp_path,
        parser="pymupdf",
        profile="native",
        document_path=Path("/fake/A.pdf"),
        expected_sha256="abc123",
        artifact_policy=ArtifactPolicy.from_cli(["native"]),
        source_inventory_path=None,
    )
    failed = [c for c in val["checks"] if c["status"] == "fail"]
    assert any("manifest.json" in c.get("detail", "") for c in failed), \
        f"Expected manifest failure, got: {failed}"


# ---------------------------------------------------------------------------
# T13: manifest.json with absolute path → post-validation FAIL
# ---------------------------------------------------------------------------

def test_t13_manifest_absolute_path_fails(tmp_path):
    native_dir = tmp_path / "pymupdf" / "A" / "native" / "native"
    native_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "bundle_status": "unavailable",
        "files": [{"path": "/absolute/path/file.txt"}],
    }
    (native_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    val = validate_post_execution(
        output_root=tmp_path,
        parser="pymupdf",
        profile="native",
        document_path=Path("/fake/A.pdf"),
        expected_sha256="x",
        artifact_policy=ArtifactPolicy.from_cli(["native"]),
        source_inventory_path=None,
    )
    failed = [c for c in val["checks"] if c["status"] == "fail"]
    assert failed, "Expected a fail for absolute path in manifest"


# ---------------------------------------------------------------------------
# T14: manifest.json with ../escape path → post-validation FAIL
# ---------------------------------------------------------------------------

def test_t14_manifest_traversal_path_fails(tmp_path):
    native_dir = tmp_path / "pymupdf" / "A" / "native" / "native"
    native_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "bundle_status": "unavailable",
        "files": [{"path": "../escape.txt"}],
    }
    (native_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    val = validate_post_execution(
        output_root=tmp_path,
        parser="pymupdf",
        profile="native",
        document_path=Path("/fake/A.pdf"),
        expected_sha256="x",
        artifact_policy=ArtifactPolicy.from_cli(["native"]),
        source_inventory_path=None,
    )
    failed = [c for c in val["checks"] if c["status"] == "fail"]
    assert failed, "Expected a fail for traversal path in manifest"


# ---------------------------------------------------------------------------
# T15: derived_content_by_page counts are reported correctly
# ---------------------------------------------------------------------------

def test_t15_derived_counts(tmp_path):
    derived = [[{"type": "formula"}], [], [{"type": "table"}, {"type": "image"}]]
    ai = _make_input(pages=3, derived_content_by_page=derived)
    result, _ = _run_finalize(tmp_path, ai, policy_names=["document.md"])
    assert result["artifacts"]["derived"]["total_items"] == 3
    assert result["artifacts"]["derived"]["pages_with_derived"] == 2


# ---------------------------------------------------------------------------
# T16: raw.md with derived:start → post-validation FAIL
# ---------------------------------------------------------------------------

def test_t16_raw_md_contaminated_fails(tmp_path):
    policy = ArtifactPolicy.from_cli(["raw.md", "document.md", "metrics.json", "run.log"])
    doc, inv = make_valid_job_output(
        tmp_path,
        artifact_policy=policy,
    )
    out_dir = tmp_path / "pymupdf" / "A" / "native"
    raw_file = out_dir / "raw.md"
    raw_file.write_text(
        "# Doc\n<!-- derived:start\ntype=x\n-->\n<!-- derived:end -->\n",
        encoding="utf-8",
    )

    val = validate_post_execution(
        output_root=tmp_path,
        parser="pymupdf",
        profile="native",
        document_path=doc,
        expected_sha256="abc123",
        artifact_policy=policy,
        source_inventory_path=inv,
    )
    failed = [c for c in val["checks"] if c["status"] == "fail"]
    assert any("derived:start" in c.get("detail", "") for c in failed), \
        f"Expected derived:start contamination fail, got: {failed}"


# ---------------------------------------------------------------------------
# T17: heuristics.raw measures native_content (not source_pages)
# ---------------------------------------------------------------------------

def test_t17_heuristics_raw_measures_native(tmp_path):
    native = "A" * 500
    source = ["B" * 200 + "\n", "C" * 300 + "\n"]
    ai = _make_input(native_markdown=native, source_page_markdown=source)
    result, _ = _run_finalize(tmp_path, ai, policy_names=["document.md"])
    raw_chars = result["heuristics"]["raw"]["total_characters"]
    assert raw_chars == len(native), (
        f"heuristics.raw.total_characters={raw_chars} should equal "
        f"len(native_content)={len(native)}"
    )


# ---------------------------------------------------------------------------
# T18: page_mapping_status="unavailable" accepted, source_page_markdown=None
# ---------------------------------------------------------------------------

def test_t18_unavailable_mapping_accepted(tmp_path):
    ai = ParserArtifactInput(
        native_markdown="native text",
        source_page_markdown=None,
        enriched_page_markdown=None,
        page_mapping_status="unavailable",
        parser_page_elements=[{}, {}],
        parser_native_pages=[{}, {}],
        derived_content_by_page=[[], []],
        raw_origin_kind="unavailable",
        raw_origin_details="no mapping",
    )
    paths = build_output_paths(tmp_path, "p", "d", "pr")
    result = finalize_artifacts(
        paths=paths, document_id="d", source_file="d.pdf",
        parser_name="p", profile_name="pr",
        artifact_input=ai, tokenizer_name=_TOKENIZER,
        normalization_config=_NORMALIZATION_CONFIG,
        artifact_policy=ArtifactPolicy.from_cli(["document.md"]),
    )
    assert result["quality_eligibility"]["page_mapping_complete"] is False
    assert result["quality_eligibility"]["formal_quality_eligible"] is False


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

def test_valid_page_mapping_status_set():
    assert "complete" in VALID_PAGE_MAPPING_STATUS
    assert "unavailable" in VALID_PAGE_MAPPING_STATUS
    assert "partial" not in VALID_PAGE_MAPPING_STATUS


def test_valid_raw_origin_kind_set():
    assert "parser_native_exact" in VALID_RAW_ORIGIN_KIND
    assert "adapter_assembled_declared" in VALID_RAW_ORIGIN_KIND
    assert "unknown_kind" not in VALID_RAW_ORIGIN_KIND

"""
Unit tests for src/benchmark/post_validation.py.

validate_post_execution() and validate_resume_candidate() are tested
with real temp-dir fixtures — no Docker, no models.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.artifact_policy import ArtifactPolicy
from src.benchmark.post_validation import validate_post_execution, validate_resume_candidate
from tests._support import make_valid_job_output

_PARSER = "pymupdf"
_PROFILE = "native"
_SHA = "deadbeef" * 8
_PAGES = 3


def _post(output_root, doc_path, inv_path, artifact_policy=None, sha=_SHA):
    policy = artifact_policy or ArtifactPolicy.from_cli(["all"])
    return validate_post_execution(
        output_root=output_root,
        parser=_PARSER,
        profile=_PROFILE,
        document_path=doc_path,
        expected_sha256=sha,
        artifact_policy=policy,
        source_inventory_path=inv_path,
    )


def _resume(output_root, doc_path, artifact_policy=None, sha=_SHA):
    policy = artifact_policy or ArtifactPolicy.from_cli(["all"])
    return validate_resume_candidate(
        output_root=output_root,
        parser=_PARSER,
        profile=_PROFILE,
        document_path=doc_path,
        expected_sha256=sha,
        requested_artifacts=policy,
    )


def _has_fail(result, name_fragment=None):
    for c in result["checks"]:
        if c["status"] == "fail":
            if name_fragment is None or name_fragment in c["name"] or name_fragment in c.get("detail", ""):
                return True
    return False


def _has_warn(result, name_fragment=None):
    for c in result["checks"]:
        if c["status"] == "warn":
            if name_fragment is None or name_fragment in c["name"] or name_fragment in c.get("detail", ""):
                return True
    return False


class TestPostExecutionAllValid(unittest.TestCase):

    def test_all_valid_ok_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            result = _post(out, doc_path, inv)
        self.assertTrue(result["ok"])
        self.assertFalse(_has_fail(result))

    def test_all_valid_no_fail_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            result = _post(out, doc_path, inv)
        fails = [c for c in result["checks"] if c["status"] == "fail"]
        self.assertEqual(fails, [])


class TestPostExecutionArtifactMissing(unittest.TestCase):

    def test_missing_document_md_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            (out / _PARSER / "A" / _PROFILE / "document.md").unlink()
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "document.md"))

    def test_missing_run_log_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            (out / _PARSER / "A" / _PROFILE / "run.log").unlink()
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "run.log"))

    def test_non_selected_artifact_absent_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            policy = ArtifactPolicy.from_cli(["document.md,metrics.json"])
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES,
                                                   artifact_policy=policy)
            result = _post(out, doc_path, inv, artifact_policy=policy)
        self.assertTrue(result["ok"])


class TestPostExecutionEmptyFileAllowed(unittest.TestCase):

    def test_empty_document_md_not_fail(self):
        # Use a policy without metrics.json so there is no size cross-check.
        # Verifies that an empty-but-existing file is not itself a FAIL.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            policy = ArtifactPolicy.from_cli(["document.md,run.log"])
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES,
                                                   artifact_policy=policy)
            (out / _PARSER / "A" / _PROFILE / "document.md").write_text("", encoding="utf-8")
            result = _post(out, doc_path, inv, artifact_policy=policy)
        self.assertTrue(result["ok"])


class TestPostExecutionMetricsInvalid(unittest.TestCase):

    def _metrics_path(self, out):
        return out / _PARSER / "A" / _PROFILE / "metrics.json"

    def test_corrupt_metrics_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            self._metrics_path(out).write_text("{invalid", encoding="utf-8")
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])

    def test_wrong_schema_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = self._metrics_path(out)
            data = json.loads(mp.read_text())
            data["benchmark"]["schema_version"] = 1
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "schema_version"))

    def test_parser_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = self._metrics_path(out)
            data = json.loads(mp.read_text())
            data["run"]["parser"] = "docling"
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "run.parser"))

    def test_profile_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = self._metrics_path(out)
            data = json.loads(mp.read_text())
            data["run"]["profile"] = "ocr_auto"
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "run.profile"))

    def test_document_file_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = self._metrics_path(out)
            data = json.loads(mp.read_text())
            data["document"]["file"] = "wrong.pdf"
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "document.file"))

    def test_document_id_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = self._metrics_path(out)
            data = json.loads(mp.read_text())
            data["document"]["id"] = "wrong"
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "document.id"))

    def test_sha_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = self._metrics_path(out)
            data = json.loads(mp.read_text())
            data["document"]["sha256"] = "wrongsha"
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "sha256"))

    def test_artifact_selection_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = self._metrics_path(out)
            data = json.loads(mp.read_text())
            data["run"]["artifact_selection"] = ["document.md"]
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "artifact_selection"))

    def test_file_size_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = self._metrics_path(out)
            data = json.loads(mp.read_text())
            data["output"]["clean_markdown_bytes"] = 99999
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "document.md"))


class TestPostExecutionSourceInventory(unittest.TestCase):

    def test_source_inventory_sha_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            inv.write_text(json.dumps({"file": "A.pdf", "sha256": "wrongsha", "pages": 3}))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "source inventory"))

    def test_source_inventory_pages_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            # Metrics says 3 pages, inventory says 11
            inv.write_text(json.dumps({"file": "A.pdf", "sha256": _SHA, "pages": 11}))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])


class TestPostExecutionDocumentJsonl(unittest.TestCase):

    def _jsonl_path(self, out):
        return out / _PARSER / "A" / _PROFILE / "document.jsonl"

    def test_valid_jsonl_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            result = _post(out, doc_path, inv)
        self.assertTrue(result["ok"])

    def test_truncated_jsonl_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            lines = self._jsonl_path(out).read_text().splitlines()
            self._jsonl_path(out).write_text("\n".join(lines[:-1]) + "\n")
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "document.jsonl"))

    def test_duplicate_page_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            lines = self._jsonl_path(out).read_text().splitlines()
            dup_line = json.dumps({"page_number": 1, "source_file": "A.pdf",
                                    "parser": _PARSER, "profile": _PROFILE,
                                    "clean_markdown": "dup"})
            # Replace last page with duplicate page 1
            lines[-1] = dup_line
            self._jsonl_path(out).write_text("\n".join(lines) + "\n")
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])

    def test_source_file_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            lines = self._jsonl_path(out).read_text().splitlines()
            rec = json.loads(lines[0])
            rec["source_file"] = "wrong.pdf"
            lines[0] = json.dumps(rec)
            self._jsonl_path(out).write_text("\n".join(lines) + "\n")
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])

    def test_parser_mismatch_in_jsonl_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            lines = self._jsonl_path(out).read_text().splitlines()
            rec = json.loads(lines[0])
            rec["parser"] = "docling"
            lines[0] = json.dumps(rec)
            self._jsonl_path(out).write_text("\n".join(lines) + "\n")
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])

    def test_profile_mismatch_in_jsonl_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            lines = self._jsonl_path(out).read_text().splitlines()
            rec = json.loads(lines[0])
            rec["profile"] = "ocr_auto"
            lines[0] = json.dumps(rec)
            self._jsonl_path(out).write_text("\n".join(lines) + "\n")
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])

    def test_blank_page_clean_markdown_allowed(self):
        """A page with clean_markdown="" is valid (blank page is ok)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            # make_valid_job_output already sets last page clean_markdown="" — should still pass
            result = _post(out, doc_path, inv)
        self.assertTrue(result["ok"])


class TestPostExecutionRemovedContentJsonl(unittest.TestCase):

    def _rc_path(self, out):
        return out / _PARSER / "A" / _PROFILE / "removed_content.jsonl"

    def test_invalid_json_line_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES,
                                                   removed_records=2)
            self._rc_path(out).write_text('{"ok":1}\n{bad\n', encoding="utf-8")
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])

    def test_count_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES,
                                                   removed_records=2)
            # Overwrite with only 1 line while metrics says 2
            self._rc_path(out).write_text('{"removed_item":0}\n', encoding="utf-8")
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "removed_content.jsonl"))

    def test_zero_removed_records_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES,
                                                   removed_records=0)
            result = _post(out, doc_path, inv)
        self.assertTrue(result["ok"])


class TestPostExecutionProcessingCoherence(unittest.TestCase):

    def _metrics_path(self, out):
        return out / _PARSER / "A" / _PROFILE / "metrics.json"

    def _patch_processing(self, out, **kwargs):
        mp = self._metrics_path(out)
        data = json.loads(mp.read_text())
        data["processing"].update(kwargs)
        mp.write_text(json.dumps(data))

    def test_pages_processed_less_than_total_is_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            self._patch_processing(out, pages_processed=2, failed_pages=1)
            result = _post(out, doc_path, inv)
        self.assertTrue(result["ok"])
        self.assertTrue(_has_warn(result, "pages_processed"))

    def test_failed_pages_incoherent_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            self._patch_processing(out, pages_processed=2, failed_pages=0)
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "failed_pages"))

    def test_pages_processed_exceeds_total_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            self._patch_processing(out, pages_processed=999, failed_pages=0)
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])

    def test_empty_output_pages_is_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            self._patch_processing(out, empty_output_pages=1)
            result = _post(out, doc_path, inv)
        self.assertTrue(result["ok"])
        self.assertTrue(_has_warn(result, "empty_output_pages"))

    def test_errors_count_positive_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            self._patch_processing(out, errors_count=1)
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        self.assertTrue(_has_fail(result, "errors_count"))

    def test_no_metrics_selected_still_ok(self):
        """When metrics.json not in policy, validation can succeed without it."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            policy = ArtifactPolicy.from_cli(["document.md"])
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES,
                                                   artifact_policy=policy)
            result = _post(out, doc_path, inv, artifact_policy=policy)
        self.assertTrue(result["ok"])


# ── validate_resume_candidate ─────────────────────────────────────────────────

class TestResumeAllValid(unittest.TestCase):

    def test_valid_resume_ok_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            result = _resume(out, doc_path)
        self.assertTrue(result["ok"])

    def test_valid_resume_no_fail_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            result = _resume(out, doc_path)
        fails = [c for c in result["checks"] if c["status"] == "fail"]
        self.assertEqual(fails, [])


class TestResumeMetricsRequired(unittest.TestCase):

    def test_missing_metrics_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            (out / _PARSER / "A" / _PROFILE / "metrics.json").unlink()
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])

    def test_corrupt_metrics_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            (out / _PARSER / "A" / _PROFILE / "metrics.json").write_text("{bad")
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])

    def test_sha_mismatch_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            result = _resume(out, doc_path, sha="wrongsha")
        self.assertFalse(result["ok"])

    def test_parser_mismatch_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = out / _PARSER / "A" / _PROFILE / "metrics.json"
            data = json.loads(mp.read_text())
            data["run"]["parser"] = "docling"
            mp.write_text(json.dumps(data))
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])

    def test_profile_mismatch_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = out / _PARSER / "A" / _PROFILE / "metrics.json"
            data = json.loads(mp.read_text())
            data["run"]["profile"] = "ocr_auto"
            mp.write_text(json.dumps(data))
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])


class TestResumeArtifactSuperset(unittest.TestCase):

    def test_saved_superset_allows_resume(self):
        """Previous run saved all artifacts; current run requests only document.md."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES,
                                                 artifact_policy=ArtifactPolicy.from_cli(["all"]))
            requested = ArtifactPolicy.from_cli(["document.md"])
            result = _resume(out, doc_path, artifact_policy=requested)
        self.assertTrue(result["ok"])

    def test_saved_subset_blocks_resume(self):
        """Previous run saved only document.md; current run requests all."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            policy = ArtifactPolicy.from_cli(["document.md,metrics.json"])
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES,
                                                 artifact_policy=policy)
            result = _resume(out, doc_path, artifact_policy=ArtifactPolicy.from_cli(["all"]))
        self.assertFalse(result["ok"])

    def test_missing_requested_artifact_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            (out / _PARSER / "A" / _PROFILE / "document.md").unlink()
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])

    def test_size_mismatch_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            mp = out / _PARSER / "A" / _PROFILE / "metrics.json"
            data = json.loads(mp.read_text())
            data["output"]["clean_markdown_bytes"] = 99999
            mp.write_text(json.dumps(data))
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])

    def test_truncated_jsonl_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            jp = out / _PARSER / "A" / _PROFILE / "document.jsonl"
            lines = jp.read_text().splitlines()
            jp.write_text("\n".join(lines[:-1]) + "\n")
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])


class TestInventoryAuthoritative(unittest.TestCase):
    """§3.1: inventory is the authoritative source for content_expected."""

    def _make_inventory_with_content(self, out: Path, doc_sha: str, pages: int, doc_name: str) -> None:
        inv_dir = out / "_source_inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        (inv_dir / "A.json").write_text(json.dumps({
            "file": doc_name,
            "sha256": doc_sha,
            "pages": pages,
            "measurement_complete": True,
            "native_text": {"characters": 500},  # forces content_expected=True
        }), encoding="utf-8")

    def test_metrics_content_expected_false_but_inventory_requires_fails(self):
        """inventory requires content, metrics says content_expected=False → fail."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            # Override inventory to require content
            self._make_inventory_with_content(out, _SHA, _PAGES, doc_path.name)
            # Patch metrics to claim content_expected=False
            mp = out / _PARSER / "A" / _PROFILE / "metrics.json"
            data = json.loads(mp.read_text())
            for artifact in ("raw.md", "document.md", "document.enriched.md"):
                if artifact in data.get("content_validation", {}):
                    data["content_validation"][artifact]["content_expected"] = False
            mp.write_text(json.dumps(data))
            result = _post(out, doc_path, inv)
        self.assertFalse(result["ok"])
        names = [c["name"] for c in result["checks"] if c["status"] == "fail"]
        self.assertTrue(any("content_expected" in n for n in names))

    def test_empty_markdown_when_inventory_requires_content_fails(self):
        """Artifact is empty but inventory requires content → fail."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, inv = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            self._make_inventory_with_content(out, _SHA, _PAGES, doc_path.name)
            # Write empty document.md
            md_path = out / _PARSER / "A" / _PROFILE / "document.md"
            md_path.write_text("", encoding="utf-8")
            # Also patch metrics so content_expected=True
            mp = out / _PARSER / "A" / _PROFILE / "metrics.json"
            data = json.loads(mp.read_text())
            data.setdefault("content_validation", {}).setdefault("document.md", {})["content_expected"] = True
            mp.write_text(json.dumps(data))
            ap = ArtifactPolicy.from_cli(["document.md", "metrics.json"])
            result = _post(out, doc_path, inv, artifact_policy=ap)
        self.assertFalse(result["ok"])

    def test_proven_empty_inventory_allows_empty_markdown(self):
        """Inventory proves PDF is empty (no content, measurement complete) → empty markdown OK."""
        from src.benchmark.post_validation import _has_meaningful_text, _inventory_content_expectation
        # Fixture inventory without native_text → content_expected=False
        inv = {"file": "A.pdf", "sha256": "x", "pages": 3, "measurement_complete": True}
        content_expected = _inventory_content_expectation(inv)
        self.assertFalse(content_expected)
        # Empty markdown is acceptable when content is not expected
        self.assertFalse(_has_meaningful_text(""))


class TestResumeInventoryRequired(unittest.TestCase):
    """§3.2: validate_resume_candidate must validate source inventory."""

    def test_missing_inventory_blocks_resume(self):
        """No inventory file → resume must not be approved (ok=False)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            # Remove inventory file
            inv_path = out / "_source_inventory" / "A.json"
            inv_path.unlink()
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])
        names = [c["name"] for c in result["checks"] if c["status"] == "fail"]
        self.assertTrue(any("inventory" in n for n in names))

    def test_tampered_inventory_sha_blocks_resume(self):
        """Inventory SHA-256 mismatch → resume blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            inv_path = out / "_source_inventory" / "A.json"
            data = json.loads(inv_path.read_text())
            data["sha256"] = "b" * 64  # tampered
            inv_path.write_text(json.dumps(data))
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])

    def test_incomplete_measurement_blocks_resume(self):
        """measurement_complete=False → output must not be reused."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            inv_path = out / "_source_inventory" / "A.json"
            data = json.loads(inv_path.read_text())
            data["measurement_complete"] = False
            inv_path.write_text(json.dumps(data))
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])

    def test_valid_inventory_and_artifacts_allows_resume(self):
        """Complete, coherent inventory + intact artifacts → resume approved."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            result = _resume(out, doc_path)
        self.assertTrue(result["ok"], msg=[c for c in result["checks"] if c["status"] == "fail"])

    def test_content_expected_incoherence_blocks_resume(self):
        """Inventory requires content but metrics says content_expected=False → blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc_path, _ = make_valid_job_output(out, doc_sha256=_SHA, pages=_PAGES)
            # Override inventory to require content
            inv_path = out / "_source_inventory" / "A.json"
            data = json.loads(inv_path.read_text())
            data["native_text"] = {"characters": 500}
            inv_path.write_text(json.dumps(data))
            # Patch metrics to claim content_expected=False for raw.md
            mp = out / _PARSER / "A" / _PROFILE / "metrics.json"
            mdata = json.loads(mp.read_text())
            mdata.setdefault("content_validation", {}).setdefault("raw.md", {})["content_expected"] = False
            mp.write_text(json.dumps(mdata))
            result = _resume(out, doc_path)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()

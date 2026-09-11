"""Post-execution and resume-candidate validation for benchmark outputs.

``validate_post_execution`` checks that all selected artifacts were written
correctly after a parser run.  ``validate_resume_candidate`` checks whether a
previously written run can be reused without re-running the parser.

Both functions return a dict with a top-level ``ok`` boolean and a list of
named ``checks``, each with a ``status`` of ``"pass"``, ``"warn"``, or
``"fail"``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.benchmark.artifact_policy import ArtifactPolicy
from src.benchmark.content_validation import inventory_requires_content
from src.benchmark.paths import build_output_paths

SCHEMA_VERSION = 1
METRICS_SCHEMA_VERSION = 3
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

_ARTIFACT_PATH_ATTR: dict[str, str] = {
    "raw.md": "raw_markdown",
    "document.md": "clean_markdown",
    "document.enriched.md": "enriched_markdown",
    "document.jsonl": "document_jsonl",
    "metrics.json": "metrics_json",
    "removed_content.jsonl": "removed_content_jsonl",
    "run.log": "run_log",
    "native": "native_dir",
}

_TEXT_READABLE: frozenset[str] = frozenset({"raw.md", "document.md", "document.enriched.md", "run.log"})

_ARTIFACT_OUTPUT_KEY: dict[str, str] = {
    "raw.md": "raw_markdown",
    "document.md": "clean_markdown",
    "document.enriched.md": "enriched_markdown",
    "document.jsonl": "document_jsonl",
    "removed_content.jsonl": "removed_content_jsonl",
    "run.log": "run_log",
    "metrics.json": "metrics_json",
}

_ARTIFACT_BYTES_KEY: dict[str, str] = {
    "raw.md": "raw_markdown_bytes",
    "document.md": "clean_markdown_bytes",
    "document.enriched.md": "enriched_markdown_bytes",
    "document.jsonl": "document_jsonl_bytes",
    "removed_content.jsonl": "removed_content_jsonl_bytes",
}


def make_check(name: str, status: str, detail: str = "") -> dict:
    """Build a single check record.

    Args:
        name: Short identifier for the check.
        status: One of ``"pass"``, ``"warn"``, or ``"fail"``.
        detail: Optional human-readable explanation appended when non-empty.

    Returns:
        Dict with keys ``name`` and ``status``, plus ``detail`` when provided.
    """
    check: dict = {"name": name, "status": status}
    if detail:
        check["detail"] = detail
    return check


def make_result(
    *,
    parser: str,
    profile: str,
    document: str,
    checks: list[dict],
) -> dict:
    """Build a validation result dict from a list of check records.

    Args:
        parser: Parser identifier.
        profile: Profile identifier.
        document: Document basename (including extension).
        checks: List of check dicts produced by ``make_check``.

    Returns:
        Dict with ``schema_version``, ``parser``, ``profile``, ``document``,
        ``ok`` (``True`` when no check failed), and ``checks``.
    """
    ok = not any(c["status"] == "fail" for c in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "parser": parser,
        "profile": profile,
        "document": document,
        "ok": ok,
        "checks": checks,
    }


def _has_meaningful_text(content: str) -> bool:
    """Return ``True`` when *content* contains alphanumeric text outside HTML comments."""
    return any(character.isalnum() for character in _HTML_COMMENT_RE.sub("", content))


def _inventory_content_expectation(inventory: dict | None) -> bool:
    """Return the content-expected boolean from a source inventory dict.

    Args:
        inventory: Parsed source-inventory JSON dict, or ``None``.

    Returns:
        ``True`` when the inventory indicates text or image content exists,
        ``False`` when the inventory is absent or proves the PDF is empty.
    """
    if not inventory:
        return False
    return inventory_requires_content(inventory)[0]


def validate_post_execution(
    *,
    output_root: Path,
    parser: str,
    profile: str,
    document_path: Path,
    expected_sha256: str,
    artifact_policy: ArtifactPolicy,
    source_inventory_path: Path | None,
) -> dict:
    """Validate all selected artifacts after a completed parser run.

    Checks that each artifact file exists, is readable UTF-8, and (for text
    artifacts that are expected to carry content) actually contains
    alphanumeric text.  Also validates ``metrics.json`` structure and
    ``document.jsonl`` record integrity.

    Args:
        output_root: Root directory of benchmark outputs.
        parser: Parser identifier.
        profile: Profile identifier.
        document_path: Path to the source PDF (used for its ``stem`` and
            ``name``).
        expected_sha256: SHA-256 hex digest of the source PDF for provenance
            checks.
        artifact_policy: Which artifacts were selected for this run.
        source_inventory_path: Path to the pre-computed source-inventory JSON,
            or ``None`` to skip inventory checks.

    Returns:
        Validation result dict (see ``make_result``).
    """
    checks: list[dict] = []
    paths = build_output_paths(output_root, parser, document_path.stem, profile, create=False)
    doc_name = document_path.name

    source_pages: int | None = None
    source_inventory: dict | None = None
    if source_inventory_path is not None:
        source_pages, source_inventory = _check_source_inventory(
            source_inventory_path, doc_name, expected_sha256, checks
        )

    # §3.1: inventory is authoritative — derive content_expected from it when available
    inventory_content_expected: bool | None = None
    if source_inventory is not None:
        inventory_content_expected = _inventory_content_expectation(source_inventory)

    metrics: dict | None = None
    if artifact_policy.includes("metrics.json"):
        metrics = _load_and_check_metrics(
            paths.metrics_json, parser, profile, doc_name, document_path.stem,
            expected_sha256, artifact_policy, source_pages, paths, checks,
        )

    # §3.1: if inventory requires content, metrics must not claim content_expected=False
    if metrics is not None and inventory_content_expected is True:
        cv = metrics.get("content_validation") or {}
        for md_artifact in ("raw.md", "document.md", "document.enriched.md"):
            if not artifact_policy.includes(md_artifact):
                continue
            entry = cv.get(md_artifact, {})
            metrics_ce = entry.get("content_expected")
            if not bool(metrics_ce):
                checks.append(make_check(
                    f"inventory vs metrics content_expected ({md_artifact})",
                    "fail",
                    f"inventory requires content but metrics content_validation."
                    f"{md_artifact}.content_expected={metrics_ce!r}",
                ))

    for artifact in artifact_policy.as_list():
        if artifact == "metrics.json":
            continue
        artifact_path = getattr(paths, _ARTIFACT_PATH_ATTR[artifact])
        check_name = f"artifact {artifact}"
        if artifact == "native":
            checks.extend(_validate_native_dir(artifact_path, check_name, parser=parser, profile=profile))
            continue
        if artifact == "document.jsonl":
            jsonl_block = (
                (metrics.get("artifacts") or {}).get("document_jsonl", {})
                if metrics else {}
            )
            jsonl_present = jsonl_block.get("present", True)  # conservative if no metrics
            if not jsonl_present:
                checks.append(make_check(check_name, "pass"))
                continue
        if not artifact_path.exists() or not artifact_path.is_file():
            checks.append(make_check(check_name, "fail", "file not found"))
            continue
        if artifact in _TEXT_READABLE:
            try:
                content = artifact_path.read_text(encoding="utf-8")
                if artifact == "raw.md" and "<!-- derived:start" in content:
                    checks.append(make_check(check_name, "fail",
                        "raw.md contains derived:start marker — contamination detected"))
                else:
                    content_entry = (
                        (metrics.get("content_validation") or {}).get(artifact, {})
                        if metrics else {}
                    )
                    # §3.1: inventory is authoritative; fall back to metrics, then False
                    if artifact in {
                        "raw.md",
                        "document.md",
                        "document.enriched.md",
                    }:
                        if inventory_content_expected is not None:
                            expected = inventory_content_expected
                        else:
                            expected = bool(
                                content_entry.get(
                                    "content_expected",
                                    False,
                                )
                            )
                    else:
                        expected = bool(
                            content_entry.get(
                                "content_expected",
                                False,
                            )
                        )
                    if expected and not _has_meaningful_text(content):
                        checks.append(make_check(
                            check_name,
                            "fail",
                            "content expected but artifact is empty, comment-only, or separator-only",
                        ))
                    else:
                        checks.append(make_check(check_name, "pass"))
            except (OSError, UnicodeDecodeError) as exc:
                checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
        elif artifact == "document.jsonl":
            _validate_document_jsonl(artifact_path, parser, profile, doc_name, metrics, checks)
        elif artifact == "removed_content.jsonl":
            _validate_removed_content_jsonl(artifact_path, metrics, checks)
        else:
            checks.append(make_check(check_name, "pass"))

    return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)


def validate_resume_candidate(
    *,
    output_root: Path,
    parser: str,
    profile: str,
    document_path: Path,
    expected_sha256: str,
    requested_artifacts: ArtifactPolicy,
    expected_fingerprint: str | None = None,
) -> dict:
    """Check whether a previous run's output can be reused without re-running.

    Performs a series of checks in strict order; returns early on the first
    failure so downstream checks do not run on corrupt state.  Checks include:

    * Source inventory present, complete, and matching the current SHA-256.
    * ``metrics.json`` present, readable, and matching the current
      parser/profile/document provenance.
    * Saved artifact selection covers every requested artifact.
    * Optional execution fingerprint match to detect stale cached output.
    * Content-expected consistency between the inventory and saved metrics.
    * Each requested artifact file exists and (where recorded) matches its
      registered byte count and SHA-256.

    Args:
        output_root: Root directory of benchmark outputs.
        parser: Parser identifier.
        profile: Profile identifier.
        document_path: Path to the source PDF.
        expected_sha256: SHA-256 hex digest of the source PDF.
        requested_artifacts: Artifacts required for the current run.
        expected_fingerprint: Optional execution fingerprint to compare
            against the saved value.  ``None`` skips fingerprint checking.

    Returns:
        Validation result dict (see ``make_result``).
    """
    checks: list[dict] = []
    paths = build_output_paths(output_root, parser, document_path.stem, profile, create=False)
    doc_name = document_path.name

    # §3.2: load and validate source inventory before approving resume
    inv_path = output_root / "_source_inventory" / f"{document_path.stem}.json"
    source_inventory: dict | None = None
    if not inv_path.is_file():
        checks.append(make_check(
            "source inventory",
            "fail",
            f"not found: {inv_path} — output must not be reused without a valid inventory",
        ))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    try:
        source_inventory = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        checks.append(make_check("source inventory", "fail", f"unreadable: {exc}"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    if source_inventory.get("file") != doc_name:
        checks.append(make_check("source inventory", "fail",
            f"file mismatch: expected {doc_name!r}, got {source_inventory.get('file')!r}"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    if source_inventory.get("sha256") != expected_sha256:
        checks.append(make_check("source inventory", "fail",
            "sha256 mismatch — inventory was built from a different file version"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    inv_pages = source_inventory.get("pages")
    if not isinstance(inv_pages, int) or inv_pages <= 0:
        checks.append(make_check("source inventory", "fail",
            f"pages must be a positive integer, got {inv_pages!r}"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    inv_complete = bool(source_inventory.get("measurement_complete", False))
    if not inv_complete:
        checks.append(make_check("source inventory", "fail",
            "measurement_complete=false — inventory is incomplete; output must not be reused"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    checks.append(make_check("source inventory", "pass"))

    if not paths.metrics_json.is_file():
        checks.append(make_check("metrics.json", "fail", "file not found — cannot verify provenance"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    try:
        metrics = json.loads(paths.metrics_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        checks.append(make_check("metrics.json", "fail", f"unreadable: {exc}"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    schema_ver = metrics.get("benchmark", {}).get("schema_version")
    if schema_ver != METRICS_SCHEMA_VERSION:
        checks.append(make_check("metrics schema_version", "fail",
            f"expected {METRICS_SCHEMA_VERSION}, got {schema_ver!r}"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    run_block = metrics.get("run", {})
    doc_block = metrics.get("document", {})

    if run_block.get("parser") != parser:
        checks.append(make_check("metrics run.parser", "fail",
            f"expected {parser!r}, got {run_block.get('parser')!r}"))
    if run_block.get("profile") != profile:
        checks.append(make_check("metrics run.profile", "fail",
            f"expected {profile!r}, got {run_block.get('profile')!r}"))
    if doc_block.get("file") != doc_name:
        checks.append(make_check("metrics document.file", "fail",
            f"expected {doc_name!r}, got {doc_block.get('file')!r}"))
    if doc_block.get("id") != document_path.stem:
        checks.append(make_check("metrics document.id", "fail",
            f"expected {document_path.stem!r}, got {doc_block.get('id')!r}"))
    if doc_block.get("sha256") != expected_sha256:
        checks.append(make_check("metrics document.sha256", "fail", "sha256 mismatch"))

    if any(c["status"] == "fail" for c in checks):
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    saved_sel_raw = run_block.get("artifact_selection", [])
    if not isinstance(saved_sel_raw, list):
        checks.append(make_check("metrics run.artifact_selection", "fail",
            f"must be a list, got {type(saved_sel_raw).__name__}"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    saved_sel = set(saved_sel_raw)
    requested_sel = set(requested_artifacts.as_list())
    if not requested_sel.issubset(saved_sel):
        missing = sorted(requested_sel - saved_sel)
        checks.append(make_check("artifact coverage", "fail",
            f"saved {sorted(saved_sel)} doesn't cover requested {sorted(requested_sel)}: missing {missing}"))
        return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    # §4: execution_fingerprint — reject stale output if adapter/config/code changed
    if expected_fingerprint is not None:
        saved_fp = metrics.get("execution_fingerprint")
        if saved_fp is None:
            checks.append(make_check(
                "execution_fingerprint",
                "warn",
                "fingerprint not present in saved metrics — produced by older orchestrator version",
            ))
        elif saved_fp != expected_fingerprint:
            checks.append(make_check(
                "execution_fingerprint",
                "fail",
                "fingerprint mismatch — adapter, config, or git state changed; output must be regenerated",
            ))
            return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    # §3.2: if inventory requires content, saved metrics must not say content_expected=False
    if source_inventory is not None:
        inventory_ce = _inventory_content_expectation(source_inventory)
        if inventory_ce:
            cv_block = metrics.get("content_validation") or {}
            for md_artifact in ("raw.md", "document.md", "document.enriched.md"):
                if not requested_artifacts.includes(md_artifact):
                    continue
                entry = cv_block.get(md_artifact, {})
                metrics_ce = entry.get("content_expected")
                if not bool(metrics_ce):
                    checks.append(make_check(
                        f"inventory vs metrics content_expected ({md_artifact})",
                        "fail",
                        f"inventory requires content but saved metrics says "
                        f"content_expected={metrics_ce!r} — output must be regenerated",
                    ))
                    return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)

    out_block = metrics.get("output", {})
    expected_pages = doc_block.get("pages")
    for artifact in requested_artifacts.as_list():
        check_name = f"artifact {artifact}"
        path_attr = _ARTIFACT_PATH_ATTR.get(artifact)
        if path_attr is None:
            continue
        artifact_path = getattr(paths, path_attr)
        if artifact == "native":
            checks.extend(_validate_native_dir(artifact_path, check_name, parser=parser, profile=profile))
            continue
        if artifact == "document.jsonl":
            jsonl_present = (
                metrics.get("artifacts", {}).get("document_jsonl", {}).get("present", True)
            )
            if not jsonl_present:
                checks.append(make_check(check_name, "pass"))
                continue
        if not artifact_path.is_file():
            checks.append(make_check(check_name, "fail", "file not found"))
            continue
        bytes_key = _ARTIFACT_BYTES_KEY.get(artifact)
        if bytes_key is not None:
            registered = out_block.get(bytes_key)
            if registered is not None:
                actual = artifact_path.stat().st_size
                if actual != registered:
                    checks.append(make_check(check_name, "fail",
                        f"size mismatch: registered {registered}, actual {actual}"))
                    continue
        if artifact == "document.jsonl" and isinstance(expected_pages, int):
            try:
                lines = [ln for ln in artifact_path.read_text(encoding="utf-8").split("\n") if ln.strip()]
                if len(lines) != expected_pages:
                    checks.append(make_check(check_name, "fail",
                        f"truncated: expected {expected_pages} records, got {len(lines)}"))
                    continue
            except (OSError, UnicodeDecodeError) as exc:
                checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
                continue
        content_entry = (metrics.get("content_validation") or {}).get(artifact, {})
        registered_sha = content_entry.get("sha256")
        if registered_sha:
            import hashlib as _hashlib
            actual_sha = _hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if actual_sha != registered_sha:
                checks.append(make_check(
                    check_name, "fail", "sha256 mismatch against content_validation"
                ))
                continue
        if content_entry.get("valid") is False:
            checks.append(make_check(
                check_name, "fail", "saved content_validation marks artifact invalid"
            ))
            continue
        checks.append(make_check(check_name, "pass"))

    return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)


def _check_source_inventory(
    inv_path: Path,
    doc_name: str,
    expected_sha256: str,
    checks: list[dict],
) -> tuple[int | None, dict | None]:
    """Load and validate a source-inventory JSON file, appending to *checks*.

    Args:
        inv_path: Path to the inventory JSON file.
        doc_name: Expected ``file`` field value (PDF basename).
        expected_sha256: Expected ``sha256`` field value.
        checks: List to which check results are appended in place.

    Returns:
        Tuple of ``(pages, inventory_dict)`` on success, or ``(None, None)``
        / ``(None, partial_dict)`` on failure.
    """
    check_name = "source inventory"
    if not inv_path.is_file():
        checks.append(make_check(check_name, "fail", "file not found"))
        return None, None
    try:
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
        return None, None
    if inv.get("file") != doc_name:
        checks.append(make_check(check_name, "fail",
            f"file mismatch: expected {doc_name!r}, got {inv.get('file')!r}"))
        return None, inv
    if inv.get("sha256") != expected_sha256:
        checks.append(make_check(check_name, "fail", "sha256 mismatch"))
        return None, inv
    pages = inv.get("pages")
    if not isinstance(pages, int) or pages <= 0:
        checks.append(make_check(check_name, "fail",
            f"pages must be a positive integer, got {pages!r}"))
        return None, inv
    if not bool(inv.get("measurement_complete", False)):
        checks.append(make_check(check_name, "fail",
            "measurement_complete is not True — inventory is incomplete"))
        return None, inv
    checks.append(make_check(check_name, "pass"))
    return pages, inv


_VALID_BUNDLE_STATUS = frozenset({"unavailable", "available"})


def _validate_native_dir(
    artifact_path: Path,
    check_name: str,
    *,
    parser: str,
    profile: str,
) -> list[dict]:
    """Validate the native bundle directory against its ``manifest.json``.

    Checks manifest structure, bundle status, declared file sizes and
    SHA-256 digests, and that no unlisted files exist in the bundle.

    Args:
        artifact_path: Path to the ``native/`` directory.
        check_name: Label used in the returned check records.
        parser: Expected ``parser`` value in the manifest.
        profile: Expected ``profile`` value in the manifest.

    Returns:
        List of check dicts (a single ``"pass"`` entry on success, or one
        ``"fail"`` entry describing the first violation).
    """
    checks: list[dict] = []
    if not artifact_path.is_dir():
        checks.append(make_check(check_name, "fail", "directory not found"))
        return checks

    manifest_path = artifact_path / "manifest.json"
    if not manifest_path.is_file():
        checks.append(make_check(check_name, "fail", "manifest.json not found"))
        return checks

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        checks.append(make_check(check_name, "fail", f"manifest.json unreadable: {exc}"))
        return checks

    # schema_version must be exactly 1
    schema_ver = manifest.get("schema_version")
    if schema_ver != 1:
        checks.append(make_check(check_name, "fail",
            f"manifest.json: schema_version must be 1, got {schema_ver!r}"))
        return checks

    bundle_status = manifest.get("bundle_status")
    if bundle_status not in _VALID_BUNDLE_STATUS:
        checks.append(make_check(check_name, "fail",
            f"manifest.json: bundle_status must be one of {sorted(_VALID_BUNDLE_STATUS)}, "
            f"got {bundle_status!r}"))
        return checks

    if not isinstance(manifest.get("files"), list):
        checks.append(make_check(check_name, "fail",
            "manifest.json: files must be list"))
        return checks

    # unavailable → files must be empty
    if bundle_status == "unavailable" and manifest["files"]:
        checks.append(make_check(check_name, "fail",
            "manifest.json: bundle_status=unavailable requires files=[]"))
        return checks

    # parser and profile must match the job
    manifest_parser = manifest.get("parser")
    if manifest_parser is not None and manifest_parser != parser:
        checks.append(make_check(check_name, "fail",
            f"manifest.json: parser mismatch: expected {parser!r}, got {manifest_parser!r}"))
        return checks

    manifest_profile = manifest.get("profile")
    if manifest_profile is not None and manifest_profile != profile:
        checks.append(make_check(check_name, "fail",
            f"manifest.json: profile mismatch: expected {profile!r}, got {manifest_profile!r}"))
        return checks

    native_root = artifact_path.resolve()
    declared_paths: set[str] = set()
    for i, entry in enumerate(manifest["files"]):
        if not isinstance(entry, dict):
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: not a dict"))
            return checks
        rel = entry.get("path", "")
        rel_path = Path(rel) if rel else None
        if not rel or (rel_path is not None and rel_path.is_absolute()):
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: path must be non-empty relative"))
            return checks
        candidate = (artifact_path / rel).resolve()
        if candidate == native_root or native_root not in candidate.parents:
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: path escapes native/: {rel!r}"))
            return checks
        if not candidate.is_file():
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: declared file missing: {rel!r}"))
            return checks
        normalized_relative = candidate.relative_to(native_root).as_posix()
        if normalized_relative in declared_paths:
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: duplicate path: {rel!r}"))
            return checks
        declared_paths.add(normalized_relative)
        declared_size = entry.get("size_bytes")
        if not isinstance(declared_size, int) or declared_size < 0:
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: size_bytes must be a non-negative integer"))
            return checks
        if candidate.stat().st_size != declared_size:
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: size mismatch for {rel!r}"))
            return checks
        declared_sha256 = entry.get("sha256")
        if not isinstance(declared_sha256, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", declared_sha256
        ):
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: sha256 must contain 64 hexadecimal characters"))
            return checks
        import hashlib as _hashlib
        actual = _hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != declared_sha256.lower():
            checks.append(make_check(check_name, "fail",
                f"manifest.json files[{i}]: sha256 mismatch for {rel!r}"))
            return checks

    actual_paths: set[str] = set()
    for path in artifact_path.rglob("*"):
        if not path.is_file() or path.resolve() == manifest_path.resolve():
            continue
        try:
            relative = path.resolve().relative_to(native_root).as_posix()
        except ValueError:
            checks.append(make_check(check_name, "fail",
                f"native bundle contains a file that resolves outside native/: {path}"))
            return checks
        actual_paths.add(relative)
    unexpected = sorted(actual_paths - declared_paths)
    if unexpected:
        checks.append(make_check(check_name, "fail",
            f"native bundle contains unlisted files: {unexpected[:10]}"))
        return checks

    checks.append(make_check(check_name, "pass"))
    return checks


def _load_and_check_metrics(
    metrics_path: Path,
    parser: str,
    profile: str,
    doc_name: str,
    doc_stem: str,
    expected_sha256: str,
    artifact_policy: ArtifactPolicy,
    source_pages: int | None,
    paths,
    checks: list[dict],
) -> dict | None:
    """Load ``metrics.json``, validate its structure, and append check results.

    Verifies schema version, required blocks, provenance fields, artifact
    selection, byte-count consistency, and content-validation entries.

    Args:
        metrics_path: Path to ``metrics.json``.
        parser: Expected parser identifier.
        profile: Expected profile identifier.
        doc_name: Expected document basename.
        doc_stem: Expected document stem (without extension).
        expected_sha256: Expected SHA-256 digest of the source PDF.
        artifact_policy: Artifact selection for this run.
        source_pages: Page count from the source inventory, or ``None``.
        paths: Resolved ``BenchmarkPaths`` for this run.
        checks: List to which check records are appended in place.

    Returns:
        Parsed metrics dict on success, or ``None`` if the file could not be
        loaded.
    """
    if not metrics_path.is_file():
        checks.append(make_check("artifact metrics.json", "fail", "file not found"))
        return None
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        checks.append(make_check("artifact metrics.json", "fail", f"unreadable: {exc}"))
        return None

    for block in ("benchmark", "run", "document", "processing", "output"):
        if block not in metrics:
            checks.append(make_check(f"metrics {block} block", "fail", "missing"))

    # Schema 3 requires artifacts, quality_eligibility, and content validation.
    artifacts_block = metrics.get("artifacts")
    if not isinstance(artifacts_block, dict):
        checks.append(make_check("metrics artifacts block", "fail",
            "missing or not a dict (required in schema v3)"))
    else:
        for sub in ("raw", "clean", "enriched"):
            if not isinstance(artifacts_block.get(sub), dict):
                checks.append(make_check(f"metrics artifacts.{sub}", "fail",
                    "missing or not a dict"))
        # coherence: selected enriched output is always materialized, even when
        # it is a documented fallback to document.md/native Markdown.
        enriched_sub = artifacts_block.get("enriched") or {}
        enriched_present = enriched_sub.get("present")
        out_block_pre = metrics.get("output", {})
        enriched_output_path = out_block_pre.get("enriched_markdown")
        if enriched_present is True and enriched_output_path is None:
            checks.append(make_check("metrics artifacts.enriched coherence", "fail",
                "artifacts.enriched.present=true but output.enriched_markdown=null"))
        elif enriched_present is False and enriched_output_path is not None:
            checks.append(make_check("metrics artifacts.enriched coherence", "fail",
                "artifacts.enriched.present=false but output.enriched_markdown is set"))
        if artifact_policy.includes("document.enriched.md") and enriched_present is not True:
            checks.append(make_check(
                "metrics artifacts.enriched present",
                "fail",
                "selected document.enriched.md must always be present",
            ))

    content_validation = metrics.get("content_validation")
    if not isinstance(content_validation, dict):
        checks.append(make_check(
            "metrics content_validation block", "fail", "missing or not a dict"
        ))
    else:
        for artifact in artifact_policy.as_list():
            if artifact not in _ARTIFACT_BYTES_KEY:
                continue
            entry = content_validation.get(artifact)
            if not isinstance(entry, dict):
                checks.append(make_check(
                    f"metrics content_validation.{artifact}", "fail", "missing or not a dict"
                ))
                continue
            for field in (
                "exists", "utf8_valid", "bytes", "has_alphanumeric",
                "content_expected", "expectation_reason", "valid",
            ):
                if field not in entry:
                    checks.append(make_check(
                        f"metrics content_validation.{artifact}.{field}", "fail", "missing"
                    ))
            if entry.get("valid") is False:
                checks.append(make_check(
                    f"metrics content_validation.{artifact}",
                    "fail",
                    "artifact content does not satisfy its declared expectation",
                ))

    quality_block = metrics.get("quality_eligibility")
    if not isinstance(quality_block, dict):
        checks.append(make_check("metrics quality_eligibility block", "fail",
            "missing or not a dict (required in schema v3)"))
    else:
        for field in ("source_text", "page_mapping_complete", "formal_quality_eligible"):
            if field not in quality_block:
                checks.append(make_check(f"metrics quality_eligibility.{field}", "fail",
                    "missing"))

    bm = metrics.get("benchmark", {})
    if bm.get("schema_version") != METRICS_SCHEMA_VERSION:
        checks.append(make_check("metrics schema_version", "fail",
            f"expected {METRICS_SCHEMA_VERSION}, got {bm.get('schema_version')!r}"))

    run_block = metrics.get("run", {})
    doc_block = metrics.get("document", {})
    proc_block = metrics.get("processing", {})
    out_block = metrics.get("output", {})

    if run_block.get("parser") != parser:
        checks.append(make_check("metrics run.parser", "fail",
            f"expected {parser!r}, got {run_block.get('parser')!r}"))
    if run_block.get("profile") != profile:
        checks.append(make_check("metrics run.profile", "fail",
            f"expected {profile!r}, got {run_block.get('profile')!r}"))
    if doc_block.get("file") != doc_name:
        checks.append(make_check("metrics document.file", "fail",
            f"expected {doc_name!r}, got {doc_block.get('file')!r}"))
    if doc_block.get("id") != doc_stem:
        checks.append(make_check("metrics document.id", "fail",
            f"expected {doc_stem!r}, got {doc_block.get('id')!r}"))
    if doc_block.get("sha256") != expected_sha256:
        checks.append(make_check("metrics document.sha256", "fail", "sha256 mismatch"))

    pages_val = doc_block.get("pages")
    if not isinstance(pages_val, int) or pages_val <= 0:
        checks.append(make_check("metrics document.pages", "fail",
            f"must be positive int, got {pages_val!r}"))
    elif source_pages is not None and pages_val != source_pages:
        checks.append(make_check("metrics document.pages", "fail",
            f"mismatch with source inventory: metrics={pages_val}, inventory={source_pages}"))

    saved_sel_raw = run_block.get("artifact_selection")
    if not isinstance(saved_sel_raw, list):
        checks.append(make_check("metrics run.artifact_selection", "fail",
            f"must be a list, got {type(saved_sel_raw).__name__ if saved_sel_raw is not None else 'None'}"))
    else:
        expected_sel = set(artifact_policy.as_list())
        saved_sel = set(saved_sel_raw)
        if saved_sel != expected_sel:
            checks.append(make_check("metrics run.artifact_selection", "fail",
                f"expected {sorted(expected_sel)}, got {sorted(saved_sel)}"))
        out_sel = out_block.get("selected_artifacts")
        if out_sel is not None and set(out_sel) != saved_sel:
            checks.append(make_check("metrics output.selected_artifacts", "fail",
                "diverges from run.artifact_selection"))

    for artifact, out_key in _ARTIFACT_OUTPUT_KEY.items():
        if artifact not in artifact_policy.selected:
            if out_block.get(out_key) is not None:
                checks.append(make_check(f"metrics output.{out_key}", "warn",
                    "field set for artifact not in selection"))
        else:
            if artifact == "document.jsonl":
                jsonl_present = (
                    metrics.get("artifacts", {}).get("document_jsonl", {}).get("present", True)
                )
                if not jsonl_present:
                    continue
            val = out_block.get(out_key)
            if not isinstance(val, str) or not val:
                checks.append(make_check(f"metrics output.{out_key}", "fail",
                    "must be non-empty string for selected artifact"))

    for artifact, bytes_key in _ARTIFACT_BYTES_KEY.items():
        if artifact not in artifact_policy.selected:
            if out_block.get(bytes_key) is not None:
                checks.append(make_check(f"metrics output.{bytes_key}", "warn",
                    "field set for artifact not in selection"))
        else:
            path_attr = _ARTIFACT_PATH_ATTR[artifact]
            artifact_path = getattr(paths, path_attr)
            registered = out_block.get(bytes_key)
            if registered is not None and artifact_path.is_file():
                actual = artifact_path.stat().st_size
                if actual != registered:
                    checks.append(make_check(f"artifact size {artifact}", "fail",
                        f"registered {registered} bytes, actual {actual} bytes"))

    _check_processing(proc_block, doc_block, checks)

    checks.append(make_check("artifact metrics.json", "pass"))
    return metrics


def _check_processing(proc_block: dict, doc_block: dict, checks: list[dict]) -> None:
    """Validate the ``processing`` block of a metrics dict.

    Checks numeric type constraints, range consistency
    (``failed_pages == pages_total - pages_processed``), and emits warnings
    for partial processing or empty output pages.

    Args:
        proc_block: The ``metrics["processing"]`` dict.
        doc_block: The ``metrics["document"]`` dict (used for page-count
            cross-check).
        checks: List to which check records are appended in place.
    """
    pt = proc_block.get("pages_total")
    pp = proc_block.get("pages_processed")
    fp = proc_block.get("failed_pages")
    eop = proc_block.get("empty_output_pages")
    ec = proc_block.get("errors_count")

    types_ok = True
    for field, val in [("pages_total", pt), ("pages_processed", pp),
                       ("failed_pages", fp), ("empty_output_pages", eop)]:
        if not isinstance(val, int):
            checks.append(make_check(f"metrics processing.{field}", "fail",
                f"must be int, got {type(val).__name__ if val is not None else 'missing'}"))
            types_ok = False

    if types_ok:
        if pt <= 0:
            checks.append(make_check("metrics processing.pages_total", "fail",
                f"must be > 0, got {pt}"))
        elif pp < 0 or pp > pt:
            checks.append(make_check("metrics processing.pages_processed", "fail",
                f"{pp} not in [0, {pt}]"))
        elif fp < 0 or fp > pt:
            checks.append(make_check("metrics processing.failed_pages", "fail",
                f"{fp} out of range"))
        elif eop < 0 or eop > pt:
            checks.append(make_check("metrics processing.empty_output_pages", "fail",
                f"{eop} out of range"))
        else:
            expected_fp = max(pt - pp, 0)
            if fp != expected_fp:
                checks.append(make_check("metrics processing.failed_pages", "fail",
                    f"expected max(pages_total-pages_processed,0)={expected_fp}, got {fp}"))
            else:
                if pp < pt:
                    checks.append(make_check("metrics processing.pages_processed", "warn",
                        f"{pp}/{pt} pages reported as processed"))
            if eop > 0:
                checks.append(make_check("metrics processing.empty_output_pages", "warn",
                    f"{eop} page(s) have empty normalized output"))
            doc_pages = doc_block.get("pages")
            if isinstance(doc_pages, int) and pt != doc_pages:
                checks.append(make_check("metrics processing.pages_total", "fail",
                    f"does not match document.pages: {pt} != {doc_pages}"))

    if ec is None:
        checks.append(make_check("metrics processing.errors_count", "fail", "field missing"))
    elif not isinstance(ec, int):
        checks.append(make_check("metrics processing.errors_count", "fail",
            f"must be int, got {type(ec).__name__}"))
    elif ec > 0:
        checks.append(make_check("metrics processing.errors_count", "fail",
            f"{ec} error(s) reported by adapter"))


def _validate_document_jsonl(
    path: Path,
    parser: str,
    profile: str,
    doc_name: str,
    metrics: dict | None,
    checks: list[dict],
) -> None:
    """Validate the structure and provenance of ``document.jsonl``.

    Checks that every line is valid JSON, the record count matches
    ``metrics.document.pages``, page numbers form a contiguous sequence
    starting at 1, and each record's ``source_file``, ``parser``, and
    ``profile`` fields match the current run.

    Args:
        path: Path to the ``document.jsonl`` file.
        parser: Expected parser identifier.
        profile: Expected profile identifier.
        doc_name: Expected ``source_file`` value in each record.
        metrics: Parsed metrics dict for cross-checking, or ``None``.
        checks: List to which check records are appended in place.
    """
    check_name = "artifact document.jsonl"
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
        return

    lines = [ln for ln in content.split("\n") if ln.strip()]
    records = []
    for i, line in enumerate(lines, 1):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            checks.append(make_check(check_name, "fail", f"invalid JSON on line {i}"))
            return

    if metrics is not None:
        expected_count = metrics.get("document", {}).get("pages")
        if isinstance(expected_count, int) and len(records) != expected_count:
            checks.append(make_check(check_name, "fail",
                f"expected {expected_count} records (one per page), got {len(records)}"))
            return

    if records:
        page_numbers = [rec.get("page_number") for rec in records]
        try:
            sorted_pages = sorted(page_numbers)
            if sorted_pages != list(range(1, len(records) + 1)):
                checks.append(make_check(check_name, "fail",
                    f"page_number sequence invalid: {sorted_pages}"))
                return
        except TypeError:
            checks.append(make_check(check_name, "fail", "page_number values not sortable"))
            return

    for i, rec in enumerate(records, 1):
        if rec.get("source_file") != doc_name:
            checks.append(make_check(check_name, "fail",
                f"record {i}: source_file mismatch: expected {doc_name!r}, got {rec.get('source_file')!r}"))
            return
        if rec.get("parser") != parser:
            checks.append(make_check(check_name, "fail",
                f"record {i}: parser mismatch: expected {parser!r}, got {rec.get('parser')!r}"))
            return
        if rec.get("profile") != profile:
            checks.append(make_check(check_name, "fail",
                f"record {i}: profile mismatch: expected {profile!r}, got {rec.get('profile')!r}"))
            return

    checks.append(make_check(check_name, "pass"))


def _validate_removed_content_jsonl(
    path: Path,
    metrics: dict | None,
    checks: list[dict],
) -> None:
    """Validate that ``removed_content.jsonl`` is well-formed JSONL.

    Each non-blank line must be valid JSON.  When metrics are available, the
    record count is cross-checked against
    ``metrics.normalization.removed_records``.

    Args:
        path: Path to the ``removed_content.jsonl`` file.
        metrics: Parsed metrics dict for cross-checking, or ``None``.
        checks: List to which check records are appended in place.
    """
    check_name = "artifact removed_content.jsonl"
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
        return

    lines = [ln for ln in content.split("\n") if ln.strip()]
    for i, line in enumerate(lines, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError:
            checks.append(make_check(check_name, "fail", f"invalid JSON on line {i}"))
            return

    if metrics is not None:
        expected = metrics.get("normalization", {}).get("removed_records")
        if isinstance(expected, int) and len(lines) != expected:
            checks.append(make_check(check_name, "fail",
                f"expected {expected} records (from metrics.normalization.removed_records), got {len(lines)}"))
            return

    checks.append(make_check(check_name, "pass"))

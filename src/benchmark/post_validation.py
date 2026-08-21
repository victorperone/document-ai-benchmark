from __future__ import annotations

import json
from pathlib import Path

from src.benchmark.artifact_policy import ArtifactPolicy
from src.benchmark.paths import build_output_paths

SCHEMA_VERSION = 1
METRICS_SCHEMA_VERSION = 2

_ARTIFACT_PATH_ATTR: dict[str, str] = {
    "raw.md": "raw_markdown",
    "document.md": "clean_markdown",
    "document.jsonl": "document_jsonl",
    "metrics.json": "metrics_json",
    "removed_content.jsonl": "removed_content_jsonl",
    "run.log": "run_log",
}

_TEXT_READABLE: frozenset[str] = frozenset({"raw.md", "document.md", "run.log"})

_ARTIFACT_OUTPUT_KEY: dict[str, str] = {
    "raw.md": "raw_markdown",
    "document.md": "clean_markdown",
    "document.jsonl": "document_jsonl",
    "removed_content.jsonl": "removed_content_jsonl",
    "run.log": "run_log",
    "metrics.json": "metrics_json",
}

_ARTIFACT_BYTES_KEY: dict[str, str] = {
    "raw.md": "raw_markdown_bytes",
    "document.md": "clean_markdown_bytes",
    "document.jsonl": "document_jsonl_bytes",
    "removed_content.jsonl": "removed_content_jsonl_bytes",
}


def make_check(name: str, status: str, detail: str = "") -> dict:
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
    ok = not any(c["status"] == "fail" for c in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "parser": parser,
        "profile": profile,
        "document": document,
        "ok": ok,
        "checks": checks,
    }


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
    checks: list[dict] = []
    paths = build_output_paths(output_root, parser, document_path.stem, profile, create=False)
    doc_name = document_path.name

    source_pages: int | None = None
    if source_inventory_path is not None:
        source_pages = _check_source_inventory(
            source_inventory_path, doc_name, expected_sha256, checks
        )

    metrics: dict | None = None
    if artifact_policy.includes("metrics.json"):
        metrics = _load_and_check_metrics(
            paths.metrics_json, parser, profile, doc_name, document_path.stem,
            expected_sha256, artifact_policy, source_pages, paths, checks,
        )

    for artifact in artifact_policy.as_list():
        if artifact == "metrics.json":
            continue
        artifact_path = getattr(paths, _ARTIFACT_PATH_ATTR[artifact])
        check_name = f"artifact {artifact}"
        if not artifact_path.exists() or not artifact_path.is_file():
            checks.append(make_check(check_name, "fail", "file not found"))
            continue
        if artifact in _TEXT_READABLE:
            try:
                artifact_path.read_text(encoding="utf-8")
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
) -> dict:
    checks: list[dict] = []
    paths = build_output_paths(output_root, parser, document_path.stem, profile, create=False)
    doc_name = document_path.name

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

    out_block = metrics.get("output", {})
    expected_pages = doc_block.get("pages")
    for artifact in requested_artifacts.as_list():
        check_name = f"artifact {artifact}"
        path_attr = _ARTIFACT_PATH_ATTR.get(artifact)
        if path_attr is None:
            continue
        artifact_path = getattr(paths, path_attr)
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
                lines = [ln for ln in artifact_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if len(lines) != expected_pages:
                    checks.append(make_check(check_name, "fail",
                        f"truncated: expected {expected_pages} records, got {len(lines)}"))
                    continue
            except (OSError, UnicodeDecodeError) as exc:
                checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
                continue
        checks.append(make_check(check_name, "pass"))

    return make_result(parser=parser, profile=profile, document=doc_name, checks=checks)


def _check_source_inventory(
    inv_path: Path,
    doc_name: str,
    expected_sha256: str,
    checks: list[dict],
) -> int | None:
    check_name = "source inventory"
    if not inv_path.is_file():
        checks.append(make_check(check_name, "fail", "file not found"))
        return None
    try:
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
        return None
    if inv.get("file") != doc_name:
        checks.append(make_check(check_name, "fail",
            f"file mismatch: expected {doc_name!r}, got {inv.get('file')!r}"))
        return None
    if inv.get("sha256") != expected_sha256:
        checks.append(make_check(check_name, "fail", "sha256 mismatch"))
        return None
    pages = inv.get("pages")
    if not isinstance(pages, int) or pages <= 0:
        checks.append(make_check(check_name, "fail",
            f"pages must be a positive integer, got {pages!r}"))
        return None
    checks.append(make_check(check_name, "pass"))
    return pages


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
    check_name = "artifact document.jsonl"
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
        return

    lines = [ln for ln in content.splitlines() if ln.strip()]
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
    check_name = "artifact removed_content.jsonl"
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        checks.append(make_check(check_name, "fail", f"unreadable: {exc}"))
        return

    lines = [ln for ln in content.splitlines() if ln.strip()]
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

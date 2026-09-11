"""Metrics discovery and loading helpers for benchmark summary scripts.

Scans the output directory tree for ``metrics.json`` files, validates their
provenance against their filesystem path, and provides helpers for loading
per-parser/profile datasets and asserting that all datasets share the same
document set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class SummaryInputError(RuntimeError):
    """Raised when a metrics file is malformed or inconsistent with its path."""


@dataclass
class MetricsRecord:
    """A single discovered ``metrics.json`` with its parsed content.

    Attributes:
        path: Absolute path to the ``metrics.json`` file.
        parser: Parser identifier (from the directory structure).
        profile: Profile identifier (from the directory structure).
        document: Document basename including extension (from the JSON).
        document_stem: Document basename without extension.
        data: Parsed metrics dict.
    """

    path: Path
    parser: str
    profile: str
    document: str
    document_stem: str
    data: dict


def discover_metrics(
    output_root: Path,
    *,
    parser: str | None = None,
    profile: str | None = None,
) -> list[MetricsRecord]:
    """Discover and validate all ``metrics.json`` files under *output_root*.

    Walks the expected ``<parser>/<document>/<profile>/metrics.json``
    directory structure, reads each file, and cross-checks the JSON
    ``run.parser``, ``run.profile``, and ``document.file`` fields against the
    path components.

    Args:
        output_root: Root of the benchmark output tree.
        parser: When provided, only metrics for this parser are returned.
        profile: When provided, only metrics for this profile are returned.

    Returns:
        Sorted list of ``MetricsRecord`` instances.

    Raises:
        SummaryInputError: If a file contains invalid JSON, or if any JSON
            field is inconsistent with the directory path.
    """
    if parser is not None and profile is not None:
        pattern = f"{parser}/*/{profile}/metrics.json"
    elif parser is not None:
        pattern = f"{parser}/*/*/metrics.json"
    elif profile is not None:
        pattern = f"*/*/{profile}/metrics.json"
    else:
        pattern = "*/*/*/metrics.json"

    records: list[MetricsRecord] = []

    for metrics_path in sorted(output_root.glob(pattern)):
        parts = metrics_path.relative_to(output_root).parts
        if len(parts) != 4:
            continue

        path_parser, path_doc_stem, path_profile, _ = parts

        try:
            data = json.loads(
                metrics_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise SummaryInputError(
                f"Invalid JSON in {metrics_path}: {exc}"
            )

        try:
            json_parser = data["run"]["parser"]
            json_profile = data["run"]["profile"]
            json_file = data["document"]["file"]
        except KeyError as exc:
            raise SummaryInputError(
                f"Missing required field {exc} in {metrics_path}"
            )

        if json_parser != path_parser:
            raise SummaryInputError(
                f"Metrics parser mismatch:\n"
                f"path says {path_parser!r}, "
                f"JSON says {json_parser!r}:\n"
                f"{metrics_path}"
            )

        if json_profile != path_profile:
            raise SummaryInputError(
                f"Metrics profile mismatch:\n"
                f"path says {path_profile!r}, "
                f"JSON says {json_profile!r}:\n"
                f"{metrics_path}"
            )

        json_doc_stem = Path(json_file).stem
        if json_doc_stem != path_doc_stem:
            raise SummaryInputError(
                f"Metrics document mismatch:\n"
                f"path says {path_doc_stem!r}, "
                f"JSON says {json_doc_stem!r}:\n"
                f"{metrics_path}"
            )

        records.append(
            MetricsRecord(
                path=metrics_path,
                parser=path_parser,
                profile=path_profile,
                document=json_file,
                document_stem=path_doc_stem,
                data=data,
            )
        )

    return records


def load_metrics_by_document(
    output_root: Path,
    parser: str,
    profile: str,
) -> dict[str, dict]:
    """Return a mapping of document basename to metrics dict for one run.

    Args:
        output_root: Root of the benchmark output tree.
        parser: Parser identifier to filter by.
        profile: Profile identifier to filter by.

    Returns:
        Dict mapping ``document`` (basename with extension) to the parsed
        metrics dict.

    Raises:
        SummaryInputError: If any file is invalid, or if the same document
            appears more than once under the same parser/profile.
    """
    records = discover_metrics(
        output_root,
        parser=parser,
        profile=profile,
    )

    result: dict[str, dict] = {}
    for rec in records:
        if rec.document in result:
            raise SummaryInputError(
                f"Duplicate result for "
                f"{parser}/{profile}/{rec.document}"
            )
        result[rec.document] = rec.data

    return result


def require_same_documents(
    datasets: Mapping[str, Mapping[str, object]],
) -> list[str]:
    """Assert that all datasets cover exactly the same set of documents.

    Used before cross-parser comparisons to ensure every dataset has a result
    for every document.

    Args:
        datasets: Mapping of dataset name (e.g. ``"pymupdf/default"``) to an
            inner mapping whose keys are document basenames.

    Returns:
        Sorted list of all document names in the union.

    Raises:
        SummaryInputError: If any dataset is missing documents that appear in
            another dataset.
    """
    names = list(datasets.keys())
    if not names:
        return []

    all_doc_sets = {
        name: set(docs)
        for name, docs in datasets.items()
    }

    union = set.union(*all_doc_sets.values())

    errors: list[str] = []
    for name, docs in all_doc_sets.items():
        absent = union - docs
        if absent:
            errors.append(
                f"  {name} is missing: "
                + str(sorted(absent))
            )

    if errors:
        raise SummaryInputError(
            "Document sets differ across datasets:\n"
            + "\n".join(errors)
        )

    return sorted(union)

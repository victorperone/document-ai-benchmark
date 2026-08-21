from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class SummaryInputError(RuntimeError):
    pass


@dataclass
class MetricsRecord:
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

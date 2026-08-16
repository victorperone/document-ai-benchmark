from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from src.evaluation.ocr_quality import (  # noqa: E402
    evaluate_ocr_text,
)


GROUND_TRUTH = (
    PROJECT_ROOT
    / "outputs"
    / "_fixtures"
    / "ocr_regression"
    / "ground_truth.json"
)

OUTPUT_ROOT = (
    PROJECT_ROOT
    / "outputs"
    / "_runtime_feature_test"
    / "orientation_baseline"
    / "pymupdf"
)

PROFILE = (
    "ocr_auto_rapidtess_150"
)

FIXTURES = (
    "scan_landscape_upright.pdf",
    "scan_metadata_rotation_90.pdf",
    "scan_pixels_90.pdf",
    "scan_pixels_180.pdf",
    "scan_pixels_270.pdf",
)


def require(
    mapping: dict[str, Any],
    key: str,
    context: str,
) -> Any:
    if key not in mapping:
        raise RuntimeError(
            f"Missing {context}.{key}. "
            f"Available: "
            f"{sorted(mapping.keys())}"
        )

    return mapping[key]


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(
            f"Missing file: {path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def load_jsonl(
    path: Path,
) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(
            f"Missing file: {path}"
        )

    return [
        json.loads(line)
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]


def percent(
    value: float | None,
) -> str:
    if value is None:
        return "N/A"

    return (
        f"{value * 100:.2f}%"
    )


def main() -> None:
    ground = load_json(
        GROUND_TRUTH
    )

    fixtures = require(
        ground,
        "fixtures",
        "ground_truth",
    )

    print("=" * 118)

    print(
        f"{'FIXTURE':<35}"
        f"{'PDF ROT':>9}"
        f"{'CER':>10}"
        f"{'WER':>10}"
        f"{'ACCENT':>10}"
        f"{'NUMERIC':>10}"
        f"{'CRITICAL':>11}"
        f"{'ID':>9}"
    )

    print("=" * 118)

    results: dict[
        str,
        Any,
    ] = {}

    for filename in FIXTURES:
        if filename not in fixtures:
            raise RuntimeError(
                f"Ground-truth fixture "
                f"missing: {filename}"
            )

        fixture = fixtures[
            filename
        ]

        pages = require(
            fixture,
            "pages",
            filename,
        )

        if len(pages) != 1:
            raise RuntimeError(
                f"{filename}: expected one "
                "ground-truth page."
            )

        truth_page = pages[0]

        expected_lines = require(
            truth_page,
            "expected_lines",
            filename,
        )

        reference = "\n".join(
            str(value)
            for value
            in expected_lines
        )

        stem = Path(
            filename
        ).stem

        profile_dir = (
            OUTPUT_ROOT
            / stem
            / PROFILE
        )

        records = load_jsonl(
            profile_dir
            / "document.jsonl"
        )

        if len(records) != 1:
            raise RuntimeError(
                f"{filename}: expected one "
                "document.jsonl record, found "
                f"{len(records)}."
            )

        record = records[0]

        hypothesis = str(
            require(
                record,
                "raw_markdown",
                "document.jsonl",
            )
        )

        quality = evaluate_ocr_text(
            reference=reference,
            hypothesis=hypothesis,
        )

        validation = require(
            fixture,
            "validation",
            filename,
        )

        rotations = require(
            validation,
            "page_rotations",
            f"{filename}.validation",
        )

        pdf_rotation = (
            rotations[0]
            if rotations
            else None
        )

        results[
            filename
        ] = quality

        print(
            f"{filename:<35}"
            f"{str(pdf_rotation):>9}"
            f"{percent(quality['cer']['rate']):>10}"
            f"{percent(quality['wer']['rate']):>10}"
            f"{percent(quality['accented_token_recall']['recall']):>10}"
            f"{percent(quality['numeric_token_recall']['recall']):>10}"
            f"{percent(quality['critical_term_recall']['recall']):>11}"
            f"{percent(quality['regression_id_recall']['recall']):>9}"
        )

    print("=" * 118)

    output = (
        OUTPUT_ROOT
        / "orientation_quality_summary.json"
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            results,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "Quality JSON:",
        output,
    )

    print()
    print(
        "Lower CER/WER is better."
    )

    print(
        "Higher recall is better."
    )


if __name__ == "__main__":
    main()

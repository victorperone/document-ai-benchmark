from __future__ import annotations

import argparse
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


DEFAULT_GROUND_TRUTH = (
    PROJECT_ROOT
    / "outputs"
    / "_fixtures"
    / "ocr_regression"
    / "ground_truth.json"
)

DEFAULT_RESULTS_ROOT = (
    PROJECT_ROOT
    / "outputs"
    / "_runtime_feature_test"
    / "dpi_ablation"
    / "pymupdf"
    / "scan_quality_3"
)

DEFAULT_FIXTURE = (
    "scan_quality_3.pdf"
)

DEFAULT_PROFILES = (
    "ocr_auto_rapidtess_150",
    "ocr_auto_rapidtess_200",
    "ocr_auto_rapidtess_300",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare PyMuPDF OCR quality and runtime "
            "across OCR DPI profiles."
        )
    )

    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GROUND_TRUTH,
    )

    parser.add_argument(
        "--results-root",
        type=Path,
        default=DEFAULT_RESULTS_ROOT,
    )

    parser.add_argument(
        "--fixture",
        default=DEFAULT_FIXTURE,
    )

    parser.add_argument(
        "--profiles",
        nargs="+",
        default=list(
            DEFAULT_PROFILES
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )

    return parser.parse_args()


def require(
    mapping: dict[str, Any],
    key: str,
    context: str,
) -> Any:
    if key not in mapping:
        raise RuntimeError(
            f"Required field "
            f"{context}.{key} is missing. "
            f"Available keys: "
            f"{sorted(mapping.keys())}"
        )

    return mapping[key]


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Required file not found: {path}"
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
        raise FileNotFoundError(
            f"Required file not found: {path}"
        )

    return [
        json.loads(line)
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]


def build_reference_pages(
    ground_truth: dict[str, Any],
    fixture_name: str,
) -> dict[int, str]:
    fixtures = require(
        ground_truth,
        "fixtures",
        "ground_truth",
    )

    if fixture_name not in fixtures:
        raise RuntimeError(
            f"Fixture {fixture_name!r} "
            "not present in ground truth. "
            f"Available fixtures: "
            f"{sorted(fixtures.keys())}"
        )

    fixture = fixtures[
        fixture_name
    ]

    pages = require(
        fixture,
        "pages",
        f"fixtures.{fixture_name}",
    )

    result: dict[
        int,
        str
    ] = {}

    for page in pages:
        page_number = int(
            require(
                page,
                "page_number",
                "ground_truth.page",
            )
        )

        expected_lines = require(
            page,
            "expected_lines",
            "ground_truth.page",
        )

        if not isinstance(
            expected_lines,
            list,
        ):
            raise RuntimeError(
                "expected_lines must be a list."
            )

        result[
            page_number
        ] = "\n".join(
            str(line)
            for line
            in expected_lines
        )

    return result


def build_hypothesis_pages(
    records: list[
        dict[str, Any]
    ],
) -> dict[int, str]:
    result: dict[
        int,
        str
    ] = {}

    for record in records:
        page_number = int(
            require(
                record,
                "page_number",
                "document.jsonl",
            )
        )

        raw_markdown = str(
            require(
                record,
                "raw_markdown",
                "document.jsonl",
            )
        )

        if page_number in result:
            raise RuntimeError(
                f"Duplicate page number "
                f"{page_number} in document.jsonl."
            )

        result[
            page_number
        ] = raw_markdown

    return result


def combine_pages(
    pages: dict[int, str],
) -> str:
    return "\n".join(
        pages[
            page_number
        ]
        for page_number
        in sorted(
            pages
        )
    )


def percent(
    value: float | None,
) -> str:
    if value is None:
        return "N/A"

    return (
        f"{value * 100:.2f}%"
    )


def main() -> None:
    args = parse_args()

    ground_truth = load_json(
        args.ground_truth
    )

    reference_pages = (
        build_reference_pages(
            ground_truth,
            args.fixture,
        )
    )

    expected_page_numbers = set(
        reference_pages.keys()
    )

    summary: dict[
        str,
        Any,
    ] = {
        "schema_version": 1,
        "fixture": args.fixture,
        "ground_truth": str(
            args.ground_truth
        ),
        "profiles": {},
    }

    for profile in args.profiles:
        profile_dir = (
            args.results_root
            / profile
        )

        metrics = load_json(
            profile_dir
            / "metrics.json"
        )

        document_records = (
            load_jsonl(
                profile_dir
                / "document.jsonl"
            )
        )

        hypothesis_pages = (
            build_hypothesis_pages(
                document_records
            )
        )

        actual_page_numbers = set(
            hypothesis_pages.keys()
        )

        if (
            actual_page_numbers
            != expected_page_numbers
        ):
            raise RuntimeError(
                f"{profile}: page mismatch. "
                f"Expected "
                f"{sorted(expected_page_numbers)}, "
                f"found "
                f"{sorted(actual_page_numbers)}."
            )

        reference_text = (
            combine_pages(
                reference_pages
            )
        )

        hypothesis_text = (
            combine_pages(
                hypothesis_pages
            )
        )

        quality = (
            evaluate_ocr_text(
                reference=reference_text,
                hypothesis=hypothesis_text,
            )
        )

        per_page: dict[
            str,
            Any,
        ] = {}

        for page_number in sorted(
            expected_page_numbers
        ):
            per_page[
                str(page_number)
            ] = evaluate_ocr_text(
                reference=(
                    reference_pages[
                        page_number
                    ]
                ),
                hypothesis=(
                    hypothesis_pages[
                        page_number
                    ]
                ),
            )

        run = require(
            metrics,
            "run",
            "metrics",
        )

        config = require(
            run,
            "resolved_config",
            "metrics.run",
        )

        processing = require(
            metrics,
            "processing",
            "metrics",
        )

        resources = require(
            metrics,
            "resources",
            "metrics",
        )

        tokens = require(
            metrics,
            "tokens",
            "metrics",
        )

        reference_tokens = require(
            tokens,
            "reference",
            "metrics.tokens",
        )

        ocr = require(
            processing,
            "ocr",
            "metrics.processing",
        )

        requested_pages = require(
            ocr,
            "requested_page_numbers",
            "metrics.processing.ocr",
        )

        failed_ocr = require(
            ocr,
            "failed_ocr_pages",
            "metrics.processing.ocr",
        )

        summary[
            "profiles"
        ][profile] = {
            "dpi": require(
                config,
                "ocr_dpi",
                "resolved_config",
            ),

            "performance": {
                "extraction_seconds": (
                    require(
                        processing,
                        "extraction_seconds",
                        "processing",
                    )
                ),

                "pipeline_seconds": (
                    require(
                        processing,
                        "pipeline_seconds",
                        "processing",
                    )
                ),

                "process_cpu_time_seconds": (
                    require(
                        resources,
                        "process_cpu_time_seconds",
                        "resources",
                    )
                ),

                "peak_rss_mb": (
                    require(
                        resources,
                        "peak_rss_mb",
                        "resources",
                    )
                ),

                "clean_markdown_tokens": (
                    require(
                        reference_tokens,
                        "clean_markdown_tokens",
                        "tokens.reference",
                    )
                ),
            },

            "ocr_execution": {
                "requested_page_numbers": (
                    requested_pages
                ),

                "requested_pages": len(
                    requested_pages
                ),

                "failed_ocr_pages": (
                    failed_ocr
                ),
            },

            "quality": quality,
            "per_page": per_page,
        }

    output_path = (
        args.output
        if args.output is not None
        else (
            args.results_root
            / "ocr_quality_summary.json"
        )
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print("=" * 132)

    print(
        f"{'PROFILE':<29}"
        f"{'DPI':>6}"
        f"{'EXTRACT':>10}"
        f"{'RAM MB':>10}"
        f"{'CER':>10}"
        f"{'WER':>10}"
        f"{'ACCENT':>10}"
        f"{'NUMERIC':>10}"
        f"{'CURRENCY':>11}"
        f"{'CRITICAL':>11}"
        f"{'ID':>9}"
    )

    print("=" * 132)

    for profile in args.profiles:
        result = (
            summary[
                "profiles"
            ][profile]
        )

        performance = (
            result["performance"]
        )

        quality = (
            result["quality"]
        )

        print(
            f"{profile:<29}"
            f"{result['dpi']:>6}"
            f"{performance['extraction_seconds']:>10.3f}"
            f"{performance['peak_rss_mb']:>10.1f}"
            f"{percent(quality['cer']['rate']):>10}"
            f"{percent(quality['wer']['rate']):>10}"
            f"{percent(quality['accented_token_recall']['recall']):>10}"
            f"{percent(quality['numeric_token_recall']['recall']):>10}"
            f"{percent(quality['currency_value_recall']['recall']):>11}"
            f"{percent(quality['critical_term_recall']['recall']):>11}"
            f"{percent(quality['regression_id_recall']['recall']):>9}"
        )

    print("=" * 132)

    print()
    print(
        "Quality JSON:",
        output_path,
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

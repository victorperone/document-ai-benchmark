from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.summary_io import (  # noqa: E402
    SummaryInputError,
    load_metrics_by_document,
)

PARSER_NAME = "mineru"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build MinerU per-profile benchmark summary."
    )

    p.add_argument(
        "--profile",
        required=True,
        metavar="PROFILE",
        help="Profile name (e.g. txt, auto, ocr).",
    )

    p.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "outputs",
        metavar="DIR",
        help="Root of parser outputs. Default: <repo>/outputs.",
    )

    p.add_argument(
        "--metrics-root",
        type=Path,
        default=ROOT / "metrics",
        metavar="DIR",
        help="Root for summary outputs. Default: <repo>/metrics.",
    )

    return p.parse_args()


def load_results(
    output_root: Path,
    profile: str,
) -> list[dict]:
    raw = load_metrics_by_document(
        output_root,
        PARSER_NAME,
        profile,
    )

    results = []
    for data in raw.values():
        parser_output = data["content_elements"]["parser_output"]

        results.append(
            {
                "document": data["document"]["file"],
                "profile": profile,
                "pages": data["document"]["pages"],
                "input_mb": data["document"]["input_size_mb"],
                "markdown_mb": data["output"]["clean_markdown_mb"],
                "tokens": (
                    data["tokens"]["reference"]["clean_markdown_tokens"]
                ),
                "tokens_per_page": (
                    data["tokens"]["reference"]["clean_tokens_per_page"]
                ),
                "extraction_seconds": (
                    data["processing"]["extraction_seconds"]
                ),
                "pipeline_seconds": (
                    data["processing"]["pipeline_seconds"]
                ),
                "pages_per_second": (
                    data["processing"]["extraction_pages_per_second"]
                ),
                "average_cpu_percent": (
                    data["resources"][
                        "average_cpu_system_capacity_percent"
                    ]
                ),
                "peak_cpu_percent": (
                    data["resources"][
                        "peak_cpu_system_capacity_percent"
                    ]
                ),
                "peak_ram_mb": data["resources"]["peak_rss_mb"],
                # CSV column "tables" reads tables_detected from parser_output.
                "tables": parser_output["tables_detected"],
                # CSV column "pictures" reads images_detected (v2 schema name).
                "pictures": parser_output["images_detected"],
                # charts_detected is None in the MinerU adapter; preserve None.
                # Do not convert to 0 — None means "not measured", not "zero charts".
                "charts": parser_output["charts_detected"],
                "size_ratio": (
                    data["output"]["input_to_clean_markdown_size_ratio"]
                ),
            }
        )

    results.sort(
        key=lambda item: (item["pages"], item["document"])
    )

    return results


def write_csv(
    results: list[dict],
    csv_path: Path,
) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(results[0].keys()),
        )
        writer.writeheader()
        writer.writerows(results)


def write_markdown(
    results: list[dict],
    profile: str,
    markdown_path: Path,
) -> None:
    lines = [
        "# MinerU Benchmark Summary",
        "",
        f"Profile: `{profile}`",
        "",
        "Pipeline backend.",
        "",
        "| Document | Pages | Input MB | Markdown MB | Tokens | Tokens/Page | Extraction s | Pipeline s | Pages/s | Avg CPU % | Peak CPU % | Peak RAM MB | Tables | Pictures | Charts | Size Ratio |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for item in results:
        charts_cell = (
            str(item["charts"])
            if item["charts"] is not None
            else "N/A"
        )

        lines.append(
            "| "
            f"{item['document']} | "
            f"{item['pages']} | "
            f"{item['input_mb']} | "
            f"{item['markdown_mb']} | "
            f"{item['tokens']} | "
            f"{item['tokens_per_page']} | "
            f"{item['extraction_seconds']} | "
            f"{item['pipeline_seconds']} | "
            f"{item['pages_per_second']} | "
            f"{item['average_cpu_percent']} | "
            f"{item['peak_cpu_percent']} | "
            f"{item['peak_ram_mb']} | "
            f"{item['tables']} | "
            f"{item['pictures']} | "
            f"{charts_cell} | "
            f"{item['size_ratio']} |"
        )

    markdown_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    try:
        results = load_results(args.output_root, args.profile)
    except SummaryInputError as exc:
        raise SystemExit(str(exc))

    if not results:
        raise SystemExit(
            f"No metrics found for "
            f"{PARSER_NAME}/{args.profile} "
            f"under {args.output_root}"
        )

    summary_dir = args.metrics_root / PARSER_NAME / args.profile
    summary_dir.mkdir(parents=True, exist_ok=True)

    csv_path = summary_dir / "summary.csv"
    markdown_path = summary_dir / "summary.md"

    write_csv(results, csv_path)
    write_markdown(results, args.profile, markdown_path)

    print(f"Documents found: {len(results)}")
    print(f"CSV:      {csv_path}")
    print(f"Markdown: {markdown_path}")


if __name__ == "__main__":
    main()

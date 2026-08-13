from __future__ import annotations

import csv
import json
from pathlib import Path


OUTPUT_ROOT = Path("/outputs/docling")
METRICS_ROOT = Path("/metrics")

CSV_PATH = METRICS_ROOT / "docling_summary.csv"
MARKDOWN_PATH = METRICS_ROOT / "docling_summary.md"


def load_results() -> list[dict]:
    results = []

    for metrics_path in sorted(
        OUTPUT_ROOT.glob("*/metrics.json")
    ):
        data = json.loads(
            metrics_path.read_text(encoding="utf-8")
        )

        results.append(
            {
                "document": data["document"]["file"],
                "pages": data["document"]["pages"],
                "input_mb": data["document"]["input_size_mb"],
                "markdown_mb": data["output"]["markdown_size_mb"],
                "tokens": data["tokens"]["full_markdown_tokens"],
                "tokens_per_page": data["tokens"]["tokens_per_page"],
                "extraction_seconds": data["processing"]["extraction_seconds"],
                "pipeline_seconds": data["processing"]["pipeline_seconds"],
                "pages_per_second": data["processing"][
                    "extraction_pages_per_second"
                ],
                "average_cpu_percent": data["resources"][
                    "average_cpu_system_capacity_percent"
                ],
                "peak_cpu_percent": data["resources"][
                    "peak_cpu_system_capacity_percent"
                ],
                "peak_ram_mb": data["resources"]["peak_rss_mb"],
                "tables": data["content"]["tables_detected"],
                "pictures": data["content"]["pictures_detected"],
                "size_ratio": data["output"][
                    "input_to_markdown_size_ratio"
                ],
            }
        )

    results.sort(key=lambda item: item["pages"])
    return results


def write_csv(results: list[dict]) -> None:
    if not results:
        return

    with CSV_PATH.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(results[0].keys()),
        )
        writer.writeheader()
        writer.writerows(results)


def write_markdown(results: list[dict]) -> None:
    lines = [
        "# Docling CPU Benchmark Summary",
        "",
        "| Document | Pages | Input MB | Markdown MB | Tokens | Tokens/Page | Extraction s | Pipeline s | Pages/s | Avg CPU % | Peak CPU % | Peak RAM MB | Tables | Pictures | Size Ratio |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for item in results:
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
            f"{item['size_ratio']} |"
        )

    MARKDOWN_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    results = load_results()

    if not results:
        raise SystemExit(
            "No Docling metrics files were found."
        )

    METRICS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_csv(results)
    write_markdown(results)

    print(f"Documents found: {len(results)}")
    print(f"CSV:      {CSV_PATH}")
    print(f"Markdown: {MARKDOWN_PATH}")


if __name__ == "__main__":
    main()

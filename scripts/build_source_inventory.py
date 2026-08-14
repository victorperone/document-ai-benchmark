from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.benchmark.source_inventory import (
    analyze_pdf_source,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build objective source-PDF inventory."
        )
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("/data/raw"),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "/outputs/_source_inventory"
        ),
    )

    parser.add_argument(
        "--only",
        default=None,
        help="Optional exact PDF filename.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pdfs = sorted(
        path
        for path in args.input_dir.glob(
            "*.pdf"
        )
        if path.is_file()
    )

    if args.only is not None:
        pdfs = [
            path
            for path in pdfs
            if path.name == args.only
        ]

    if not pdfs:
        raise SystemExit(
            "No PDF files found."
        )

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        f"Documents found: {len(pdfs)}"
    )

    for index, pdf in enumerate(
        pdfs,
        start=1,
    ):
        print(
            f"[{index}/{len(pdfs)}] "
            f"{pdf.name}"
        )

        result = analyze_pdf_source(
            pdf
        )

        destination = (
            args.output_dir
            / f"{pdf.stem}.json"
        )

        destination.write_text(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        print(
            f"  pages: "
            f"{result['pages']}"
        )

        print(
            f"  native coverage: "
            f"{result['native_text']['page_coverage_ratio']:.2%}"
        )

        print(
            f"  embedded images: "
            f"{result['images']['embedded_image_occurrences']}"
        )

        print(
            f"  output: "
            f"{destination}"
        )


if __name__ == "__main__":
    main()

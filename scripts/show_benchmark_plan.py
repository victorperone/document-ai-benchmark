from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "benchmark_profiles.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show benchmark execution plan without running it."
    )

    parser.add_argument(
        "--suite",
        default="ocr_primary",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = json.loads(
        CONFIG_PATH.read_text(encoding="utf-8")
    )

    benchmark = config["benchmark"]

    input_dir = ROOT / benchmark["input_directory"]
    input_glob = benchmark["input_glob"]

    pdfs = sorted(
        path
        for path in input_dir.glob(input_glob)
        if path.is_file()
    )

    if not pdfs:
        raise SystemExit(
            f"No input files found in {input_dir}"
        )

    suites = config["suites"]

    if args.suite not in suites:
        available = ", ".join(
            sorted(suites)
        )

        raise SystemExit(
            f"Unknown suite: {args.suite}\n"
            f"Available suites: {available}"
        )

    jobs = suites[args.suite]

    print("=" * 78)
    print("DOCUMENT AI BENCHMARK V2 - EXECUTION PLAN")
    print("=" * 78)
    print(
        f"Schema version:      "
        f"{config['schema_version']}"
    )
    print(
        f"Reference tokenizer: "
        f"{benchmark['reference_tokenizer']}"
    )
    print(
        f"Execution mode:      "
        f"{benchmark['execution_mode']}"
    )
    print(f"Suite:               {args.suite}")
    print(f"PDF files:           {len(pdfs)}")
    print(f"Profiles per PDF:    {len(jobs)}")
    print(
        f"Total jobs:          "
        f"{len(pdfs) * len(jobs)}"
    )
    print("=" * 78)

    print()
    print("INPUT FILES")
    print("-" * 78)

    for index, pdf in enumerate(
        pdfs,
        start=1,
    ):
        print(
            f"{index:02d}. {pdf.name}"
        )

    print()
    print("PARSER PROFILES")
    print("-" * 78)

    for index, (
        parser_name,
        profile_name,
    ) in enumerate(
        jobs,
        start=1,
    ):
        profile = (
            config["parsers"]
            [parser_name]
            ["profiles"]
            [profile_name]
        )

        print(
            f"{index:02d}. "
            f"{parser_name:<10} "
            f"{profile_name}"
        )

        print(
            "    "
            + json.dumps(
                profile,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    print()
    print("OUTPUT PLAN")
    print("-" * 78)

    output_root = ROOT / benchmark[
        "output_directory"
    ]

    for pdf in pdfs:
        for parser_name, profile_name in jobs:
            destination = (
                output_root
                / parser_name
                / pdf.stem
                / profile_name
            )

            print(
                destination.relative_to(ROOT)
            )

    print()
    print("=" * 78)
    print("PLAN ONLY - NO DOCUMENTS WERE PROCESSED")
    print("=" * 78)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import Any

import pymupdf

from src.benchmark.process_tree import run_process_tree


DEFAULT_DPI = 150


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect image regions inside a PDF and run "
            "Tesseract OSD on each rendered region."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input PDF path.",
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=(
            "DPI used to render image regions before "
            f"Tesseract OSD. Default: {DEFAULT_DPI}."
        ),
    )

    return parser.parse_args()


def parse_osd_output(
    text: str,
) -> dict[str, Any]:
    """
    Parse the exact text format produced by the installed
    Tesseract OSD command.

    Expected fields observed previously:

        Orientation in degrees
        Rotate
        Orientation confidence
        Script
        Script confidence
    """

    raw_values: dict[str, str] = {}

    for line in text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(
            ":",
            1,
        )

        raw_values[
            key.strip()
        ] = value.strip()

    result: dict[str, Any] = {
        "raw": text,
        "orientation_degrees": None,
        "rotate_degrees": None,
        "orientation_confidence": None,
        "script": None,
        "script_confidence": None,
    }

    if "Orientation in degrees" in raw_values:
        try:
            result[
                "orientation_degrees"
            ] = int(
                raw_values[
                    "Orientation in degrees"
                ]
            )
        except ValueError:
            pass

    if "Rotate" in raw_values:
        try:
            result[
                "rotate_degrees"
            ] = int(
                raw_values["Rotate"]
            )
        except ValueError:
            pass

    if "Orientation confidence" in raw_values:
        try:
            result[
                "orientation_confidence"
            ] = float(
                raw_values[
                    "Orientation confidence"
                ]
            )
        except ValueError:
            pass

    result["script"] = raw_values.get(
        "Script"
    )

    if "Script confidence" in raw_values:
        try:
            result[
                "script_confidence"
            ] = float(
                raw_values[
                    "Script confidence"
                ]
            )
        except ValueError:
            pass

    return result


def run_tesseract_osd(
    image_path: Path,
) -> dict[str, Any]:
    """
    Run Tesseract only in Orientation and Script Detection mode.

    This does NOT perform our final OCR extraction.
    """

    command = [
        "tesseract",
        str(image_path),
        "stdout",
        "--psm",
        "0",
        "-l",
        "osd",
    ]

    completed = run_process_tree(
        command,
        capture_output=True,
        timeout=30,
    )

    result = parse_osd_output(
        completed.stdout
    )

    result["return_code"] = (
        completed.returncode
    )

    result["stderr"] = (
        completed.stderr.strip()
    )

    return result


def get_image_blocks(
    page: pymupdf.Page,
) -> list[dict[str, Any]]:
    """
    Return image blocks exposed by PyMuPDF's dictionary
    representation of the page.

    Block type:
        0 = text
        1 = image
    """

    page_dict = page.get_text(
        "dict"
    )

    blocks = page_dict.get(
        "blocks",
        []
    )

    return [
        block
        for block in blocks
        if block.get("type") == 1
    ]


def main() -> None:
    args = parse_args()

    if not args.input.is_file():
        raise SystemExit(
            "ERROR: input PDF not found: "
            f"{args.input}"
        )

    if args.dpi <= 0:
        raise SystemExit(
            "ERROR: --dpi must be greater than zero."
        )

    document = pymupdf.open(
        args.input
    )

    try:
        print("=" * 112)
        print(
            "IMAGE REGION ORIENTATION PROBE"
        )
        print("=" * 112)

        print(
            "Input:",
            args.input,
        )

        print(
            "Pages:",
            len(document),
        )

        print(
            "OSD render DPI:",
            args.dpi,
        )

        total_image_regions = 0
        successful_osd = 0
        failed_osd = 0

        with tempfile.TemporaryDirectory(
            prefix="document_ai_region_osd_"
        ) as temp_directory:
            temp_dir = Path(
                temp_directory
            )

            for page_number, page in enumerate(
                document,
                start=1,
            ):
                blocks = get_image_blocks(
                    page
                )

                if not blocks:
                    continue

                print()
                print("-" * 112)

                print(
                    f"PAGE {page_number}"
                )

                print(
                    "PDF rotation:",
                    page.rotation,
                )

                print(
                    "Page size:",
                    (
                        round(
                            page.rect.width,
                            2,
                        ),
                        round(
                            page.rect.height,
                            2,
                        ),
                    ),
                )

                print(
                    "Image regions:",
                    len(blocks),
                )

                for image_index, block in enumerate(
                    blocks,
                    start=1,
                ):
                    total_image_regions += 1

                    bbox = block.get(
                        "bbox"
                    )

                    if bbox is None:
                        print()
                        print(
                            f"  IMAGE {image_index}"
                        )
                        print(
                            "    SKIPPED: "
                            "image block has no bbox"
                        )

                        continue

                    rect = pymupdf.Rect(
                        bbox
                    )

                    if rect.is_empty:
                        print()
                        print(
                            f"  IMAGE {image_index}"
                        )
                        print(
                            "    SKIPPED: empty bbox"
                        )

                        continue

                    page_area = (
                        page.rect.width
                        * page.rect.height
                    )

                    region_area = (
                        rect.width
                        * rect.height
                    )

                    area_fraction = (
                        region_area / page_area
                        if page_area > 0
                        else 0.0
                    )

                    try:
                        pixmap = page.get_pixmap(
                            dpi=args.dpi,
                            clip=rect,
                            colorspace=(
                                pymupdf.csGRAY
                            ),
                            alpha=False,
                            annots=False,
                        )

                    except Exception as exc:
                        print()
                        print(
                            f"  IMAGE {image_index}"
                        )

                        print(
                            "    RENDER ERROR:",
                            type(exc).__name__,
                            str(exc),
                        )

                        failed_osd += 1
                        continue

                    image_path = (
                        temp_dir
                        / (
                            f"page_"
                            f"{page_number:03d}_"
                            f"image_"
                            f"{image_index:02d}.png"
                        )
                    )

                    pixmap.save(
                        str(
                            image_path
                        )
                    )

                    osd = run_tesseract_osd(
                        image_path
                    )

                    print()
                    print(
                        f"  IMAGE {image_index}"
                    )

                    print(
                        "    bbox:",
                        tuple(
                            round(
                                float(value),
                                2,
                            )
                            for value in rect
                        ),
                    )

                    print(
                        "    page-area fraction:",
                        f"{area_fraction:.3f}",
                    )

                    print(
                        "    rendered pixels:",
                        (
                            pixmap.width,
                            pixmap.height,
                        ),
                    )

                    print(
                        "    OSD return code:",
                        osd["return_code"],
                    )

                    print(
                        "    orientation:",
                        osd[
                            "orientation_degrees"
                        ],
                    )

                    print(
                        "    rotate:",
                        osd[
                            "rotate_degrees"
                        ],
                    )

                    print(
                        "    orientation confidence:",
                        osd[
                            "orientation_confidence"
                        ],
                    )

                    print(
                        "    script:",
                        osd[
                            "script"
                        ],
                    )

                    print(
                        "    script confidence:",
                        osd[
                            "script_confidence"
                        ],
                    )

                    if osd["stderr"]:
                        print(
                            "    stderr:",
                            osd["stderr"],
                        )

                    if osd["return_code"] == 0:
                        successful_osd += 1
                    else:
                        failed_osd += 1

        print()
        print("=" * 112)
        print("SUMMARY")
        print("=" * 112)

        print(
            "Image regions inspected:",
            total_image_regions,
        )

        print(
            "Successful OSD:",
            successful_osd,
        )

        print(
            "Failed OSD:",
            failed_osd,
        )

        print("=" * 112)

        if total_image_regions == 0:
            raise SystemExit(
                "ERROR: no image regions were found."
            )

        print(
            "Image region orientation probe: OK"
        )

    finally:
        document.close()


if __name__ == "__main__":
    main()

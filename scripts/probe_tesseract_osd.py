from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf


DEFAULT_FIXTURES_DIR = Path(
    "/outputs/_fixtures/ocr_regression"
)

DEFAULT_FILES = (
    "scan_landscape_upright.pdf",
    "scan_metadata_rotation_90.pdf",
    "scan_pixels_90.pdf",
    "scan_pixels_180.pdf",
    "scan_pixels_270.pdf",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe the raw Tesseract OSD behavior "
            "against synthetic orientation fixtures."
        )
    )

    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=DEFAULT_FIXTURES_DIR,
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help=(
            "Resolution used only to render the page "
            "for the OSD probe. Default: 150."
        ),
    )

    parser.add_argument(
        "--files",
        nargs="+",
        default=list(
            DEFAULT_FILES
        ),
    )

    return parser.parse_args()


def run_osd(
    image_path: Path,
) -> subprocess.CompletedProcess[str]:
    command = [
        "tesseract",
        str(image_path),
        "stdout",
        "--psm",
        "0",
        "-l",
        "osd",
    ]

    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> None:
    args = parse_args()

    if args.dpi <= 0:
        raise SystemExit(
            "ERROR: --dpi must be greater than zero."
        )

    tesseract = shutil.which(
        "tesseract"
    )

    if tesseract is None:
        raise SystemExit(
            "ERROR: tesseract executable "
            "was not found."
        )

    print("=" * 88)
    print("TESSERACT OSD PROBE")
    print("=" * 88)

    print(
        "Tesseract:",
        tesseract,
    )

    print(
        "Render DPI:",
        args.dpi,
    )

    print(
        "Fixtures:",
        args.fixtures_dir,
    )

    failures: list[str] = []

    with tempfile.TemporaryDirectory(
        prefix="document_ai_osd_"
    ) as temporary_directory:
        temp_dir = Path(
            temporary_directory
        )

        for filename in args.files:
            pdf_path = (
                args.fixtures_dir
                / filename
            )

            if not pdf_path.is_file():
                raise SystemExit(
                    "ERROR: fixture not found: "
                    f"{pdf_path}"
                )

            document = pymupdf.open(
                pdf_path
            )

            try:
                if len(document) != 1:
                    raise RuntimeError(
                        f"{filename}: expected exactly "
                        f"one page, found "
                        f"{len(document)}."
                    )

                page = document[0]

                pixmap = page.get_pixmap(
                    dpi=args.dpi,
                    colorspace=(
                        pymupdf.csGRAY
                    ),
                    alpha=False,
                    annots=True,
                )

                image_path = (
                    temp_dir
                    / (
                        Path(
                            filename
                        ).stem
                        + ".png"
                    )
                )

                pixmap.save(
                    image_path
                )

                result = run_osd(
                    image_path
                )

                print()
                print("=" * 88)
                print(filename)
                print("=" * 88)

                print(
                    "PDF page.rotation:",
                    page.rotation,
                )

                print(
                    "PDF page.rect:",
                    (
                        round(
                            page.rect.width,
                            3,
                        ),
                        round(
                            page.rect.height,
                            3,
                        ),
                    ),
                )

                print(
                    "Rendered pixmap:",
                    (
                        pixmap.width,
                        pixmap.height,
                    ),
                )

                print(
                    "Return code:",
                    result.returncode,
                )

                print()
                print("--- STDOUT ---")

                stdout = (
                    result.stdout.strip()
                    or "<empty>"
                )

                print(
                    stdout
                )

                print()
                print("--- STDERR ---")

                stderr = (
                    result.stderr.strip()
                    or "<empty>"
                )

                print(
                    stderr
                )

                if result.returncode != 0:
                    failures.append(
                        filename
                    )

            finally:
                document.close()

    print()
    print("=" * 88)

    if failures:
        print(
            "OSD probe completed with "
            "non-zero Tesseract result(s):"
        )

        for filename in failures:
            print(
                " -",
                filename,
            )

        raise SystemExit(
            2
        )

    print(
        "Tesseract OSD probe execution: OK"
    )

    print("=" * 88)


if __name__ == "__main__":
    main()

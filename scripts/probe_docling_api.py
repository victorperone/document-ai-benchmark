from __future__ import annotations

import importlib.metadata
import inspect
import os
import shutil
from typing import Any

import docling.datamodel.pipeline_options as po

from docling.document_converter import (
    DocumentConverter,
)

from docling_core.types.doc.document import (
    DoclingDocument,
)


def package_version(
    package: str,
) -> str | None:
    """
    Return the installed package version.

    None means the package is not installed in the current
    Python environment.
    """
    try:
        return importlib.metadata.version(
            package
        )

    except importlib.metadata.PackageNotFoundError:
        return None


def dump_model(
    value: Any,
) -> Any:
    """
    Convert a Pydantic object to a printable structure when
    possible without depending on a particular Pydantic API.
    """
    if hasattr(
        value,
        "model_dump",
    ):
        try:
            return value.model_dump()
        except Exception:
            pass

    return repr(value)


def print_separator(
    title: str,
) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


print_separator(
    "DOCLING V2 API PROBE"
)

# ---------------------------------------------------------------------
# 1. Installed package versions
# ---------------------------------------------------------------------

print()
print("INSTALLED PACKAGE VERSIONS")
print("-" * 78)

packages = [
    "docling",
    "docling-core",
    "torch",
    "torchvision",
    "transformers",
    "rapidocr",
    "onnxruntime",
    "easyocr",
    "tesserocr",
    "opencv-python",
    "opencv-python-headless",
]

for package in packages:
    print(
        f"{package:<28}",
        package_version(
            package
        ),
    )


# ---------------------------------------------------------------------
# 2. External OCR binaries
# ---------------------------------------------------------------------

print()
print("EXTERNAL OCR BINARIES")
print("-" * 78)

tesseract_path = shutil.which(
    "tesseract"
)

print(
    f"{'tesseract executable':<28}",
    tesseract_path,
)


# ---------------------------------------------------------------------
# 3. Important environment variables
# ---------------------------------------------------------------------

print()
print("RELEVANT ENVIRONMENT VARIABLES")
print("-" * 78)

environment_variables = [
    "DOCLING_DEVICE",
    "DOCLING_NUM_THREADS",
    "DOCLING_INFERENCE_COMPILE_TORCH_MODELS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "HF_HOME",
    "HUGGINGFACE_HUB_CACHE",
    "TRANSFORMERS_CACHE",
]

for name in environment_variables:
    print(
        f"{name:<42}",
        os.environ.get(
            name
        ),
    )


# ---------------------------------------------------------------------
# 4. Verify important Docling symbols
# ---------------------------------------------------------------------

print()
print("PIPELINE API SYMBOLS")
print("-" * 78)

symbols = [
    "PdfPipelineOptions",
    "AcceleratorOptions",
    "AcceleratorDevice",
    "OcrAutoOptions",
    "OcrEngine",
    "OcrMode",
    "RapidOcrOptions",
    "EasyOcrOptions",
    "TesseractOcrOptions",
    "TesseractCliOcrOptions",
    "TableStructureOptions",
    "TableStructureV2Options",
    "TableFormerMode",
    "PictureDescriptionVlmOptions",
    "smolvlm_picture_description",
]

for name in symbols:
    value = getattr(
        po,
        name,
        None,
    )

    print(
        f"{name:<38}",
        "YES"
        if value is not None
        else "NO",
    )


# ---------------------------------------------------------------------
# 5. PdfPipelineOptions defaults
# ---------------------------------------------------------------------

print_separator(
    "PDF PIPELINE DEFAULTS"
)

PdfPipelineOptions = getattr(
    po,
    "PdfPipelineOptions",
    None,
)

if PdfPipelineOptions is None:
    raise RuntimeError(
        "PdfPipelineOptions is unavailable."
    )

pipeline_options = (
    PdfPipelineOptions()
)

pipeline_fields = [
    "do_ocr",
    "do_table_structure",
    "do_picture_description",
    "do_picture_classification",
    "do_chart_extraction",
    "do_code_enrichment",
    "do_formula_enrichment",
    "force_backend_text",
    "generate_page_images",
    "generate_picture_images",
    "generate_table_images",
    "generate_parsed_pages",
    "images_scale",
    "ocr_options",
    "table_structure_options",
    "picture_description_options",
    "accelerator_options",
    "enable_remote_services",
    "artifacts_path",
]

for name in pipeline_fields:
    if not hasattr(
        pipeline_options,
        name,
    ):
        print(
            f"{name:<36}",
            "<NOT AVAILABLE>",
        )
        continue

    value = getattr(
        pipeline_options,
        name,
    )

    print(
        f"{name:<36}",
        repr(value),
    )


# ---------------------------------------------------------------------
# 6. OCR Auto
# ---------------------------------------------------------------------

print_separator(
    "OCR AUTO OPTIONS"
)

OcrAutoOptions = getattr(
    po,
    "OcrAutoOptions",
    None,
)

if OcrAutoOptions is None:
    print(
        "OcrAutoOptions: NOT AVAILABLE"
    )

else:
    try:
        value = OcrAutoOptions()

        print(
            "class:",
            type(value).__name__,
        )

        print(
            "data:",
            dump_model(value),
        )

    except Exception as exc:
        print(
            "Instantiation error:",
            type(exc).__name__,
            str(exc),
        )


# ---------------------------------------------------------------------
# 7. RapidOCR options
# ---------------------------------------------------------------------

print_separator(
    "RAPIDOCR OPTIONS"
)

RapidOcrOptions = getattr(
    po,
    "RapidOcrOptions",
    None,
)

if RapidOcrOptions is None:
    print(
        "RapidOcrOptions: NOT AVAILABLE"
    )

else:
    try:
        value = RapidOcrOptions()

        print(
            "class:",
            type(value).__name__,
        )

        print(
            "data:",
            dump_model(value),
        )

    except Exception as exc:
        print(
            "Instantiation error:",
            type(exc).__name__,
            str(exc),
        )


# ---------------------------------------------------------------------
# 8. Tesseract CLI options
# ---------------------------------------------------------------------

print_separator(
    "TESSERACT CLI OPTIONS"
)

TesseractCliOcrOptions = getattr(
    po,
    "TesseractCliOcrOptions",
    None,
)

if TesseractCliOcrOptions is None:
    print(
        "TesseractCliOcrOptions: NOT AVAILABLE"
    )

else:
    try:
        value = (
            TesseractCliOcrOptions()
        )

        print(
            "class:",
            type(value).__name__,
        )

        print(
            "data:",
            dump_model(value),
        )

    except Exception as exc:
        print(
            "Instantiation error:",
            type(exc).__name__,
            str(exc),
        )


# ---------------------------------------------------------------------
# 9. Table structure options
# ---------------------------------------------------------------------

print_separator(
    "TABLE STRUCTURE OPTIONS"
)

TableFormerMode = getattr(
    po,
    "TableFormerMode",
    None,
)

if TableFormerMode is None:
    print(
        "TableFormerMode: NOT AVAILABLE"
    )

else:
    print(
        "TableFormerMode values:",
        [
            (
                item.name,
                item.value,
            )
            for item in TableFormerMode
        ],
    )


TableStructureOptions = getattr(
    po,
    "TableStructureOptions",
    None,
)

if TableStructureOptions is None:
    print(
        "TableStructureOptions: "
        "NOT AVAILABLE"
    )

else:
    try:
        value = (
            TableStructureOptions()
        )

        print(
            "default options:",
            dump_model(value),
        )

    except Exception as exc:
        print(
            "Instantiation error:",
            type(exc).__name__,
            str(exc),
        )


# ---------------------------------------------------------------------
# 10. SmolVLM picture description
# ---------------------------------------------------------------------

print_separator(
    "SMOLVLM PICTURE DESCRIPTION"
)

smolvlm = getattr(
    po,
    "smolvlm_picture_description",
    None,
)

if smolvlm is None:
    print(
        "smolvlm_picture_description: "
        "NOT AVAILABLE"
    )

else:
    print(
        "class:",
        type(smolvlm).__name__,
    )

    attributes = [
        "repo_id",
        "prompt",
        "generation_config",
        "scale",
    ]

    for name in attributes:
        if hasattr(
            smolvlm,
            name,
        ):
            print(
                f"{name:<24}",
                repr(
                    getattr(
                        smolvlm,
                        name,
                    )
                ),
            )


# ---------------------------------------------------------------------
# 11. Public function signatures
# ---------------------------------------------------------------------

print_separator(
    "IMPORTANT FUNCTION SIGNATURES"
)

try:
    print(
        "DocumentConverter.convert:"
    )

    print(
        inspect.signature(
            DocumentConverter.convert
        )
    )

except Exception as exc:
    print(
        "Unable to inspect "
        "DocumentConverter.convert:",
        type(exc).__name__,
        str(exc),
    )


print()

try:
    print(
        "DoclingDocument.export_to_markdown:"
    )

    print(
        inspect.signature(
            DoclingDocument
            .export_to_markdown
        )
    )

except Exception as exc:
    print(
        "Unable to inspect "
        "export_to_markdown:",
        type(exc).__name__,
        str(exc),
    )


# ---------------------------------------------------------------------
# 12. Markdown-related methods
# ---------------------------------------------------------------------

print_separator(
    "DOCLING DOCUMENT SERIALIZATION METHODS"
)

serialization_methods = [
    "export_to_markdown",
    "export_to_text",
    "export_to_dict",
    "export_to_html",
    "save_as_markdown",
    "save_as_json",
]

for name in serialization_methods:
    value = getattr(
        DoclingDocument,
        name,
        None,
    )

    print(
        f"{name:<28}",
        "YES"
        if value is not None
        else "NO",
    )


print_separator(
    "DOCLING API PROBE: OK"
)

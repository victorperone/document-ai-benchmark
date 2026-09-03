#!/usr/bin/env python3
"""
Probe script for Unstructured 0.27.1 API.

Run inside the .venvs/unstructured venv before writing the adapter.
Reports exact signatures, element types, and metadata fields actually
present in the installed release.

Usage:
    .venvs\\unstructured\\Scripts\\python.exe scripts\\probe_unstructured_api.py
"""
from __future__ import annotations

import inspect
import platform
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

from src.benchmark.process_tree import run_process_tree

PASS_MARK = "[PASS]"
FAIL_MARK = "[FAIL]"
WARN_MARK = "[WARN]"

_failures: list[str] = []
_warnings: list[str] = []


def _ok(label: str, detail: str = "") -> None:
    suffix = f"  {detail}" if detail else ""
    print(f"  {PASS_MARK} {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    _failures.append(label)
    suffix = f"  {detail}" if detail else ""
    print(f"  {FAIL_MARK} {label}{suffix}")


def _warn(label: str, detail: str = "") -> None:
    _warnings.append(label)
    suffix = f"  {detail}" if detail else ""
    print(f"  {WARN_MARK} {label}{suffix}")


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 1. Versions
# ---------------------------------------------------------------------------

_section("1. Versions")

try:
    import importlib.metadata as _meta
    for pkg in (
        "unstructured",
        "unstructured-inference",
        "onnxruntime",
        "pdfminer.six",
        "unstructured-pytesseract",
    ):
        try:
            v = _meta.version(pkg)
            _ok(pkg, v)
        except _meta.PackageNotFoundError:
            _fail(pkg, "not installed")
except Exception as exc:
    _fail("importlib.metadata", str(exc))

print(f"\n  Python: {sys.version}")
print(f"  Platform: {platform.platform()}")


# ---------------------------------------------------------------------------
# 2. partition_pdf signature
# ---------------------------------------------------------------------------

_section("2. partition_pdf signature")

try:
    from unstructured.partition.pdf import partition_pdf
    _ok("import partition_pdf")

    sig = inspect.signature(partition_pdf)
    params = set(sig.parameters)

    required_params = [
        "filename", "strategy", "infer_table_structure", "languages",
        "detect_language_per_element", "include_page_breaks",
        "hi_res_model_name", "extract_image_block_types",
        "extract_image_block_to_payload", "starting_page_number",
        "extract_forms", "form_extraction_skip_tables", "password",
    ]
    pdfminer_params = [
        "chunking_strategy", "combine_under_n_chars",
    ]
    for p in required_params:
        if p in params:
            _ok(f"param: {p}")
        else:
            _fail(f"param: {p}", "missing from signature")

    # PDFMiner params are optional
    for p in ["line_margin", "char_margin", "line_overlap", "word_margin"]:
        if p in params:
            _ok(f"pdfminer param: {p}")
        else:
            _warn(f"pdfminer param: {p}", "not in signature (may be passed via kwargs)")

    # extract_forms is present in the signature but NOT implemented in pinned 0.27.1:
    # form_extraction.run_form_extraction() raises NotImplementedError unconditionally.
    # Treat its presence as "parameter exists / implementation missing".
    _warn(
        "form extraction implementation",
        "parameter 'extract_forms' exists in partition_pdf() signature but "
        "form_extraction.run_form_extraction() raises NotImplementedError in "
        "unstructured==0.27.1 — do not set extract_forms=True in profiles",
    )

    print(f"\n  Full signature:\n  {sig}")

except Exception as exc:
    _fail("partition_pdf import", str(exc))


# ---------------------------------------------------------------------------
# 3. Element types
# ---------------------------------------------------------------------------

_section("3. Element types")

element_classes = [
    ("unstructured.documents.elements", "Element"),
    ("unstructured.documents.elements", "Title"),
    ("unstructured.documents.elements", "NarrativeText"),
    ("unstructured.documents.elements", "ListItem"),
    ("unstructured.documents.elements", "Table"),
    ("unstructured.documents.elements", "Image"),
    ("unstructured.documents.elements", "Formula"),
    ("unstructured.documents.elements", "Header"),
    ("unstructured.documents.elements", "Footer"),
    ("unstructured.documents.elements", "PageBreak"),
]

for mod_name, cls_name in element_classes:
    try:
        import importlib
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name, None)
        if cls is not None:
            _ok(f"{cls_name}")
        else:
            _fail(f"{cls_name}", f"not found in {mod_name}")
    except Exception as exc:
        _fail(f"{cls_name}", str(exc))

# FormKeysValues may be in a different module
try:
    from unstructured.documents.elements import FormKeysValues  # type: ignore
    _ok("FormKeysValues")
except ImportError:
    _warn("FormKeysValues", "not in unstructured.documents.elements — check alternate location")


# ---------------------------------------------------------------------------
# 4. External tools
# ---------------------------------------------------------------------------

_section("4. External tools")

tess = shutil.which("tesseract")
if tess:
    _ok("tesseract executable", tess)
    try:
        r = run_process_tree(
            ["tesseract", "--version"], capture_output=True, timeout=10
        )
        first = (r.stdout or r.stderr).splitlines()[0]
        _ok("tesseract version", first)
    except Exception as exc:
        _warn("tesseract version", str(exc))

    import os
    tessdata = os.environ.get("TESSDATA_PREFIX", "")
    candidates = [
        tessdata,
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    ]
    tessdata_dir = next((c for c in candidates if c and Path(c).is_dir()), None)
    if tessdata_dir:
        _ok("TESSDATA_PREFIX", tessdata_dir)
        for lang in ("por", "eng"):
            f = Path(tessdata_dir) / f"{lang}.traineddata"
            if f.is_file():
                _ok(f"tessdata {lang}")
            else:
                _fail(f"tessdata {lang}", str(f))
        osd = Path(tessdata_dir) / "osd.traineddata"
        if osd.is_file():
            _ok("tessdata osd")
        else:
            _warn("tessdata osd", "missing — auto-rotation via OSD not guaranteed")
    else:
        _fail("TESSDATA_PREFIX", "tessdata directory not found")
else:
    _fail("tesseract executable", "not in PATH")

for tool in ("pdfinfo", "pdftoppm"):
    path = shutil.which(tool)
    if path:
        _ok(f"poppler: {tool}", path)
    else:
        _fail(f"poppler: {tool}", "not in PATH")


# ---------------------------------------------------------------------------
# 5. YOLOX model
# ---------------------------------------------------------------------------

_section("5. YOLOX model (offline)")

try:
    import os
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from unstructured_inference.models.base import get_model
    model = get_model("yolox")
    _ok("yolox model offline load")
except Exception as exc:
    _warn("yolox model offline load", f"{exc} — run prepare_unstructured_models.ps1 first")


# ---------------------------------------------------------------------------
# 6. Minimal PDF partition
# ---------------------------------------------------------------------------

_section("6. Minimal PDF partition")

_MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj
2 0 obj<</Type /Pages /Kids [3 0 R] /Count 1>>endobj
3 0 obj<</Type /Page /Parent 2 0 R /MediaBox[0 0 612 792]
/Contents 4 0 R /Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 12 Tf 72 720 Td (Hello World) Tj ET
endstream endobj
5 0 obj<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000274 00000 n
0000000369 00000 n
trailer<</Size 6 /Root 1 0 R>>
startxref
450
%%EOF"""

with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
    tmp.write(_MINIMAL_PDF)
    tmp_path = tmp.name

try:
    from unstructured.partition.pdf import partition_pdf as _pp

    for strategy in ("fast",):
        try:
            elements = _pp(filename=tmp_path, strategy=strategy, include_page_breaks=True)
            categories = [type(e).__name__ for e in elements]
            _ok(f"partition strategy={strategy}", f"{len(elements)} elements: {categories}")

            # Inspect first element metadata
            if elements:
                el = elements[0]
                meta = getattr(el, "metadata", None)
                if meta:
                    fields = [
                        "page_number", "coordinates", "parent_id",
                        "detection_class_prob", "text_as_html",
                    ]
                    found = [f for f in fields if hasattr(meta, f)]
                    _ok("element metadata fields", ", ".join(found))
                else:
                    _warn("element metadata", "no metadata attribute")
        except Exception as exc:
            _fail(f"partition strategy={strategy}", str(exc))
finally:
    Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
if _failures:
    print(f"  UNSTRUCTURED API PROBE: FAIL ({len(_failures)} failure(s))")
    for f in _failures:
        print(f"    - {f}")
    sys.exit(1)
else:
    warn_note = f" ({len(_warnings)} warning(s))" if _warnings else ""
    print(f"  UNSTRUCTURED API PROBE: PASS{warn_note}")
print("=" * 60)

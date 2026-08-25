"""
Probe script for liteparse==2.13.0 — run inside the liteparse container.

Confirms the real Python API before adapter implementation. Descartable.

Usage (inside container):
    python /app/scripts/probe_liteparse_api.py /data/raw/batch/<some.pdf>
"""
from __future__ import annotations

import importlib.metadata
import io
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── 1. Package and runtime versions ──────────────────────────────────────────

print("=" * 72)
print("LITEPARSE API PROBE")
print("=" * 72)

try:
    import liteparse
    lp_version = importlib.metadata.version("liteparse")
    print(f"liteparse version   : {lp_version}")
    print(f"liteparse.__file__  : {getattr(liteparse, '__file__', 'N/A')}")
except ImportError as exc:
    print(f"FATAL: cannot import liteparse — {exc}")
    sys.exit(1)

print(f"Python version      : {platform.python_version()}")
print(f"Python impl         : {platform.python_implementation()}")

# ── 2. LiteParse constructor — confirm accepted kwargs ────────────────────────

print("\n─── Constructor probe ──────────────────────────────────────────────────")

CONSTRUCTOR_KWARGS = {
    "ocr_enabled": False,
    "ocr_language": "por+eng",
    "ocr_server_url": None,
    "tessdata_path": None,
    "max_pages": 2000,
    "target_pages": None,
    "extract_screenshots": False,
    "continue_on_page_error": False,
    "dpi": 150,
    "output_format": "markdown",
    "image_mode": "off",
    "extract_images": True,
    "image_output_dir": None,
    "extract_links": False,
    "keep_headers_footers": True,
    "extract_vector_graphics": False,
    "extract_annotations": False,
    "extract_form_fields": False,
    "extract_structure_tree": False,
    "preserve_very_small_text": False,
    "extract_text_metadata": False,
    "extract_document_metadata": True,
    "password": None,
    "quiet": True,
    "num_workers": 4,
}

for kwarg, value in CONSTRUCTOR_KWARGS.items():
    try:
        liteparse.LiteParse(**{kwarg: value})
        print(f"  OK  {kwarg}={value!r}")
    except TypeError as exc:
        print(f"  ERR {kwarg}={value!r} → {exc}")

# Probe kwargs that spec mentioned but may not exist in Python API
SPEC_ONLY_KWARGS = [
    "extract_blocks",
    "emit_word_boxes",
    "include_complexity",
    "skip_diagonal_text",
    "render_form_fields",
    "detect_screenshot_rects",
    "extract_xfa_packets",
    "extract_content_bounds",
]

print("\n─── Spec-only kwargs (may not exist in Python API) ─────────────────────")
for kwarg in SPEC_ONLY_KWARGS:
    try:
        liteparse.LiteParse(**{kwarg: False})
        print(f"  EXISTS  {kwarg}")
    except TypeError:
        print(f"  ABSENT  {kwarg}")

# ── 3. Parse a PDF if provided ────────────────────────────────────────────────

if len(sys.argv) < 2:
    print("\nNo PDF path provided — skipping parse/is_complex probes.")
    print("Usage: python probe_liteparse_api.py <path.pdf>")
    sys.exit(0)

pdf_path = Path(sys.argv[1])
if not pdf_path.is_file():
    print(f"\nFile not found: {pdf_path}")
    sys.exit(1)

print(f"\n─── Parsing: {pdf_path.name} ────────────────────────────────────────────")

import tempfile

with tempfile.TemporaryDirectory() as tmp:
    image_dir = Path(tmp) / "images"
    image_dir.mkdir()

    parser = liteparse.LiteParse(
        ocr_enabled=False,
        output_format="markdown",
        image_mode="off",
        extract_images=True,
        image_output_dir=image_dir,
        extract_links=False,
        keep_headers_footers=True,
        extract_document_metadata=True,
        num_workers=4,
        quiet=True,
        max_pages=2000,
    )

    result = parser.parse(pdf_path)

    print(f"result type         : {type(result).__name__}")
    print(f"result attrs        : {[a for a in dir(result) if not a.startswith('_')]}")
    print(f"result.total_pages  : {getattr(result, 'total_pages', 'ABSENT')}")
    print(f"result.text[:200]   : {str(getattr(result, 'text', ''))[:200]!r}")

    pages = getattr(result, "pages", None)
    if pages:
        print(f"result.pages count  : {len(pages)}")
        p0 = pages[0]
        print(f"page[0] type        : {type(p0).__name__}")
        print(f"page[0] attrs       : {[a for a in dir(p0) if not a.startswith('_')]}")
        text_items = getattr(p0, "text_items", None)
        blocks = getattr(p0, "blocks", None)
        print(f"page[0].text_items  : {'present, count=' + str(len(text_items)) if text_items else 'ABSENT'}")
        print(f"page[0].blocks      : {'present, count=' + str(len(blocks)) if blocks else 'ABSENT'}")
        if text_items:
            ti0 = text_items[0]
            print(f"text_item[0] attrs  : {[a for a in dir(ti0) if not a.startswith('_')]}")
        if blocks:
            b0 = blocks[0]
            print(f"block[0] attrs      : {[a for a in dir(b0) if not a.startswith('_')]}")
            print(f"block[0].kind       : {getattr(b0, 'kind', 'ABSENT')}")
    else:
        print("result.pages        : ABSENT or empty")

    images = getattr(result, "images", None)
    extracted_images = list(image_dir.glob("*")) if image_dir.exists() else []
    print(f"result.images count : {len(images) if images else 0}")
    print(f"files in image_dir  : {len(extracted_images)}")
    if images:
        img0 = images[0]
        print(f"image[0] attrs      : {[a for a in dir(img0) if not a.startswith('_')]}")
        print(f"image[0].name       : {getattr(img0, 'name', 'ABSENT')}")
        print(f"image[0].path       : {getattr(img0, 'path', 'ABSENT')}")
        print(f"image[0].page_num   : {getattr(img0, 'page_num', 'ABSENT')}")

    doc_meta = getattr(result, "doc_meta", None)
    print(f"result.doc_meta     : {'present' if doc_meta else 'ABSENT'}")
    if doc_meta:
        print(f"doc_meta attrs      : {[a for a in dir(doc_meta) if not a.startswith('_')]}")

# ── 4. is_complex() probe ─────────────────────────────────────────────────────

print(f"\n─── is_complex() probe ─────────────────────────────────────────────────")

complexity_parser = liteparse.LiteParse(ocr_enabled=False, quiet=True, max_pages=2000)
try:
    complexity = complexity_parser.is_complex(pdf_path)
    print(f"is_complex() result type : {type(complexity).__name__}")
    if complexity:
        cr0 = complexity[0]
        print(f"page[0] type            : {type(cr0).__name__}")
        print(f"page[0] attrs           : {[a for a in dir(cr0) if not a.startswith('_')]}")
        print(f"page[0].page_number     : {getattr(cr0, 'page_number', 'ABSENT')}")
        print(f"page[0].needs_ocr       : {getattr(cr0, 'needs_ocr', 'ABSENT')}")
        print(f"page[0].reasons         : {getattr(cr0, 'reasons', 'ABSENT')}")
except Exception as exc:
    print(f"is_complex() failed: {exc}")

# ── 5. Tesseract probe ───────────────────────────────────────────────────────

print(f"\n─── Tesseract probe ────────────────────────────────────────────────────")
tess_bin = shutil.which("tesseract")
print(f"tesseract binary    : {tess_bin or 'NOT FOUND'}")
if tess_bin:
    result_v = subprocess.run(
        ["tesseract", "--version"], capture_output=True, text=True
    )
    print(f"tesseract version   : {result_v.stdout.splitlines()[0] if result_v.stdout else result_v.stderr.splitlines()[0]}")
    result_l = subprocess.run(
        ["tesseract", "--list-langs"], capture_output=True, text=True
    )
    langs = result_l.stdout.strip() + result_l.stderr.strip()
    for required_lang in ("eng", "por", "osd"):
        status = "OK" if required_lang in langs else "MISSING"
        print(f"  tessdata {required_lang:<5}  : {status}")

# ── 6. pytesseract OSD probe ─────────────────────────────────────────────────

print(f"\n─── pytesseract OSD probe ──────────────────────────────────────────────")
try:
    import pytesseract
    print(f"pytesseract version : {importlib.metadata.version('pytesseract')}")
    print("OSD (on extracted images, if any):")
    if extracted_images:
        from PIL import Image
        try:
            img = Image.open(extracted_images[0])
            osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
            print(f"  osd result        : {osd}")
        except Exception as exc:
            print(f"  OSD failed        : {exc}")
    else:
        print("  No extracted images available for OSD test.")
except ImportError:
    print("pytesseract not installed")

print("\n" + "=" * 72)
print("PROBE COMPLETE")
print("=" * 72)

#!/usr/bin/env python3
"""
Probe script for Xberg 1.0.14 API.

Run inside the .venvs/xberg venv before writing the adapter.
Reports exact class names, field names, enum values, and async patterns
present in the installed release.

Usage:
    .venvs\\xberg\\Scripts\\python.exe scripts\\probe_xberg_api.py
"""
from __future__ import annotations

import asyncio
import inspect
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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
# 1. Version and native module
# ---------------------------------------------------------------------------

_section("1. Version and native module")

try:
    import xberg
    _ok("import xberg", getattr(xberg, "__version__", "version attr missing"))

    # Locate native .pyd / .so
    xberg_file = getattr(xberg, "__file__", None)
    _ok("xberg module path", str(xberg_file))

    # Check for native extension
    try:
        import xberg._xberg as _native  # type: ignore
        _ok("native extension _xberg", str(getattr(_native, "__file__", "built-in")))
    except ImportError as exc:
        _warn("native extension _xberg", str(exc))

except Exception as exc:
    _fail("import xberg", str(exc))
    print(f"\nXBERG API PROBE: FAIL (cannot import xberg)")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Top-level API — extract / extract_batch
# ---------------------------------------------------------------------------

_section("2. Top-level API")

try:
    extract_fn = getattr(xberg, "extract", None)
    if extract_fn is None:
        _fail("xberg.extract", "not found")
    else:
        _ok("xberg.extract", str(extract_fn))
        if asyncio.iscoroutinefunction(extract_fn):
            _ok("extract is awaitable (async)")
        else:
            _warn("extract is not async", "check if it returns a coroutine another way")
        sig = inspect.signature(extract_fn)
        _ok("extract signature", str(sig))

    batch_fn = getattr(xberg, "extract_batch", None)
    if batch_fn is not None:
        _ok("xberg.extract_batch")
        if asyncio.iscoroutinefunction(batch_fn):
            _ok("extract_batch is awaitable (async)")
    else:
        _warn("xberg.extract_batch", "not found at top level")

except Exception as exc:
    _fail("top-level API", str(exc))


# ---------------------------------------------------------------------------
# 3. Configuration objects
# ---------------------------------------------------------------------------

_section("3. Configuration objects")

config_classes = [
    "ExtractInput",
    "ExtractionConfig",
    "OcrConfig",
    "TesseractConfig",
    "PageConfig",
    "PdfConfig",
    "ContentFilterConfig",
    "LayoutDetectionConfig",
    "ImageExtractionConfig",
]

for cls_name in config_classes:
    cls = getattr(xberg, cls_name, None)
    if cls is not None:
        try:
            sig = inspect.signature(cls)
            _ok(cls_name, f"params: {list(sig.parameters)[:8]}")
        except Exception:
            _ok(cls_name)
    else:
        # Try in sub-modules
        for sub in ("options", "config", "types"):
            try:
                import importlib
                m = importlib.import_module(f"xberg.{sub}")
                cls = getattr(m, cls_name, None)
                if cls:
                    _ok(cls_name, f"found in xberg.{sub}")
                    break
            except ImportError:
                continue
        else:
            _fail(cls_name, "not found in xberg or sub-modules")


# ---------------------------------------------------------------------------
# 4. Enums and constants
# ---------------------------------------------------------------------------

_section("4. Enums and constants")

# Check output format
for attr in ("OutputFormat", "ResultFormat", "OcrStrategy", "ExtractionMethod"):
    obj = getattr(xberg, attr, None)
    if obj is not None:
        values = []
        if hasattr(obj, "__members__"):
            values = list(obj.__members__)
        _ok(attr, f"values: {values}")
    else:
        _warn(attr, "not found at top level")

# Markdown output value
for attr_name in ("OutputFormat", "Format"):
    obj = getattr(xberg, attr_name, None)
    if obj and hasattr(obj, "MARKDOWN"):
        _ok("Markdown output format available", f"{attr_name}.MARKDOWN")
        break
    elif obj and hasattr(obj, "markdown"):
        _ok("Markdown output format available", f"{attr_name}.markdown")
        break


# ---------------------------------------------------------------------------
# 5. Result types
# ---------------------------------------------------------------------------

_section("5. Result types")

result_classes = [
    "ExtractionResult",
    "ExtractedDocument",
    "PageContent",
    "Table",
    "ProcessingWarning",
    "ExtractionSummary",
    "ExtractionErrorItem",
]

for cls_name in result_classes:
    cls = getattr(xberg, cls_name, None)
    if cls is not None:
        _ok(cls_name)
        try:
            sig = inspect.signature(cls)
            _ok(f"  {cls_name} fields", str(list(sig.parameters))[:120])
        except Exception:
            pass
    else:
        _warn(cls_name, "not found at top level — verify correct name in installed release")


# ---------------------------------------------------------------------------
# 6. Tesseract
# ---------------------------------------------------------------------------

_section("6. Tesseract")

tess = shutil.which("tesseract")
if tess:
    _ok("tesseract executable", tess)
    try:
        r = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=10)
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
            (_ok if f.is_file() else _fail)(f"tessdata {lang}", str(f))
        osd = Path(tessdata_dir) / "osd.traineddata"
        if osd.is_file():
            _ok("tessdata osd (required for auto_rotate)")
        else:
            _warn("tessdata osd", "missing — auto_rotate may be limited")
    else:
        _fail("tessdata directory", "not found")
else:
    _fail("tesseract executable", "not in PATH")


# ---------------------------------------------------------------------------
# 7. Minimal extraction
# ---------------------------------------------------------------------------

_section("7. Minimal extraction (fast strategy)")

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


async def _run_extraction() -> None:
    try:
        extract_fn = getattr(xberg, "extract", None)
        if extract_fn is None:
            _fail("extraction", "xberg.extract not found")
            return

        # Build minimal config — try common patterns and fall back gracefully
        try:
            cfg_cls = getattr(xberg, "ExtractionConfig", None)
            input_cls = getattr(xberg, "ExtractInput", None)
            if cfg_cls and input_cls:
                # Minimal: just output format markdown, no OCR
                cfg = cfg_cls()
                inp = input_cls(source=tmp_path)
                result = await extract_fn(inp, cfg)
            else:
                result = await extract_fn(tmp_path)
        except Exception:
            # Fallback: pass path directly
            result = await extract_fn(tmp_path)

        _ok("extraction completed")

        # Inspect result shape
        if result is not None:
            _ok("result type", type(result).__name__)
            for attr in ("documents", "errors", "summary", "output"):
                if hasattr(result, attr):
                    val = getattr(result, attr)
                    _ok(f"result.{attr}", type(val).__name__)

            # Try to find the document content
            docs = getattr(result, "documents", None) or getattr(result, "results", None)
            if docs:
                doc = docs[0] if isinstance(docs, list) else docs
                _ok("document type", type(doc).__name__)
                for field in ("content", "pages", "tables", "metadata", "warnings", "elements"):
                    if hasattr(doc, field):
                        _ok(f"document.{field}", type(getattr(doc, field)).__name__)
                    else:
                        _warn(f"document.{field}", "not found")

    except Exception as exc:
        _fail("extraction", str(exc))


try:
    asyncio.run(_run_extraction())
finally:
    Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
if _failures:
    print(f"  XBERG API PROBE: FAIL ({len(_failures)} failure(s))")
    for f in _failures:
        print(f"    - {f}")
    sys.exit(1)
else:
    warn_note = f" ({len(_warnings)} warning(s))" if _warnings else ""
    print(f"  XBERG API PROBE: PASS{warn_note}")
print("=" * 60)

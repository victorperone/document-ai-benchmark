# Xberg — Windows Host Runtime

## Overview

`xberg` (v1.0.14) runs as a **host-only** parser on Windows Server 2025. It does not use Docker and is isolated in its own Python 3.12 venv at `.venvs/xberg/`. Xberg uses an async Python API (`asyncio.run`) internally — the adapter wraps this with a single `asyncio.run(_extract(...))` call per document.

## Prerequisites

- Python 3.12 installed and on `PATH`
- Tesseract 5.x installed (required only for OCR profiles)
- No network access required at runtime

## Setup

```powershell
# 1. Create venv and install Xberg
.\scripts\windows\setup_xberg.ps1

# 2. Verify all environments
.\scripts\windows\check_envs.ps1
```

## Profiles

| Profile | OCR | Auto-Rotate | Table Extraction | Use Case |
|---|---|---|---|---|
| `native_markdown` | No | No | Yes | Native text PDFs |
| `ocr_auto_tesseract` | Yes (auto) | Yes | Yes | Mixed/scanned PDFs |
| `ocr_force_tesseract` | Yes (forced) | Yes | Yes | Fully scanned documents |
| `ocr_auto_tesseract_repair` | Yes (auto) | Yes | Yes | Low-quality scans (deskew + denoise) |

## Running

```powershell
# Run via run_batch.py (host runtime)
python scripts/run_batch.py `
    --suite xberg_host_native `
    --runtime host `
    --input-dir data/

# Run parser tests
.\scripts\windows\run_host_parser_tests.ps1 -Parser xberg
```

## Environment Variables

These are set automatically by the adapter and the setup script:

| Variable | Value | Purpose |
|---|---|---|
| `HF_HOME` | `models/xberg` | HuggingFace model cache root |
| `HF_HUB_OFFLINE` | `1` | Disable HF Hub network |
| `TRANSFORMERS_OFFLINE` | `1` | Disable Transformers network |
| `DO_NOT_TRACK` | `1` | Disable telemetry |
| `SCARF_NO_ANALYTICS` | `1` | Disable analytics |

## Timing Fields

- `initialization_seconds`: time to import the xberg module
- `extraction_seconds`: time for the `asyncio.run(xberg.extract(...))` call
- `pipeline_seconds`: total wall-clock time

## OCR Tracking Note

Xberg 1.0.14 does not expose per-page OCR tracking through its public API. The `processing.ocr.pages_requested` and `pages_processed` fields are always `null`. This is recorded in the `tracking_note` field of the OCR block.

## Known Limitations

- The async API requires a clean event loop per call. The adapter uses `asyncio.run()` which creates a fresh loop each time — do not nest inside an existing async context.
- Result shape varies by Xberg version. The adapter contains fallback logic to handle multiple possible result structures (`.documents[0].pages`, `.pages`, or full `.content`).
- `ocr_auto_tesseract_repair` requires additional image processing time due to deskew and denoise preprocessing.

## Tessdata Requirements (OCR profiles)

OCR profiles require Tesseract language data files:

| Language | Required for |
|---|---|
| `por.traineddata` | All OCR profiles |
| `eng.traineddata` | All OCR profiles |
| `osd.traineddata` | Profiles with `auto_rotate: true` |

Place `.traineddata` files in a directory pointed to by `TESSDATA_PREFIX`, typically `C:\Program Files\Tesseract-OCR\tessdata\`.

## Troubleshooting

**Error: `preflight_profile` raises on version mismatch**
Ensure v1.0.14 is installed: `pip show xberg`

**Error: native module not loadable**
Run the setup smoke test: `python -c "import xberg._xberg; print('OK')"` from the xberg venv.

**Error: `asyncio` event loop already running**
Do not call the adapter from within an existing `asyncio.run()` context.

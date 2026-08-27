# Unstructured — Windows Host Runtime

## Overview

`unstructured` (v0.27.1) runs as a **host-only** parser on Windows Server 2025. It does not use Docker and is isolated in its own Python 3.12 venv at `.venvs/unstructured/`.

## Prerequisites

- Python 3.12 installed and on `PATH`
- Tesseract 5.x installed (required for OCR profiles and for table structure inference)
- Poppler utilities available (required by `pdfminer` integration)
- No network access required at runtime — models must be pre-downloaded

## Setup

```powershell
# 1. Create venv and install dependencies
.\scripts\windows\setup_unstructured.ps1

# 2. Download required models (one-time)
.\scripts\windows\prepare_unstructured_models.ps1

# 3. Verify all environments
.\scripts\windows\check_envs.ps1
```

## Profiles

| Profile | Strategy | OCR | Table Structure | Use Case |
|---|---|---|---|---|
| `fast_native` | fast | No | No | Native text PDFs, highest speed |
| `auto_detect` | auto | Auto-detected | Yes | Mixed PDFs |
| `hi_res` | hi_res | Yes (Tesseract) | Yes | Scanned documents, high accuracy |
| `ocr_only` | ocr_only | Yes (Tesseract) | Yes | Fully scanned, no text layer |

## Running

```powershell
# Run via run_batch.py (host runtime)
python scripts/run_batch.py `
    --suite unstructured_host_fast `
    --runtime host `
    --input-dir data/

# Run parser tests
.\scripts\windows\run_host_parser_tests.ps1 -Parser unstructured
```

## Environment Variables

These are set automatically by the adapter and the setup script:

| Variable | Value | Purpose |
|---|---|---|
| `HF_HOME` | `models/unstructured` | HuggingFace model cache root |
| `HF_HUB_CACHE` | `models/unstructured/hub` | HuggingFace Hub cache |
| `HF_HUB_OFFLINE` | `1` | Disable HF Hub network |
| `TRANSFORMERS_OFFLINE` | `1` | Disable Transformers network |
| `DO_NOT_TRACK` | `1` | Disable Unstructured telemetry |
| `SCARF_NO_ANALYTICS` | `1` | Disable Scarf analytics |
| `UNSTRUCTURED_DEFAULT_MODEL_NAME` | `yolox` | Default layout model |
| `UNSTRUCTURED_HI_RES_MODEL_NAME` | `yolox` | Hi-res layout model |
| `OMP_THREAD_LIMIT` | `1` | Prevent OpenMP thread explosion |

## Timing Fields

- `initialization_seconds`: time to import `unstructured.partition.pdf`
- `extraction_seconds`: time for `partition_pdf()` call (includes first-call model loading)
- `pipeline_seconds`: total wall-clock time

## Known Limitations

- First call in a process loads ONNX models; subsequent calls are faster. `initialization_seconds` captures import time only.
- Table structure inference requires `hi_res` strategy or explicit `infer_table_structure=True`.
- `hi_res` and `ocr_only` profiles require Tesseract data files (`por.traineddata`, `eng.traineddata`) in `TESSDATA_PREFIX`.

## Troubleshooting

**Error: `preflight_profile` raises on version mismatch**
Ensure v0.27.1 is installed: `pip show unstructured`

**Error: `tesseract` not found**
Add Tesseract to `PATH`, typically `C:\Program Files\Tesseract-OCR\`.

**Error: `TESSDATA_PREFIX` not set**
Set `TESSDATA_PREFIX` to the directory containing `.traineddata` files.

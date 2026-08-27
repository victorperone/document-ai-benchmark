#Requires -Version 5.1
<#
.SYNOPSIS
    Download and verify the YOLOX layout model for Unstructured hi_res strategy.

.DESCRIPTION
    This script runs ONCE before formal benchmark execution.
    It allows network access only for the duration of the download.
    After download, it verifies offline loading and writes a manifest with SHA-256.

    During the formal benchmark run, set:
        HF_HUB_OFFLINE=1  TRANSFORMERS_OFFLINE=1

.PARAMETER Force
    Re-download even if model files already exist.
#>
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

$Root      = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath  = Join-Path $Root '.venvs\unstructured'
$ModelRoot = Join-Path $Root 'models\unstructured'
$HfHome    = Join-Path $ModelRoot 'huggingface'
$ManifestDir = Join-Path $ModelRoot 'manifests'

if (-not (Test-Path "$VenvPath\Scripts\python.exe")) {
    throw "[prepare_unstructured_models] Venv not found. Run setup_unstructured.ps1 first."
}

Write-Host "[prepare_unstructured_models] Creating model directories..."
New-Item -ItemType Directory -Force -Path $HfHome | Out-Null
New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null

$Python = "$VenvPath\Scripts\python.exe"

# ============================================================
# PHASE 1 - acquisition
# Network is allowed ONLY here.
# ============================================================

$env:HF_HOME = $HfHome
$env:HF_HUB_CACHE = Join-Path $HfHome 'hub'

Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue

$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:SCARF_NO_ANALYTICS = '1'
$env:UNSTRUCTURED_DEFAULT_MODEL_NAME = 'yolox'
$env:UNSTRUCTURED_HI_RES_MODEL_NAME = 'yolox'

Write-Host "[prepare_unstructured_models] Acquiring YOLOX..."

$DownloadScript = @'
from unstructured_inference.models.base import get_model

model = get_model("yolox")

if model is None:
    raise RuntimeError("get_model('yolox') returned None")

print("YOLOX acquisition: PASS")
'@

Invoke-PythonScriptChecked `
    -Python $Python `
    -ScriptText $DownloadScript

# ============================================================
# PHASE 2 - independent offline validation
# Invoke-PythonScriptChecked starts a NEW python.exe process.
# ============================================================

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:SCARF_NO_ANALYTICS = '1'

Write-Host "[prepare_unstructured_models] Validating YOLOX offline..."

$OfflineValidationScript = @'
from unstructured_inference.models.base import get_model

model = get_model("yolox")

if model is None:
    raise RuntimeError(
        "Offline validation failed: get_model('yolox') returned None"
    )

print("YOLOX offline validation: PASS")
'@

Invoke-PythonScriptChecked `
    -Python $Python `
    -ScriptText $OfflineValidationScript

# ============================================================
# PHASE 3 - manifest
# Only reached after independent offline validation succeeds.
# ============================================================

$ManifestScript = @"
import hashlib
import json
import time
from pathlib import Path

model_root = Path(r'$ModelRoot')
hf_home = Path(r'$HfHome')
manifest_dir = Path(r'$ManifestDir')

files = {}

for path in sorted(hf_home.rglob("*.onnx")):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    files[str(path.relative_to(model_root))] = digest

if not files:
    raise RuntimeError(
        "No ONNX model files found after YOLOX preparation"
    )

manifest = {
    "timestamp": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(),
    ),
    "model": "yolox",
    "offline_validation": True,
    "files": files,
}

manifest_path = manifest_dir / "unstructured_models.json"

manifest_path.write_text(
    json.dumps(manifest, indent=2),
    encoding="utf-8",
)

print(f"Manifest: {manifest_path}")
print("Unstructured model preparation: PASS")
"@

Invoke-PythonScriptChecked `
    -Python $Python `
    -ScriptText $ManifestScript
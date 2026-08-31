#Requires -Version 5.1
<#
.SYNOPSIS
    Acquire and certify all local artifacts required by the
    Docling full_cpu_local profile.

.DESCRIPTION
    Phase 0 validates prerequisites (Python, venv, docling version).

    Phase 1 allows network access and acquires all models required by
    full_cpu_local using docling's official download_models API:
      - Layout (docling-layout-heron)
      - TableFormer accurate
      - RapidOCR torch:pt
      - SmolVLM-256M-Instruct (picture description)
      - Document figure classifier (picture classification)
      - CodeFormulaV2 (formula/code enrichment)
      - Granite Vision V4 (chart extraction)

    Phase 2 starts a new Python process with HF offline variables and a
    socket guard. Every required model must load. The full Docling
    pipeline is initialized as the gate check.

    Phase 3 writes a manifest recording certified model state.

    Without -Force: preserves partial downloads and resumes where possible.
    With -Force: removes the model root before acquisition.

.PARAMETER Python
    Path to the Python executable inside the Docling venv.

.PARAMETER ModelRoot
    Path to the Docling model artifacts directory.

.PARAMETER Force
    Remove the model root and re-acquire all artifacts.

.PARAMETER ValidateOnly
    Skip Phase 1 acquisition; run Phases 2 and 3 only.
#>
[CmdletBinding()]
param(
    [string]$Python    = "",
    [string]$ModelRoot = "",
    [switch]$Force,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\_helpers.ps1"

Assert-WindowsLongPathsEnabled

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName

if ($Python -eq "") {
    $Python = Join-Path $Root '.venvs\docling\Scripts\python.exe'
}

if ($ModelRoot -eq "") {
    $ModelRoot = Join-Path $Root 'models\docling\docling\models'
}

$HfHome      = Join-Path $Root 'models\docling\huggingface'
$HfCache     = Join-Path $HfHome 'hub'
$HfXet       = Join-Path $HfHome 'xet'
$ManifestDir = Join-Path $Root 'models\docling\manifests'
$ManifestPath = Join-Path $ManifestDir 'docling_models_manifest.json'
$ValidateScript = Join-Path $Root 'scripts\validate_docling_models.py'

# ============================================================
# Phase 0 — prerequisites
# ============================================================

Write-Host ""
Write-Host "[docling-models] Phase 0 - prerequisites" -ForegroundColor Cyan

if (-not (Test-Path $Python -PathType Leaf)) {
    throw (
        "[docling-models] Docling venv not found. " +
        "Run setup_docling.ps1 first: $Python"
    )
}

if (-not (Test-Path $ValidateScript -PathType Leaf)) {
    throw (
        "[docling-models] Validation script not found: $ValidateScript"
    )
}

# Verify docling version
$CheckVersion = @'
import importlib.metadata, sys
try:
    v = importlib.metadata.version("docling")
except importlib.metadata.PackageNotFoundError:
    print(f"FAIL: docling not installed", file=sys.stderr)
    sys.exit(1)
if v != "2.122.0":
    print(f"WARN: expected docling==2.122.0, got {v!r}")
else:
    print(f"OK: docling=={v}")
'@

Invoke-PythonScriptChecked `
    -Python $Python `
    -ScriptText $CheckVersion

# Verify pip integrity
Invoke-NativeChecked `
    -Cmd $Python `
    -Args @('-m', 'pip', 'check')

# Report free disk space
$DriveInfo = Get-PSDrive -Name (Split-Path $ModelRoot -Qualifier).TrimEnd(':')
$FreeMB = [math]::Round($DriveInfo.Free / 1MB, 0)
Write-Host "[docling-models] Free space on drive: ${FreeMB} MB"

if ($FreeMB -lt 2048) {
    Write-Warning (
        "[docling-models] Less than 2 GB free. " +
        "Acquisition may fail mid-download. Existing partial artifacts are preserved."
    )
}

# Detect inherited HF environment from other parsers
$InheritedHfHome = [Environment]::GetEnvironmentVariable("HF_HOME", "Process")
if ($InheritedHfHome -ne $null -and $InheritedHfHome -ne "" -and
    $InheritedHfHome -ne $HfHome) {
    Write-Warning (
        "[docling-models] HF_HOME is set to a different path: $InheritedHfHome. " +
        "This script will override it with the Docling-specific cache."
    )
}

Write-Host "[docling-models] Phase 0: PASS"

# ============================================================
# Environment isolation (save and restore in finally)
# ============================================================

$ManagedEnvironmentNames = @(
    'HF_HOME',
    'HF_HUB_CACHE',
    'HF_XET_CACHE',
    'HF_HUB_OFFLINE',
    'TRANSFORMERS_OFFLINE',
    'HF_HUB_DISABLE_TELEMETRY',
    'DO_NOT_TRACK',
    'SCARF_NO_ANALYTICS',
    'BENCHMARK_DOCLING_MODEL_ROOT',
    'BENCHMARK_DOCLING_MANIFEST'
)

$OriginalEnvironment = @{}
foreach ($Name in $ManagedEnvironmentNames) {
    $OriginalEnvironment[$Name] = (
        [Environment]::GetEnvironmentVariable($Name, 'Process')
    )
}

try {
    $env:HF_HOME                 = $HfHome
    $env:HF_HUB_CACHE            = $HfCache
    $env:HF_XET_CACHE            = $HfXet
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $env:DO_NOT_TRACK            = '1'
    $env:SCARF_NO_ANALYTICS      = '1'
    $env:BENCHMARK_DOCLING_MODEL_ROOT = $ModelRoot
    $env:BENCHMARK_DOCLING_MANIFEST   = $ManifestPath

    New-Item -ItemType Directory -Force -Path $HfCache    | Out-Null
    New-Item -ItemType Directory -Force -Path $HfXet      | Out-Null
    New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null
    New-Item -ItemType Directory -Force -Path $ModelRoot  | Out-Null

    if ($Force -and (Test-Path $ModelRoot)) {
        Write-Host "[docling-models] -Force: removing model root $ModelRoot"
        Remove-Item -Recurse -Force $ModelRoot
        New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null
    }

    # ============================================================
    # PHASE 1 - acquisition. Network may be available.
    # ============================================================
    Remove-Item Env:HF_HUB_OFFLINE       -ErrorAction SilentlyContinue
    Remove-Item Env:TRANSFORMERS_OFFLINE  -ErrorAction SilentlyContinue

    if (-not $ValidateOnly) {
        Write-Host ""
        Write-Host "[docling-models] PHASE 1 - acquisition" -ForegroundColor Cyan

        $AcquireModels = @'
from __future__ import annotations

import os
import sys
from pathlib import Path

model_root = Path(os.environ["BENCHMARK_DOCLING_MODEL_ROOT"])

try:
    from docling.utils.model_downloader import download_models
except ImportError as exc:
    print(f"FAIL: cannot import download_models: {exc}", file=sys.stderr)
    sys.exit(1)

print(f"Acquiring models to: {model_root}")
print("force=False — partial downloads will be resumed.")

download_models(
    output_dir=model_root,
    force=False,
    progress=True,
    with_layout=True,
    with_tableformer=True,
    with_tableformer_v2=False,
    with_code_formula=True,
    with_picture_classifier=True,
    with_smolvlm=True,
    with_granitedocling=False,
    with_granitedocling_mlx=False,
    with_granitedocling_2stage=False,
    with_smoldocling=False,
    with_smoldocling_mlx=False,
    with_granite_vision=False,
    with_granite_chart_extraction=False,
    with_granite_chart_extraction_v4=True,
    with_rapidocr=True,
    rapidocr_models=["torch:pt"],
    with_easyocr=False,
    with_nemotron_ocr=False,
)

print("DOCLING MODEL ACQUISITION: PASS")
'@

        Invoke-PythonScriptChecked `
            -Python $Python `
            -ScriptText $AcquireModels

    }
    else {
        Write-Host ""
        Write-Host "[docling-models] PHASE 1 - skipped (ValidateOnly)" -ForegroundColor Yellow
    }

    # ============================================================
    # PHASE 2 - hard-offline validation (structural + component + pipeline).
    # ============================================================
    $env:HF_HUB_OFFLINE      = '1'
    $env:TRANSFORMERS_OFFLINE = '1'

    Write-Host ""
    Write-Host "[docling-models] PHASE 2 - offline validation" -ForegroundColor Cyan

    Invoke-NativeChecked `
        -Cmd $Python `
        -Args @(
            $ValidateScript,
            '--model-root', $ModelRoot,
            '--validate-only'
        )

    # ============================================================
    # PHASE 3 - deterministic manifest.
    # ============================================================
    Write-Host ""
    Write-Host "[docling-models] PHASE 3 - manifest" -ForegroundColor Cyan

    Invoke-NativeChecked `
        -Cmd $Python `
        -Args @(
            $ValidateScript,
            '--model-root', $ModelRoot,
            '--skip-component-load',
            '--skip-pipeline-init'
        )

    if (-not (Test-Path $ManifestPath -PathType Leaf)) {
        throw (
            "[docling-models] Manifest was not created: $ManifestPath"
        )
    }

    Write-Host ""
    Write-Host "[docling-models] Completed successfully." -ForegroundColor Green
    Write-Host "Manifest: $ManifestPath"
}
finally {
    foreach ($Name in $ManagedEnvironmentNames) {
        $OriginalValue = $OriginalEnvironment[$Name]

        if ($null -eq $OriginalValue) {
            Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path "Env:$Name" -Value $OriginalValue
        }
    }
}

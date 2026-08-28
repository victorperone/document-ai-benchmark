#Requires -Version 5.1
<#
.SYNOPSIS
    Create the Unstructured venv for host-runtime execution on Windows Server.

.DESCRIPTION
    Phase 1 installs pinned Python dependencies with network access allowed.
    Phase 2 validates imports with offline and telemetry variables enabled.
    Model acquisition is intentionally delegated to
    prepare_unstructured_models.ps1.

.PARAMETER Force
    Recreate the virtual environment even when it already exists.
#>
[CmdletBinding()]
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\_helpers.ps1"

Assert-WindowsLongPathsEnabled

$null = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw (
        "[unstructured] Python 3.12 nao esta disponivel. " +
        "Instale Python 3.12 e tente novamente."
    )
}

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\unstructured'
$ReqFile = Join-Path $Root 'requirements\windows\unstructured.txt'
$Python = Join-Path $VenvPath 'Scripts\python.exe'

if (-not (Test-Path $ReqFile -PathType Leaf)) {
    throw "[unstructured] Requirements file not found: $ReqFile"
}

$OfflineEnvNames = @(
    'HF_HUB_OFFLINE',
    'TRANSFORMERS_OFFLINE',
    'HF_HUB_DISABLE_TELEMETRY',
    'DO_NOT_TRACK',
    'SCARF_NO_ANALYTICS'
)

$OriginalEnvironment = @{}
foreach ($Name in $OfflineEnvNames) {
    $OriginalEnvironment[$Name] = (
        [Environment]::GetEnvironmentVariable($Name, 'Process')
    )
}

try {
    Write-Host "[unstructured] Setting up virtual environment..."

    if ($Force -and (Test-Path $VenvPath)) {
        Remove-Item -Recurse -Force $VenvPath
    }

    if (-not (Test-Path $VenvPath)) {
        Invoke-NativeChecked `
            -Cmd 'py' `
            -Args @('-3.12', '-m', 'venv', $VenvPath)
    }

    if (-not (Test-Path $Python -PathType Leaf)) {
        throw "[unstructured] Venv Python not found: $Python"
    }

    # ----------------------------------------------------------------
    # Phase 1: dependency installation. Network may be available.
    # ----------------------------------------------------------------
    Remove-Item Env:HF_HUB_OFFLINE      -ErrorAction SilentlyContinue
    Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue

    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $env:DO_NOT_TRACK              = '1'
    $env:SCARF_NO_ANALYTICS        = '1'

    Write-Host "[unstructured] PHASE 1 - installing dependencies..."

    Invoke-NativeChecked `
        -Cmd $Python `
        -Args @('-m', 'pip', 'install', '-r', $ReqFile)

    Write-Host "[unstructured] Running pip check..."

    Invoke-NativeChecked `
        -Cmd $Python `
        -Args @('-m', 'pip', 'check')

    # ----------------------------------------------------------------
    # Phase 2: import smoke with offline variables enabled.
    # No model acquisition is allowed here.
    # ----------------------------------------------------------------
    foreach ($Name in $OfflineEnvNames) {
        Set-Item -Path "Env:$Name" -Value '1'
    }

    Write-Host "[unstructured] PHASE 2 - offline import smoke..."

    $Smoke = @'
from __future__ import annotations

import importlib.metadata as metadata

EXPECTED = {
    "unstructured": "0.27.1",
    "unstructured-inference": "1.6.13",
}

for distribution, expected in EXPECTED.items():
    actual = metadata.version(distribution)
    if actual != expected:
        raise RuntimeError(
            f"{distribution}: expected {expected}, got {actual}"
        )
    print(f"{distribution}: {actual}")

from unstructured.partition.pdf import partition_pdf
from unstructured.documents.elements import Element
import onnxruntime
import pdf2image
import pikepdf
import unstructured_pytesseract

if not callable(partition_pdf):
    raise RuntimeError("partition_pdf is not callable")

print("partition_pdf: OK")
print("Element: OK")
print("onnxruntime:", onnxruntime.__version__)
print("pdf2image: OK")
print("pikepdf:", pikepdf.__version__)
print("unstructured_pytesseract: OK")
print("UNSTRUCTURED IMPORT SMOKE: PASS")
'@

    Invoke-PythonScriptChecked `
        -Python $Python `
        -ScriptText $Smoke

    Write-Host "[unstructured] Done."
}
finally {
    foreach ($Name in $OfflineEnvNames) {
        $OriginalValue = $OriginalEnvironment[$Name]

        if ($null -eq $OriginalValue) {
            Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path "Env:$Name" -Value $OriginalValue
        }
    }
}

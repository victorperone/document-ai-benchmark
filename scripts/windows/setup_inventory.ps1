#Requires -Version 5.1
<#
.SYNOPSIS
    Create the inventory venv for host-runtime execution on Windows Server.

.DESCRIPTION
    Installs only pymupdf (no pymupdf-layout, no RapidOCR, no ONNX Runtime).
    This venv is used exclusively by build_source_inventory.py so that a crash
    in the Layout GNN does not block inventory generation for all parsers.

.PARAMETER Force
    Recreate the venv even if it already exists.
#>
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

$null = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "[inventory] Python 3.12 nao esta disponivel. Instale Python 3.12 e tente novamente."
}

$Root     = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\inventory'
$ReqFile  = Join-Path $Root 'requirements\windows\inventory.txt'
$Python   = "$VenvPath\Scripts\python.exe"

if (-not (Test-Path $ReqFile -PathType Leaf)) {
    throw "[inventory] Requirements file not found: $ReqFile"
}

Write-Host "[inventory] Setting up inventory venv (pymupdf only, no Layout/ONNX)..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

Set-InstallingMarker $VenvPath
try {
    if (-not (Test-Path $Python)) {
        Invoke-NativeChecked py @('-3.12', '-m', 'venv', $VenvPath)
    }

    Invoke-NativeChecked $Python @('-m', 'pip', 'install', '-r', $ReqFile)

    Invoke-NativeChecked $Python @('-m', 'pip', 'check')

    $Smoke = @'
import sys
import importlib.metadata as meta

pkg = "pymupdf"
try:
    ver = meta.version(pkg)
    print(f"{pkg}: {ver}")
except meta.PackageNotFoundError:
    print(f"FAIL: {pkg} not installed", file=sys.stderr)
    sys.exit(1)

import fitz
print(f"fitz version: {fitz.version}")

# Confirm that heavy Layout extensions are NOT present in this venv
for forbidden in ("pymupdf_layout", "rapidocr_onnxruntime", "onnxruntime"):
    try:
        meta.version(forbidden)
        print(f"FAIL: {forbidden} must not be installed in the inventory venv", file=sys.stderr)
        sys.exit(1)
    except meta.PackageNotFoundError:
        pass

print("inventory venv smoke: PASS")
'@

    Invoke-PythonScriptChecked -Python $Python -ScriptText $Smoke

    $LockSha = (Get-FileHash $ReqFile -Algorithm SHA256).Hash
    Write-ReadyMarkerAtomically $VenvPath $Python $LockSha
} catch {
    if (Test-Path "$VenvPath\.ready.json") {
        Remove-Item "$VenvPath\.ready.json" -Force
    }
    throw
} finally {
    Remove-InstallingMarker $VenvPath
}

Write-Host "[inventory] Done."

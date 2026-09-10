#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

# liteparse 2.13.0 only ships a Windows cp311 wheel; use Python 3.11 for this venv.
$null = & py -3.11 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "[liteparse] Python 3.11 nao esta disponivel. Instale Python 3.11 e tente novamente."
}

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\liteparse'
$ReqFile  = Join-Path $Root 'requirements\windows\liteparse.txt'
$Python   = "$VenvPath\Scripts\python.exe"

Write-Host "[liteparse] Setting up liteparse venv (Python 3.11)..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

Set-InstallingMarker $VenvPath
try {

if (-not (Test-Path $Python)) {
    Invoke-NativeChecked py @('-3.11', '-m', 'venv', $VenvPath)
}

Invoke-NativeChecked $Python @(
    '-m', 'pip', 'install',
    'torch==2.9.1', 'torchvision==0.24.1',
    '--index-url', 'https://download.pytorch.org/whl/cpu'
)

Invoke-NativeChecked $Python @('-m', 'pip', 'install', '-r', $ReqFile)

Invoke-NativeChecked $Python @('-m', 'pip', 'check')

$Smoke = @'
import importlib.metadata
import sys

# liteparse exact version check
try:
    liteparse_version = importlib.metadata.version("liteparse")
except importlib.metadata.PackageNotFoundError:
    print("FAIL: liteparse not installed", file=sys.stderr)
    sys.exit(1)

if liteparse_version != "2.13.0":
    print(f"FAIL: expected liteparse==2.13.0, got {liteparse_version!r}", file=sys.stderr)
    sys.exit(1)

# transformers minimum version check (>=4.40.0)
try:
    transformers_version = importlib.metadata.version("transformers")
except importlib.metadata.PackageNotFoundError:
    print("FAIL: transformers not installed (need >=4.40.0)", file=sys.stderr)
    sys.exit(1)

try:
    from packaging.version import Version
    if Version(transformers_version) < Version("4.40.0"):
        print(f"FAIL: transformers {transformers_version!r} < 4.40.0", file=sys.stderr)
        sys.exit(1)
except ImportError:
    pass  # packaging not available; skip version range check

from transformers import (
    AutoModelForImageTextToText,
    AutoProcessor,
)

print(
    "[liteparse] Runtime API smoke: PASS"
)
'@

Invoke-PythonScriptChecked `
    -Python $Python `
    -ScriptText $Smoke

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

Write-Host "[liteparse] Done."

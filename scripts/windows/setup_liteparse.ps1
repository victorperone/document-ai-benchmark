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
$ReqFile = Join-Path $Root 'requirements\windows\liteparse.txt'

Write-Host "[liteparse] Setting up liteparse venv (Python 3.11)..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPath)) {
    Invoke-NativeChecked py @('-3.11', '-m', 'venv', $VenvPath)
}

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'install',
    'torch==2.9.1', 'torchvision==0.24.1',
    '--index-url', 'https://download.pytorch.org/whl/cpu'
)

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-m', 'pip', 'install', '-r', $ReqFile)

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'check'
)

$Smoke = @'
import importlib.metadata
import sys

expected = {
    "liteparse": "2.13.0",
    "transformers": "5.16.1",
}

for package, expected_version in expected.items():
    try:
        actual_version = importlib.metadata.version(
            package
        )
    except importlib.metadata.PackageNotFoundError:
        print(
            f"FAIL: {package} not installed",
            file=sys.stderr,
        )
        sys.exit(1)

    if actual_version != expected_version:
        print(
            f"FAIL: expected "
            f"{package}=={expected_version}, "
            f"got {actual_version!r}",
            file=sys.stderr,
        )
        sys.exit(1)

from transformers import (
    AutoModelForImageTextToText,
    AutoProcessor,
)

print(
    "[liteparse] Runtime API smoke: PASS"
)
'@

Invoke-PythonScriptChecked `
    -Python "$VenvPath\Scripts\python.exe" `
    -ScriptText $Smoke

Write-Host "[liteparse] Done."

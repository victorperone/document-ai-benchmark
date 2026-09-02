#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\visual-enrichment'
$ReqFile = Join-Path $Root 'requirements\windows\visual_enrichment.txt'

Write-Host "[visual-enrichment] Setting up visual enrichment venv..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPath)) {
    Invoke-NativeChecked python @('-m', 'venv', $VenvPath)
}

# Install CPU-only PyTorch first (same version as liteparse for model compat)
Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'install',
    'torch==2.9.1', 'torchvision==0.24.1',
    '--index-url', 'https://download.pytorch.org/whl/cpu'
)

# Install paddlepaddle CPU wheel before paddleocr to avoid version conflicts
Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'install',
    'paddlepaddle',
    '-i', 'https://www.paddlepaddle.org.cn/packages/stable/cpu/'
)

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-m', 'pip', 'install', '-r', $ReqFile)

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-m', 'pip', 'check')

# Smoke test: imports only, no model loading, no network
$Smoke = @'
import sys

failures = []

try:
    import paddleocr
except Exception as exc:
    failures.append(f"paddleocr: {exc}")

try:
    import transformers
    actual = transformers.__version__
    expected = "5.16.1"
    if actual != expected:
        failures.append(f"transformers version: expected {expected}, got {actual}")
except Exception as exc:
    failures.append(f"transformers: {exc}")

try:
    from PIL import Image
except Exception as exc:
    failures.append(f"Pillow: {exc}")

try:
    import torch
except Exception as exc:
    failures.append(f"torch: {exc}")

try:
    from src.enrichment.visual_contract import VisualRequest, VisualResponse
except Exception as exc:
    failures.append(f"visual_contract: {exc}")

try:
    from src.enrichment.visual_worker_client import VisualWorkerClient
except Exception as exc:
    failures.append(f"visual_worker_client: {exc}")

if failures:
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    sys.exit(1)

print("OK: visual enrichment smoke test passed")
'@

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-c', $Smoke
)

Write-Host "[visual-enrichment] Setup complete."
Write-Host ""
Write-Host "NOTE: SmolVLM model must be present locally before first use."
Write-Host "      Set smolvlm_model_path in the profile to the local model directory."
Write-Host "      Example: HuggingFaceTB/SmolVLM-256M-Instruct (downloaded offline)"

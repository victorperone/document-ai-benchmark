#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Verify')][string]$Mode = 'Prepare',
    [switch]$Force,
    [string]$FixturePath = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"
if ($Mode -eq 'Verify' -and $Force) { throw '-Force is invalid with -Mode Verify.' }
$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$Python = Join-Path $Root '.venvs\xberg\Scripts\python.exe'
$ModelRoot = Join-Path $Root 'models\xberg'
if ($FixturePath -eq '') { $FixturePath = Join-Path $Root 'fixtures\deep_smoke\deep_smoke.pdf' }
$env:PYTHONPATH = $Root
$env:HF_HOME = Join-Path $ModelRoot 'huggingface'
$env:BENCHMARK_XBERG_ROOT = $ModelRoot
$env:BENCHMARK_XBERG_FIXTURE = $FixturePath

if ($Mode -eq 'Prepare') {
    if ($Force -and (Test-Path $ModelRoot)) { Remove-Item -LiteralPath $ModelRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null
    Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
    Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
} else {
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    Invoke-ModelManifest -Mode Verify -Python $Python -Component 'xberg' `
        -Version 'layout-1.0.14' -ModelRoot $ModelRoot
}

if (-not (Test-Path $FixturePath -PathType Leaf)) { throw "Smoke fixture not found: $FixturePath" }
$Inference = @'
import asyncio,os
from pathlib import Path
from src.benchmark.config import get_profile
from src.parsers.xberg_v2 import _build_xberg_config,_extract,_unwrap_extraction_result
root=Path(os.environ["BENCHMARK_XBERG_ROOT"]).resolve()
fixture=Path(os.environ["BENCHMARK_XBERG_FIXTURE"]).resolve()
profile=get_profile("xberg","full_cpu_layout")
document,_=_unwrap_extraction_result(asyncio.run(_extract(fixture,_build_xberg_config(profile,root))))
if not str(getattr(document,"content","")).strip(): raise RuntimeError("Xberg smoke produced empty content")
print("XBERG_MODEL_INFERENCE=PASS")
'@
Invoke-PythonScriptChecked -Python $Python -ScriptText $Inference
if ($Mode -eq 'Prepare') {
    Invoke-ModelManifest -Mode Prepare -Python $Python -Component 'xberg' `
        -Version 'layout-1.0.14' -ModelRoot $ModelRoot
}
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'xberg' `
    -Version 'layout-1.0.14' -ModelRoot $ModelRoot

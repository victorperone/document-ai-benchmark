#Requires -Version 5.1
<# Runs all model verification gates and the seven-parser deep smoke offline. #>
[CmdletBinding()]
param(
    [string]$OutputRoot = 'outputs\deep_smoke',
    [ValidateRange(1, 86400)][int]$JobTimeoutSeconds = 3600,
    [switch]$VerboseOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

$RepoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$CorePython = Join-Path $RepoRoot '.venvs\core\Scripts\python.exe'
$DeepSmoke = Join-Path $RepoRoot 'scripts\parser_deep_smoke.py'
if (-not (Test-Path $CorePython -PathType Leaf)) {
    throw "Core venv not found: $CorePython"
}

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
$env:DO_NOT_TRACK = '1'

$Verifiers = @(
    'prepare_docling_models.ps1',
    'prepare_mineru_models.ps1',
    'prepare_paddleocr_models.ps1',
    'prepare_liteparse_models.ps1',
    'prepare_visual_enrichment_models.ps1',
    'prepare_unstructured_models.ps1',
    'prepare_xberg_models.ps1'
)

foreach ($Verifier in $Verifiers) {
    $Script = Join-Path $PSScriptRoot $Verifier
    Write-Host "=== Offline model verification: $Verifier ===" -ForegroundColor Cyan
    & $Script -Mode Verify
}

$ResolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot
} else {
    Join-Path $RepoRoot $OutputRoot
}
$Args = @(
    $DeepSmoke,
    '--output-root', $ResolvedOutput,
    '--job-timeout-seconds', $JobTimeoutSeconds
)
if ($VerboseOutput) { $Args += '--verbose-output' }
Invoke-NativeChecked -Cmd $CorePython -Args $Args
Write-Host 'DEEP_SMOKE_ALL=PASS' -ForegroundColor Green

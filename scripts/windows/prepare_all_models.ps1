#Requires -Version 5.1
<# Prepare or read-only verify every local model set in dependency order. #>
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Verify')][string]$Mode = 'Prepare',
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($Mode -eq 'Verify' -and $Force) { throw '-Force is invalid with -Mode Verify.' }

$Scripts = @(
    'prepare_docling_models.ps1',
    'prepare_mineru_models.ps1',
    'prepare_paddleocr_models.ps1',
    'prepare_liteparse_models.ps1',
    'prepare_visual_enrichment_models.ps1',
    'prepare_unstructured_models.ps1',
    'prepare_xberg_models.ps1'
)

foreach ($Name in $Scripts) {
    Write-Host "=== $Mode models: $Name ===" -ForegroundColor Cyan
    $Arguments = @{ Mode = $Mode }
    if ($Force) { $Arguments['Force'] = $true }
    & (Join-Path $PSScriptRoot $Name) @Arguments
}
Write-Host "ALL_MODEL_SETS_$($Mode.ToUpperInvariant())=PASS" -ForegroundColor Green

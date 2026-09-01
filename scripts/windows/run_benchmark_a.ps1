#Requires -Version 5.1
<#
.SYNOPSIS
    Run Benchmark A: all seven parsers with full_cpu_local on Windows host.
.DESCRIPTION
    Wrapper around run_batch.py that enforces the correct parameters for Benchmark A:
      suite=windows_full_cpu_local_all_host, runtime=host, artifacts=all,
      continue-on-error, no-summary.

    Execution flow (unless -DryRun or -PreflightOnly):
      1. Run preflight for all 7 parser/profile pairs.
      2. If any preflight fails  -> abort (exit 1). Do not start inference.
      3. If all 7 pass           -> run full batch.

    This makes preflight mandatory for the official Benchmark A entrypoint,
    closing the gap where run_batch.py does not run preflight automatically.
.PARAMETER InputDir
    Directory containing the PDF files to process. Required.
.PARAMETER OutputRoot
    Root directory for output artifacts. Required.
    Host runtime automatically namespaces under <OutputRoot>\host\.
.PARAMETER Limit
    Limit processing to the first N PDFs. 0 = no limit (default).
.PARAMETER DryRun
    Print the run plan without executing anything. Exits after dry run.
.PARAMETER PreflightOnly
    Run only the preflight checks and exit. Does not start batch execution.
.EXAMPLE
    # Dry run (plan only, no execution)
    .\run_benchmark_a.ps1 -InputDir C:\pdfs -OutputRoot outputs\_validation\benchmark_a -DryRun

    # Preflight only
    .\run_benchmark_a.ps1 -InputDir C:\pdfs -OutputRoot outputs\_validation\benchmark_a -PreflightOnly

    # Full run (preflight then inference)
    .\run_benchmark_a.ps1 -InputDir C:\pdfs -OutputRoot outputs\_validation\benchmark_a

    # Full run limited to 1 PDF
    .\run_benchmark_a.ps1 -InputDir C:\pdfs -OutputRoot outputs\_validation\benchmark_a -Limit 1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$InputDir,

    [Parameter(Mandatory)]
    [string]$OutputRoot,

    [int]$Limit = 0,

    [switch]$DryRun,

    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot  = (Resolve-Path "$PSScriptRoot\..\.." ).Path
$CorePython = Join-Path $RepoRoot ".venvs\core\Scripts\python.exe"
$BatchScript = Join-Path $RepoRoot "scripts\run_batch.py"

if (-not (Test-Path $CorePython)) {
    throw "Core venv not found at '$CorePython'. Run setup_core.ps1 first."
}

# Fixed parameters for Benchmark A
$Suite   = 'windows_full_cpu_local_all_host'
$Runtime = 'host'

$BaseArgs = @(
    $BatchScript,
    '--suite',    $Suite,
    '--runtime',  $Runtime,
    '--input-dir', $InputDir,
    '--output-root', $OutputRoot,
    '--artifacts', 'all',
    '--continue-on-error',
    '--no-summary'
)

if ($Limit -gt 0) {
    $BaseArgs += '--limit', $Limit
}

# -- Dry run -------------------------------------------------------------------
if ($DryRun) {
    Write-Host ""
    Write-Host "=== Benchmark A - DRY RUN ===" -ForegroundColor Cyan
    & $CorePython @BaseArgs '--dry-run'
    exit $LASTEXITCODE
}

# -- Preflight only ------------------------------------------------------------
if ($PreflightOnly) {
    Write-Host ""
    Write-Host "=== Benchmark A - PREFLIGHT ===" -ForegroundColor Cyan
    & $CorePython @BaseArgs '--preflight'
    exit $LASTEXITCODE
}

# -- Full run: preflight then inference ----------------------------------------
Write-Host ""
Write-Host "=== Benchmark A - PREFLIGHT (mandatory) ===" -ForegroundColor Cyan
& $CorePython @BaseArgs '--preflight'
$PreflightExit = $LASTEXITCODE

if ($PreflightExit -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Preflight failed (exit $PreflightExit). Batch will NOT start." -ForegroundColor Red
    Write-Host "Fix the reported issues and re-run." -ForegroundColor Red
    exit $PreflightExit
}

Write-Host ""
Write-Host "=== Benchmark A - BATCH ===" -ForegroundColor Cyan
& $CorePython @BaseArgs
exit $LASTEXITCODE

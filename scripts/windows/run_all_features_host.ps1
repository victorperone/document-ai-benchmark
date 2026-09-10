#Requires -Version 5.1
<#
.SYNOPSIS
    Execute the seven-parser, all-features benchmark locally on Windows Server.
.DESCRIPTION
    Runs a mandatory offline host preflight followed by a fresh batch by
    default. The Python runner adds the `host` namespace below OutputRoot.

    Preflight args do not receive --force/--resume flags (preflight is always
    read-only and stateless). Run args receive the resume/force flag.
#>
[CmdletBinding()]
param(
    [Alias("InputDirectory")]
    [string]$InputDir = "data\raw\batch",
    [string]$OutputRoot = "outputs",
    [switch]$Resume,
    [switch]$DryRun,
    [switch]$PreflightOnly,
    [switch]$VerboseOutput,
    [ValidateRange(1, 86400)]
    [Nullable[int]]$JobTimeoutSeconds = $null
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$CorePython = Join-Path $RepoRoot '.venvs\core\Scripts\python.exe'
$BatchScript = Join-Path $RepoRoot 'scripts\run_batch.py'

if (-not (Test-Path $CorePython -PathType Leaf)) {
    throw "Core venv not found at '$CorePython'. Run setup_core.ps1 first."
}

$InputPath = if ([System.IO.Path]::IsPathRooted($InputDir)) {
    $InputDir
} else {
    Join-Path $RepoRoot $InputDir
}

$OutputPath = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot
} else {
    Join-Path $RepoRoot $OutputRoot
}

# Shared base args (no resume/force — both preflight and run receive these)
$SharedArgs = @(
    $BatchScript,
    '--suite', 'windows_all_features_host',
    '--runtime', 'host',
    '--input-dir', $InputPath,
    '--output-root', $OutputPath,
    '--artifacts', 'all',
    '--continue-on-error',
    '--no-summary'
)

# Run args: shared + resume/force + optional flags
$RunArgs = $SharedArgs + @(if ($Resume) { '--resume' } else { '--force' })

if ($VerboseOutput) { $RunArgs += '--verbose-output' }
if ($null -ne $JobTimeoutSeconds) { $RunArgs += '--job-timeout-seconds'; $RunArgs += [string]$JobTimeoutSeconds }

if ($DryRun) {
    & $CorePython @RunArgs '--dry-run'
    exit $LASTEXITCODE
}

Write-Host "=== All features host - mandatory preflight ===" -ForegroundColor Cyan
# Preflight receives SharedArgs only (no --force/--resume/--job-timeout-seconds)
& $CorePython @SharedArgs '--preflight'
if ($LASTEXITCODE -ne 0) {
    $PreflightExitCode = $LASTEXITCODE
    Write-Host 'Preflight failed; inference was not started.' -ForegroundColor Red
    exit $PreflightExitCode
}

if ($PreflightOnly) { exit 0 }

Write-Host "=== All features host - batch ===" -ForegroundColor Cyan
& $CorePython @RunArgs
exit $LASTEXITCODE

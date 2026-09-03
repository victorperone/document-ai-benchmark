#Requires -Version 5.1
<#
.SYNOPSIS
    Execute the seven-parser, all-features benchmark locally on Windows Server.
.DESCRIPTION
    Runs a mandatory offline host preflight followed by a fresh batch by
    default. The Python runner adds the `host` namespace below OutputRoot.
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
    [int]$JobTimeoutSeconds = 3600
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

$BaseArgs = @(
    $BatchScript,
    '--suite', 'windows_all_features_host',
    '--runtime', 'host',
    '--input-dir', $InputPath,
    '--output-root', $OutputPath,
    '--artifacts', 'all',
    '--continue-on-error',
    '--no-summary',
    '--job-timeout-seconds', $JobTimeoutSeconds
)

if ($Resume) { $BaseArgs += '--resume' } else { $BaseArgs += '--force' }
if ($VerboseOutput) { $BaseArgs += '--verbose-output' }

if ($DryRun) {
    & $CorePython @BaseArgs '--dry-run'
    exit $LASTEXITCODE
}

Write-Host "=== All features host - mandatory preflight ===" -ForegroundColor Cyan
& $CorePython @BaseArgs '--preflight'
if ($LASTEXITCODE -ne 0) {
    $PreflightExitCode = $LASTEXITCODE
    Write-Host 'Preflight failed; inference was not started.' -ForegroundColor Red
    exit $PreflightExitCode
}

if ($PreflightOnly) { exit 0 }

Write-Host "=== All features host - batch ===" -ForegroundColor Cyan
& $CorePython @BaseArgs
exit $LASTEXITCODE

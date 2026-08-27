#Requires -Version 5.1
<#
.SYNOPSIS
    Run parser_tests for a host-only parser using its isolated venv.
.PARAMETER Parser
    Name of the host-only parser: 'unstructured' or 'xberg'.
.PARAMETER TestPath
    Optional path to a specific test file or directory within parser_tests/<parser>/.
    Defaults to all tests for the parser.
.PARAMETER Verbose
    Pass -v to pytest for verbose output.
.EXAMPLE
    .\run_host_parser_tests.ps1 -Parser unstructured
    .\run_host_parser_tests.ps1 -Parser xberg -Verbose
    .\run_host_parser_tests.ps1 -Parser unstructured -TestPath test_preflight.py
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('unstructured', 'xberg')]
    [string]$Parser,

    [string]$TestPath = '',

    [switch]$VerboseOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\_helpers.ps1"

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\.." ).Path
$VenvRoot = Join-Path $RepoRoot ".venvs\$Parser"
$Python   = Join-Path $VenvRoot "Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Venv not found at '$VenvRoot'. Run setup_$Parser.ps1 first."
}

$ParserTestsDir = Join-Path $RepoRoot "parser_tests\$Parser"
if (-not (Test-Path $ParserTestsDir)) {
    throw "Test directory not found: '$ParserTestsDir'"
}

$Target = if ($TestPath) {
    Join-Path $ParserTestsDir $TestPath
} else {
    $ParserTestsDir
}

Write-Host ""
Write-Host "=== Running host parser tests: $Parser ===" -ForegroundColor Cyan
Write-Host "    Python : $Python"
Write-Host "    Tests  : $Target"
Write-Host ""

$PytestArgs = @(
    '-m', 'pytest',
    $Target,
    '--tb=short',
    '-p', 'no:warnings'
)

if ($VerboseOutput) {
    $PytestArgs += '-v'
}

$env:PYTHONPATH = $RepoRoot

# Offline-mode env vars (same as the adapters enforce)
$env:HF_HUB_OFFLINE       = '1'
$env:TRANSFORMERS_OFFLINE  = '1'
$env:DO_NOT_TRACK          = '1'
$env:SCARF_NO_ANALYTICS    = '1'

if ($Parser -eq 'unstructured') {
    $env:HF_HOME = Join-Path $RepoRoot "models\unstructured"
}

Invoke-NativeChecked -Cmd $Python -Args $PytestArgs

Write-Host ""
Write-Host "=== Tests passed for $Parser ===" -ForegroundColor Green

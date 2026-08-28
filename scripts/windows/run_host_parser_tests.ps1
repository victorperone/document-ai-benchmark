#Requires -Version 5.1
<#
.SYNOPSIS
    Run parser_tests for any of the seven host parsers using its isolated venv.
.PARAMETER Parser
    Name of the parser: 'pymupdf', 'docling', 'mineru', 'paddleocr', 'liteparse',
    'unstructured', or 'xberg'.
.PARAMETER TestPath
    Optional path to a specific test file or directory within parser_tests/<parser>/.
    Defaults to all tests for the parser.
.PARAMETER VerboseOutput
    Pass -v to unittest for verbose output.
.EXAMPLE
    .\run_host_parser_tests.ps1 -Parser pymupdf
    .\run_host_parser_tests.ps1 -Parser mineru -VerboseOutput
    .\run_host_parser_tests.ps1 -Parser unstructured -TestPath test_preflight.py
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('pymupdf', 'docling', 'mineru', 'paddleocr', 'liteparse', 'unstructured', 'xberg')]
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

Write-Host ""
Write-Host "=== Running host parser tests: $Parser ===" -ForegroundColor Cyan
Write-Host "    Python : $Python"
Write-Host "    Tests  : $(if ($TestPath) { Join-Path $ParserTestsDir $TestPath } else { $ParserTestsDir })"
Write-Host ""

$env:PYTHONPATH = $RepoRoot

# Offline-mode env vars — applied to all parsers
$env:HF_HUB_OFFLINE       = '1'
$env:TRANSFORMERS_OFFLINE  = '1'
$env:DO_NOT_TRACK          = '1'
$env:SCARF_NO_ANALYTICS    = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'

# Parser-specific model environment (mirrors runtime_specs.py model_env with {model_root} resolved)
$ModelsRoot = Join-Path $RepoRoot "models"

switch ($Parser) {
    'mineru' {
        $ModelRoot = Join-Path $ModelsRoot 'mineru'
        $env:MINERU_MODEL_SOURCE       = 'local'
        $env:MINERU_TOOLS_CONFIG_JSON  = Join-Path $ModelRoot 'mineru.json'
        $env:HF_HOME                   = Join-Path $ModelRoot 'huggingface'
    }
    'paddleocr' {
        $env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
    }
    'unstructured' {
        $ModelRoot = Join-Path $ModelsRoot 'unstructured'
        $env:HF_HOME                          = Join-Path $ModelRoot 'huggingface'
        $env:HF_HUB_CACHE                     = Join-Path $ModelRoot 'huggingface\hub'
        $env:UNSTRUCTURED_DEFAULT_MODEL_NAME  = 'yolox'
        $env:UNSTRUCTURED_HI_RES_MODEL_NAME   = 'yolox'
        $env:OMP_THREAD_LIMIT                 = '1'
    }
    'xberg' {
        $ModelRoot = Join-Path $ModelsRoot 'xberg'
        $env:HF_HOME = Join-Path $ModelRoot 'huggingface'
    }
}

# Build unittest discover command
# Uses unittest discover to align with the Docker runner (run_parser_tests.py)
$UnittestArgs = @(
    '-m', 'unittest', 'discover',
    '--start-directory', $ParserTestsDir,
    '--pattern', 'test_*.py'
)

if ($TestPath) {
    # When a specific file/directory is given, discover from that sub-path
    $Target = Join-Path $ParserTestsDir $TestPath
    if (Test-Path $Target -PathType Leaf) {
        # Single file: discover from its directory so the top-level package path
        # is resolved correctly (absolute paths are not valid module names).
        $TargetDirectory = Split-Path $Target -Parent
        $TargetName      = Split-Path $Target -Leaf
        $UnittestArgs = @(
            '-m', 'unittest', 'discover',
            '--start-directory', $TargetDirectory,
            '--top-level-directory', $RepoRoot,
            '--pattern', $TargetName
        )
    } else {
        $UnittestArgs = @(
            '-m', 'unittest', 'discover',
            '--start-directory', $Target,
            '--pattern', 'test_*.py'
        )
    }
}

if ($VerboseOutput) {
    $UnittestArgs += '-v'
}

Invoke-NativeChecked -Cmd $Python -Args $UnittestArgs

Write-Host ""
Write-Host "=== Tests passed for $Parser ===" -ForegroundColor Green

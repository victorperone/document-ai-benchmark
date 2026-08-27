#Requires -Version 5.1
<#
.SYNOPSIS
    Verify that all parser venvs exist and are functional.

.DESCRIPTION
    Checks each venv's python.exe and confirms the expected top-level
    package is importable. Exits 0 if all pass, 1 if any fail.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName

$Checks = @(
    @{ Name = 'core';         Package = 'psutil' },
    @{ Name = 'pymupdf';      Package = 'pymupdf' },
    @{ Name = 'docling';      Package = 'docling' },
    @{ Name = 'liteparse';    Package = 'liteparse' },
    @{ Name = 'mineru';       Package = 'mineru' },
    @{ Name = 'paddleocr';    Package = 'paddleocr' },
    @{ Name = 'unstructured'; Package = 'unstructured' },
    @{ Name = 'xberg';        Package = 'xberg' }
)

$Failures = 0

foreach ($Check in $Checks) {
    $VenvPy = Join-Path $Root ".venvs\$($Check.Name)\Scripts\python.exe"

    if (-not (Test-Path $VenvPy)) {
        Write-Host "  FAIL  $($Check.Name)  python.exe not found at $VenvPy"
        $Failures++
        continue
    }

    $Result = & $VenvPy -c "import $($Check.Package)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAIL  $($Check.Name)  import $($Check.Package) failed: $Result"
        $Failures++
    } else {
        Write-Host "  OK    $($Check.Name)"
    }
}

Write-Host ""
if ($Failures -eq 0) {
    Write-Host "All $($Checks.Count) venvs OK."
    exit 0
} else {
    Write-Host "$Failures of $($Checks.Count) venvs FAILED."
    exit 1
}

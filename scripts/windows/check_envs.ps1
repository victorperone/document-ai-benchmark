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
    @{ Name = 'core'; Package = 'psutil'; Distribution = 'psutil'; Version = '7.2.2' },
    @{ Name = 'pymupdf'; Package = 'pymupdf'; Distribution = 'pymupdf4llm'; Version = '1.28.2' },
    @{ Name = 'docling'; Package = 'docling'; Distribution = 'docling'; Version = '2.122.0' },
    @{ Name = 'liteparse'; Package = 'liteparse'; Distribution = 'liteparse'; Version = '2.13.0' },
    @{ Name = 'mineru'; Package = 'mineru'; Distribution = 'mineru'; Version = '3.4.4' },
    @{ Name = 'paddleocr'; Package = 'paddleocr'; Distribution = 'paddleocr'; Version = '3.7.0' },
    @{ Name = 'unstructured'; Package = 'unstructured'; Distribution = 'unstructured'; Version = '0.27.1' },
    @{ Name = 'xberg'; Package = 'xberg'; Distribution = 'xberg'; Version = '1.0.14' },
    @{ Name = 'visual-enrichment'; Package = 'paddleocr'; Distribution = 'paddleocr'; Version = '3.7.0' }
)

$Failures = 0

foreach ($Check in $Checks) {
    $VenvPy = Join-Path $Root ".venvs\$($Check.Name)\Scripts\python.exe"

    if (-not (Test-Path $VenvPy)) {
        Write-Host "  FAIL  $($Check.Name)  python.exe not found at $VenvPy"
        $Failures++
        continue
    }

    $VersionScript = "import importlib.metadata as m; import $($Check.Package); actual=m.version('$($Check.Distribution)'); assert actual=='$($Check.Version)', f'expected $($Check.Version), got {actual}'; print(actual)"
    $Result = & $VenvPy -c $VersionScript 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAIL  $($Check.Name)  import $($Check.Package) failed: $Result"
        $Failures++
    } else {
        $PipCheck = & $VenvPy -m pip check 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  FAIL  $($Check.Name)  pip check failed: $PipCheck"
            $Failures++
        } else {
            Write-Host "  OK    $($Check.Name)  $Result"
        }
    }
}

foreach ($Executable in @('tesseract.exe', 'pdftoppm.exe', 'pdfinfo.exe')) {
    $Resolved = Get-Command $Executable -ErrorAction SilentlyContinue
    if ($null -eq $Resolved) {
        Write-Host "  FAIL  external executable not found: $Executable"
        $Failures++
    } else {
        Write-Host "  OK    external $Executable  $($Resolved.Source)"
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

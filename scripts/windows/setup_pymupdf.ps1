#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'

$null = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "[pymupdf] Python 3.12 nao esta disponivel. Instale Python 3.12 e tente novamente."
}

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\pymupdf'
$ReqFile = Join-Path $Root 'requirements\windows\pymupdf.txt'

Write-Host "[pymupdf] Setting up pymupdf venv..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPath)) {
    py -3.12 -m venv $VenvPath
}

& "$VenvPath\Scripts\python.exe" -m pip install -r $ReqFile

Write-Host "[pymupdf] Done."

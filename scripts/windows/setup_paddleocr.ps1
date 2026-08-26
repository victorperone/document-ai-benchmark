#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

$null = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "[paddleocr] Python 3.12 nao esta disponivel. Instale Python 3.12 e tente novamente."
}

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\paddleocr'
$ReqFile = Join-Path $Root 'requirements\windows\paddleocr.txt'

Write-Host "[paddleocr] Setting up paddleocr venv..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPath)) {
    Invoke-NativeChecked py @('-3.12', '-m', 'venv', $VenvPath)
}

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'install',
    'paddlepaddle==3.2.0',
    '-i', 'https://www.paddlepaddle.org.cn/packages/stable/cpu/'
)

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-m', 'pip', 'install', '-r', $ReqFile)

Write-Host "[paddleocr] Done."

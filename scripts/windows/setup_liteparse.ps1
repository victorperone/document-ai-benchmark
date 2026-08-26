#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

# liteparse 2.13.0 only ships a Windows cp311 wheel; use Python 3.11 for this venv.
$null = & py -3.11 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "[liteparse] Python 3.11 nao esta disponivel. Instale Python 3.11 e tente novamente."
}

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\liteparse'
$ReqFile = Join-Path $Root 'requirements\windows\liteparse.txt'

Write-Host "[liteparse] Setting up liteparse venv (Python 3.11)..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPath)) {
    Invoke-NativeChecked py @('-3.11', '-m', 'venv', $VenvPath)
}

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'install',
    'torch==2.9.1', 'torchvision==0.24.1',
    '--index-url', 'https://download.pytorch.org/whl/cpu'
)

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-m', 'pip', 'install', '-r', $ReqFile)

Write-Host "[liteparse] Done."

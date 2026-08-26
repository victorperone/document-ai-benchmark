#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

$null = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "[mineru] Python 3.12 nao esta disponivel. Instale Python 3.12 e tente novamente."
}

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\mineru'
$ReqFile = Join-Path $Root 'requirements\windows\mineru.txt'

Write-Host "[mineru] Setting up mineru venv..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPath)) {
    Invoke-NativeChecked py @('-3.12', '-m', 'venv', $VenvPath)
}

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'install',
    'torch==2.9.1', 'torchvision==0.24.1',
    '--index-url', 'https://download.pytorch.org/whl/cpu'
)

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-m', 'pip', 'install', '-r', $ReqFile)

Write-Host "[mineru] Done."

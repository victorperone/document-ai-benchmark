#Requires -Version 5.1
<#
.SYNOPSIS
    Create the Unstructured venv for host-runtime execution on Windows Server.

.DESCRIPTION
    Uses Python 3.12. Installs requirements/windows/unstructured.txt.
    Does NOT download layout models (run prepare_unstructured_models.ps1 for that).
    Does NOT install Tesseract or Poppler (must be pre-installed system-wide).
    Requires Windows Win32 long path support (LongPathsEnabled=1).

.PARAMETER Force
    Recreate the venv even if it already exists.
#>
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

Assert-WindowsLongPathsEnabled

$null = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "[unstructured] Python 3.12 nao esta disponivel. Instale Python 3.12 e tente novamente."
}

$Root    = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\unstructured'
$ReqFile  = Join-Path $Root 'requirements\windows\unstructured.txt'

Write-Host "[unstructured] Setting up unstructured venv..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPath)) {
    Invoke-NativeChecked py @('-3.12', '-m', 'venv', $VenvPath)
}

Invoke-PythonScriptChecked `
    -Python "$VenvPath\Scripts\python.exe" `
    -ScriptText $smoke

Write-Host "[unstructured] Running pip check..."
Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-m', 'pip', 'check')

# Dependency installation above may use the network.
# From this point forward validation must be offline.
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:SCARF_NO_ANALYTICS = '1'

Write-Host "[unstructured] Validating imports..."
$smoke = @'
import unstructured
from unstructured.partition.pdf import partition_pdf
import unstructured_inference
print("unstructured OK:", unstructured.__version__)
'@
Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-c', $smoke)

Write-Host "[unstructured] Done."

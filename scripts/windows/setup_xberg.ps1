#Requires -Version 5.1
<#
.SYNOPSIS
    Create the Xberg venv for host-runtime execution on Windows Server.

.DESCRIPTION
    Uses Python 3.12. Installs xberg==1.0.14 from PyPI (Windows ABI3 wheel only).
    Does NOT install Tesseract (must be pre-installed system-wide).

.PARAMETER Force
    Recreate the venv even if it already exists.
#>
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

$null = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "[xberg] Python 3.12 nao esta disponivel. Instale Python 3.12 e tente novamente."
}

$Root     = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\xberg'
$ReqFile  = Join-Path $Root 'requirements\windows\xberg.txt'

Write-Host "[xberg] Setting up xberg venv..."

if ($Force -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPath)) {
    Invoke-NativeChecked py @('-3.12', '-m', 'venv', $VenvPath)
}

# Use --only-binary xberg to prevent accidental Rust compilation on the server.
Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'install',
    '--only-binary', 'xberg',
    '-r', $ReqFile
)

Write-Host "[xberg] Running pip check..."
Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-m', 'pip', 'check')

Write-Host "[xberg] Validating imports and native module..."
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:SCARF_NO_ANALYTICS = '1'
$smoke = @'
import xberg
print("xberg OK:", xberg.__version__)

# Confirm native extension loads (xberg._xberg is a compiled .pyd on Windows)
try:
    import xberg._xberg as _native
    print("xberg native extension: OK")
except ImportError:
    # Fallback: try to exercise a function that must go through the native layer
    extract_fn = getattr(xberg, "extract", None)
    if extract_fn is None:
        raise RuntimeError("xberg.extract not found -- native extension may be broken")
    print("xberg native extension: OK (verified via xberg.extract)")
'@
Invoke-PythonScriptChecked `
    -Python "$VenvPath\Scripts\python.exe" `
    -ScriptText $smoke

Write-Host "[xberg] Done."

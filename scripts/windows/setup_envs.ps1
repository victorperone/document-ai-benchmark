#Requires -Version 5.1
<#
.SYNOPSIS
    Create all parser venvs for host-runtime execution on Windows Server.

.DESCRIPTION
    Runs each per-parser setup script in order. All parsers use CPU builds.
    Requires Python 3.12 installed and available via the Python Launcher (py -3.12).

.PARAMETER Force
    Recreate venvs that already exist.

.EXAMPLE
    .\setup_envs.ps1
    .\setup_envs.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'

$Scripts = $PSScriptRoot
$ForceArg = if ($Force) { @('-Force') } else { @() }

Write-Host "=== Setting up all parser venvs ==="

try { & "$Scripts\setup_core.ps1"      @ForceArg } catch { Write-Host "ERROR [core]: $_"; exit 1 }
try { & "$Scripts\setup_pymupdf.ps1"   @ForceArg } catch { Write-Host "ERROR [pymupdf]: $_"; exit 1 }
try { & "$Scripts\setup_docling.ps1"   @ForceArg } catch { Write-Host "ERROR [docling]: $_"; exit 1 }
try { & "$Scripts\setup_liteparse.ps1" @ForceArg } catch { Write-Host "ERROR [liteparse]: $_"; exit 1 }
try { & "$Scripts\setup_mineru.ps1"    @ForceArg } catch { Write-Host "ERROR [mineru]: $_"; exit 1 }
try { & "$Scripts\setup_paddleocr.ps1" @ForceArg } catch { Write-Host "ERROR [paddleocr]: $_"; exit 1 }

Write-Host "=== All venvs ready ==="

#Requires -Version 5.1
# Shared PowerShell helpers for setup scripts.
# Dot-source this file: . "$PSScriptRoot\_helpers.ps1"

function Invoke-NativeChecked {
    <#
    .SYNOPSIS
        Run a native command and throw if it exits non-zero.
        Required because $ErrorActionPreference='Stop' does not catch
        native command failures in PowerShell 5.1.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Cmd,
        [string[]]$Args = @()
    )
    & $Cmd @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command '$Cmd $($Args -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

function Assert-WindowsLongPathsEnabled {
    $RegistryPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem'
    $ValueName = 'LongPathsEnabled'

    try {
        $Value = (Get-ItemProperty `
            -Path $RegistryPath `
            -Name $ValueName `
            -ErrorAction Stop).$ValueName
    }
    catch {
        throw @"
Windows long path support is required for this environment.

Expected:
  HKLM\SYSTEM\CurrentControlSet\Control\FileSystem
  LongPathsEnabled = 1

Enable Win32 long paths on the Windows Server and restart the server
before running this setup again.
"@
    }

    if ($Value -ne 1) {
        throw @"
Windows long path support is disabled.

Expected:
  HKLM\SYSTEM\CurrentControlSet\Control\FileSystem
  LongPathsEnabled = 1

The Unstructured environment installs PyTorch, whose package contains
paths that can exceed the legacy Windows MAX_PATH limit.

Enable Win32 long paths and restart the Windows Server before retrying.
"@
    }
}

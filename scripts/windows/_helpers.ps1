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

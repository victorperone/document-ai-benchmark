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

function Invoke-PythonScriptChecked {
    <#
    .SYNOPSIS
        Execute multiline Python source without PowerShell 5.1 native
        argument quoting issues.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$ScriptText
    )

    $TempDir = [System.IO.Path]::GetTempPath()

    if (-not [System.IO.Directory]::Exists($TempDir)) {
        [System.IO.Directory]::CreateDirectory($TempDir) | Out-Null
    }

    $TempScript = Join-Path `
        $TempDir `
        ("document-ai-benchmark-" + [guid]::NewGuid().ToString("N") + ".py")

    try {
        $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText(
            $TempScript,
            $ScriptText,
            $Utf8NoBom
        )

        Invoke-NativeChecked $Python @($TempScript)
    }
    finally {
        if (Test-Path $TempScript) {
            Remove-Item -LiteralPath $TempScript -Force
        }
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

function Set-InstallingMarker {
    param([Parameter(Mandatory)][string]$VenvPath)

    if (-not (Test-Path -LiteralPath $VenvPath -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $VenvPath | Out-Null
    }

    Set-Content `
        -LiteralPath "$VenvPath\.installing" `
        -Value "" `
        -Encoding UTF8
}

function Remove-InstallingMarker {
    param([Parameter(Mandatory)][string]$VenvPath)
    $m = "$VenvPath\.installing"
    if (Test-Path -LiteralPath $m) { Remove-Item -LiteralPath $m -Force }
}

function Write-ReadyMarkerAtomically {
    param(
        [Parameter(Mandatory)][string]$VenvPath,
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$LockSha256
    )
    $payload = @{ schema_version = 1; python = $Python; lock_sha256 = $LockSha256 } |
        ConvertTo-Json -Compress
    $tmp = "$VenvPath\.ready.json.$([System.IO.Path]::GetRandomFileName()).tmp"
    Set-Content -LiteralPath $tmp -Value $payload -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination "$VenvPath\.ready.json" -Force
}

function Test-ReadyMarker {
    param([Parameter(Mandatory)][string]$VenvPath)
    $marker = "$VenvPath\.ready.json"
    if (-not (Test-Path -LiteralPath $marker)) { return $false }
    try {
        $null = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        return $true
    } catch {
        return $false
    }
}

function Invoke-ModelManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('Prepare', 'Verify')][string]$Mode,
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$Component,
        [Parameter(Mandatory)][string]$Version,
        [Parameter(Mandatory)][string]$ModelRoot,
        [string]$ManifestPath = ''
    )

    $RepoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
    $ManifestScript = Join-Path $RepoRoot 'scripts\model_manifest.py'
    $ManifestArgs = @(
        $ManifestScript,
        $Mode.ToLowerInvariant(),
        '--component', $Component,
        '--version', $Version,
        '--root', $ModelRoot
    )
    if ($ManifestPath -ne '') {
        $ManifestArgs += '--manifest', $ManifestPath
    }
    Invoke-NativeChecked -Cmd $Python -Args $ManifestArgs
}

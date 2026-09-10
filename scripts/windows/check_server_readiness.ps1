#Requires -Version 5.1
<# Native Windows Server release gate. It never reports PASS outside Windows. #>
[CmdletBinding()]
param(
    [string]$OutputRoot = 'outputs\deep_smoke',
    [switch]$VerboseOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RepoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$Timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd_HHmmss')
$ReportRoot = Join-Path $RepoRoot "logs\windows_readiness\$Timestamp"
New-Item -ItemType Directory -Force -Path $ReportRoot | Out-Null
$Transcript = Join-Path $ReportRoot 'readiness.log'
Start-Transcript -Path $Transcript -Force | Out-Null

$Failures = New-Object System.Collections.Generic.List[string]
$FunctionalSkipped = 0
$Parsers = @('pymupdf','docling','mineru','paddleocr','liteparse','unstructured','xberg')
$Commit = 'UNKNOWN'

# ---------------------------------------------------------------------------
# Invoke-ReadinessGate
#   Runs a command using System.Diagnostics.Process for reliable exit-code
#   capture, asynchronous stdout/stderr streaming to the log file and console,
#   and a structured return object so callers never parse Write-Host output.
#
# Returns [pscustomobject]@{ Name; Passed; ExitCode; LogPath }
# ---------------------------------------------------------------------------
function Invoke-ReadinessGate {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @(),
        [switch]$FunctionalTests
    )
    $SafeName = $Name -replace '[^A-Za-z0-9_.-]', '_'
    $LogPath  = Join-Path $ReportRoot "$SafeName.log"
    Write-Host "=== GATE: $Name ===" -ForegroundColor Cyan

    $ExitCode = -1
    try {
        $psi = [System.Diagnostics.ProcessStartInfo]::new()
        $psi.FileName               = $Command
        $psi.UseShellExecute        = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError  = $true
        $psi.CreateNoWindow         = $true

        # Build Arguments string compatible with Windows PowerShell 5.1 / .NET Framework.
        # ProcessStartInfo.ArgumentList only exists in .NET Core (PowerShell 7+).
        # Escape each argument: wrap in double quotes and escape internal double quotes.
        $escapedArgs = $Arguments | ForEach-Object {
            $a = $_ -replace '"', '\"'
            if ($a -match '[ \t]') { '"' + $a + '"' } else { $a }
        }
        $psi.Arguments = $escapedArgs -join ' '

        # Declare with $script: scope so event-handler scriptblocks can reference them.
        # In Windows PowerShell 5.1 scriptblock event handlers run in a child scope;
        # $script: is the only reliable way to share state with the enclosing function.
        $script:_gateLogWriter   = [System.IO.StreamWriter]::new($LogPath, $false, [System.Text.Encoding]::UTF8)
        $script:_gateLogWriter.AutoFlush = $true
        $script:_gateStdoutLines = New-Object System.Collections.Generic.List[string]

        $proc = [System.Diagnostics.Process]::new()
        $proc.StartInfo = $psi

        # Async stdout handler — mirrors to console and accumulates for FunctionalTests scan
        $stdoutHandler = {
            param($sender, $e)
            if ($null -ne $e.Data) {
                $script:_gateLogWriter.WriteLine($e.Data)
                Write-Host $e.Data
                $script:_gateStdoutLines.Add($e.Data)
            }
        }
        # Async stderr handler — mirrors to console and log
        $stderrHandler = {
            param($sender, $e)
            if ($null -ne $e.Data) {
                $script:_gateLogWriter.WriteLine($e.Data)
                Write-Host $e.Data -ForegroundColor DarkGray
            }
        }

        $proc.add_OutputDataReceived($stdoutHandler)
        $proc.add_ErrorDataReceived($stderrHandler)
        $proc.EnableRaisingEvents = $true

        $proc.Start() | Out-Null
        $proc.BeginOutputReadLine()
        $proc.BeginErrorReadLine()
        $proc.WaitForExit()

        $ExitCode = $proc.ExitCode
        $proc.Dispose()
        $script:_gateLogWriter.Close()

        if ($FunctionalTests) {
            foreach ($Line in $script:_gateStdoutLines) {
                if ([string]$Line -match 'skipped\s*=\s*([1-9][0-9]*)') {
                    $script:FunctionalSkipped += [int]$Matches[1]
                }
            }
        }
    }
    catch {
        try { $script:_gateLogWriter.Close() } catch {}
        $_ | Out-String | Add-Content -Path $LogPath -Encoding utf8
        $ExitCode = -1
    }

    $Passed = ($ExitCode -eq 0)
    $statusColor = if ($Passed) { 'Green' } else { 'Red' }
    $statusLabel  = if ($Passed) { 'PASS' } else { "FAIL exit=$ExitCode" }
    Write-Host "GATE_$SafeName=$statusLabel" -ForegroundColor $statusColor

    if (-not $Passed) {
        $script:Failures.Add("${Name}: exit code $ExitCode")
    }

    return [pscustomobject]@{
        Name    = $Name
        Passed  = $Passed
        ExitCode = $ExitCode
        LogPath = $LogPath
    }
}

try {
    $NativeWindows = (
        [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT -and
        [string]::IsNullOrEmpty($env:WSL_DISTRO_NAME)
    )
    if (-not $NativeWindows) {
        $Failures.Add('platform: readiness must run on native Windows Server, never WSL')
    }

    $Git = (Get-Command git.exe -ErrorAction SilentlyContinue)
    if ($null -eq $Git) { $Git = (Get-Command git -ErrorAction SilentlyContinue) }
    if ($null -eq $Git) {
        $Failures.Add('repository: git executable not found')
    } else {
        $CommitOutput = & $Git.Source -C $RepoRoot rev-parse HEAD 2>&1
        if ($LASTEXITCODE -eq 0) { $Commit = ([string]$CommitOutput).Trim() }
        else { $Failures.Add('repository: unable to resolve commit') }
        $Status = & $Git.Source -C $RepoRoot status --porcelain 2>&1
        if ($LASTEXITCODE -ne 0 -or @($Status).Count -ne 0) {
            $Failures.Add('repository: working tree must be clean')
        }
        @("COMMIT=$Commit", 'STATUS:', $Status) | Out-File `
            -FilePath (Join-Path $ReportRoot 'repository.log') -Encoding utf8
    }

    $PowerShell = Join-Path $PSHOME 'powershell.exe'
    $CorePython = Join-Path $RepoRoot '.venvs\core\Scripts\python.exe'
    if (-not (Test-Path $PowerShell -PathType Leaf)) {
        $Failures.Add("platform: Windows PowerShell 5.1 not found: $PowerShell")
    }
    if (-not (Test-Path $CorePython -PathType Leaf)) {
        $Failures.Add("environment: core Python not found: $CorePython")
    }

    # Snapshot TEMP before any gate runs so residues from any gate are captured.
    $TempDir = [System.IO.Path]::GetTempPath()
    $TempResiduePatterns = @(
        '^document-ai-',
        '^document-ai-visual-',
        '^unstructured_images_',
        '^mineru-verify-',
        '^visual_crops'
    )
    $TempBefore = @(Get-ChildItem -LiteralPath $TempDir -Force -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Name)

    if ($NativeWindows -and (Test-Path $PowerShell -PathType Leaf)) {
        Invoke-ReadinessGate -Name 'environment' -Command $PowerShell -Arguments @(
            '-NoProfile','-ExecutionPolicy','Bypass','-File',
            (Join-Path $PSScriptRoot 'check_envs.ps1')
        ) | Out-Null
        Invoke-ReadinessGate -Name 'models_verify' -Command $PowerShell -Arguments @(
            '-NoProfile','-ExecutionPolicy','Bypass','-File',
            (Join-Path $PSScriptRoot 'prepare_all_models.ps1'),'-Mode','Verify'
        ) | Out-Null
    }

    if ($NativeWindows -and (Test-Path $CorePython -PathType Leaf)) {
        Invoke-ReadinessGate -Name 'common_tests' -Command $CorePython -Arguments @(
            (Join-Path $RepoRoot 'scripts\run_tests.py')
        ) | Out-Null
    }

    $DeepSmokeGate = $null
    if ($NativeWindows -and (Test-Path $PowerShell -PathType Leaf)) {
        foreach ($Parser in $Parsers) {
            Invoke-ReadinessGate -Name "parser_tests_$Parser" -Command $PowerShell `
                -FunctionalTests -Arguments @(
                    '-NoProfile','-ExecutionPolicy','Bypass','-File',
                    (Join-Path $PSScriptRoot 'run_host_parser_tests.ps1'),
                    '-Parser',$Parser,'-VerboseOutput','-FunctionalTests'
                ) | Out-Null
        }
        $SmokeArgs = @(
            '-NoProfile','-ExecutionPolicy','Bypass','-File',
            (Join-Path $PSScriptRoot 'run_deep_smoke_all.ps1'),
            '-OutputRoot',$OutputRoot
        )
        if ($VerboseOutput) { $SmokeArgs += '-VerboseOutput' }
        $DeepSmokeGate = Invoke-ReadinessGate -Name 'deep_smoke' -Command $PowerShell `
            -Arguments $SmokeArgs -FunctionalTests
    }

    # Derive PARSERS_READY from DEEP_SMOKE_PARSER=PASS lines written to the gate's log file.
    # Use .Passed from the structured gate result — never parse Write-Host output.
    $Ready = New-Object System.Collections.Generic.List[string]
    if ($null -ne $DeepSmokeGate -and $DeepSmokeGate.Passed) {
        foreach ($Line in Get-Content -LiteralPath $DeepSmokeGate.LogPath -Encoding utf8) {
            if ([string]$Line -match '^DEEP_SMOKE_PARSER=PASS\s+parser=(\S+)') {
                $ParserName = $Matches[1].ToLower()
                if ($Parsers -contains $ParserName -and -not $Ready.Contains($ParserName)) {
                    $Ready.Add($ParserName)
                }
            }
        }
    }

    # Verify that all DOCUMENT_AI_OFFLINE_LOG env files are empty (no network calls)
    $OfflineLog = $env:DOCUMENT_AI_OFFLINE_LOG
    if (-not [string]::IsNullOrEmpty($OfflineLog) -and (Test-Path $OfflineLog -PathType Leaf)) {
        $OfflineLines = @(Get-Content -LiteralPath $OfflineLog -Encoding utf8 |
            Where-Object { $_.Trim() -ne '' })
        if ($OfflineLines.Count -gt 0) {
            $Failures.Add("offline_violation: $($OfflineLines.Count) network call(s) logged in DOCUMENT_AI_OFFLINE_LOG")
            $OfflineLines | Out-File (Join-Path $ReportRoot 'offline_violations.log') -Encoding utf8
        }
    }

    # Temp file residue check — run after all gates complete
    $TempAfter = @(Get-ChildItem -LiteralPath $TempDir -Force -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Name)
    $NewTempItems = $TempAfter | Where-Object { $TempBefore -notcontains $_ }
    $TempResidues = @($NewTempItems | Where-Object {
        $name = $_
        $TempResiduePatterns | Where-Object { $name -match $_ }
    })
    if ($TempResidues.Count -gt 0) {
        $Failures.Add("hygiene: $($TempResidues.Count) temporary item(s) remained in TEMP: $($TempResidues -join ', ')")
        $TempResidues | Out-File (Join-Path $ReportRoot 'hygiene_temp_residues.log') -Encoding utf8
    }

    $ResolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
        $OutputRoot
    } else { Join-Path $RepoRoot $OutputRoot }
    $HostOutput = Join-Path $ResolvedOutput 'host'
    if (Test-Path $HostOutput -PathType Container) {
        $Debris = @(Get-ChildItem -LiteralPath $HostOutput -Recurse -Force -File |
            Where-Object { $_.Name -match '\.(tmp|download|part)$' -or $_.FullName -match 'visual[_-]crops' })
        if ($Debris.Count -gt 0) {
            $Failures.Add("hygiene: $($Debris.Count) temporary/download file(s) remained")
            $Debris.FullName | Out-File (Join-Path $ReportRoot 'hygiene_failures.log') -Encoding utf8
        }
    }

    if ($NativeWindows) {
        $EscapedRoot = [regex]::Escape($RepoRoot)
        $Leaks = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ProcessId -ne $PID -and $_.CommandLine -match $EscapedRoot -and
                $_.CommandLine -match '\.venvs\\[^\\]+\\Scripts\\python\.exe'
            })
        if ($Leaks.Count -gt 0) {
            $Failures.Add("process_leaks: $($Leaks.Count) repository Python process(es) remained")
            $Leaks | Format-List ProcessId,ParentProcessId,CommandLine | Out-File `
                (Join-Path $ReportRoot 'process_leaks.log') -Encoding utf8
        }
    }

    if ($FunctionalSkipped -ne 0) {
        $Failures.Add("functional_tests: $FunctionalSkipped test(s) skipped")
    }

    $FailedParsers = @($Parsers | Where-Object { -not $Ready.Contains($_) })
    $Readiness = if ($NativeWindows -and $Failures.Count -eq 0 -and $Ready.Count -eq 7) {
        'PASS'
    } else { 'FAIL' }
    $Summary = @(
        "SERVER_READINESS=$Readiness",
        "COMMIT=$Commit",
        "PARSERS_READY=$($Ready -join ',')",
        "PARSERS_FAILED=$($FailedParsers -join ',')",
        "FUNCTIONAL_TESTS_SKIPPED=$FunctionalSkipped"
    )
    $Summary | Out-File (Join-Path $ReportRoot 'summary.txt') -Encoding ascii
    $Failures | Out-File (Join-Path $ReportRoot 'failures.txt') -Encoding utf8
    $Summary | ForEach-Object { Write-Host $_ }
    if ($Readiness -ne 'PASS') { exit 1 }
}
finally {
    Stop-Transcript | Out-Null
}

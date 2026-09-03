#Requires -Version 5.1
<# Native Windows Server release gate. It never reports PASS outside Windows. #>
[CmdletBinding()]
param(
    [string]$OutputRoot = 'outputs\deep_smoke',
    [ValidateRange(1, 86400)][int]$JobTimeoutSeconds = 3600,
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

function Invoke-ReadinessGate {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @(),
        [switch]$FunctionalTests
    )
    $SafeName = $Name -replace '[^A-Za-z0-9_.-]', '_'
    $LogPath = Join-Path $ReportRoot "$SafeName.log"
    Write-Host "=== GATE: $Name ===" -ForegroundColor Cyan
    try {
        $Output = & $Command @Arguments 2>&1
        $ExitCode = $LASTEXITCODE
        $Output | Out-File -FilePath $LogPath -Encoding utf8
        $Output | ForEach-Object { Write-Host $_ }
        if ($FunctionalTests) {
            foreach ($Line in $Output) {
                if ([string]$Line -match 'skipped\s*=\s*([1-9][0-9]*)') {
                    $script:FunctionalSkipped += [int]$Matches[1]
                }
            }
        }
        if ($ExitCode -ne 0) { throw "exit code $ExitCode" }
        Write-Host "GATE_$SafeName=PASS" -ForegroundColor Green
        return $true
    }
    catch {
        $_ | Out-String | Add-Content -Path $LogPath -Encoding utf8
        $script:Failures.Add("$Name`: $($_.Exception.Message)")
        Write-Host "GATE_$SafeName=FAIL $($_.Exception.Message)" -ForegroundColor Red
        return $false
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

    if ($NativeWindows -and (Test-Path $PowerShell -PathType Leaf)) {
        foreach ($Parser in $Parsers) {
            Invoke-ReadinessGate -Name "parser_tests_$Parser" -Command $PowerShell `
                -FunctionalTests -Arguments @(
                    '-NoProfile','-ExecutionPolicy','Bypass','-File',
                    (Join-Path $PSScriptRoot 'run_host_parser_tests.ps1'),
                    '-Parser',$Parser,'-VerboseOutput','-FunctionalTests',
                    '-FunctionalTimeoutSeconds',$JobTimeoutSeconds
                ) | Out-Null
        }
        $SmokeArgs = @(
            '-NoProfile','-ExecutionPolicy','Bypass','-File',
            (Join-Path $PSScriptRoot 'run_deep_smoke_all.ps1'),
            '-OutputRoot',$OutputRoot,
            '-JobTimeoutSeconds',$JobTimeoutSeconds
        )
        if ($VerboseOutput) { $SmokeArgs += '-VerboseOutput' }
        Invoke-ReadinessGate -Name 'deep_smoke' -Command $PowerShell `
            -Arguments $SmokeArgs -FunctionalTests | Out-Null
    }

    $ResolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
        $OutputRoot
    } else { Join-Path $RepoRoot $OutputRoot }
    $HostOutput = Join-Path $ResolvedOutput 'host'
    $Ready = New-Object System.Collections.Generic.List[string]
    foreach ($Parser in $Parsers) {
        $Profile = if ($Parser -eq 'pymupdf') { 'full_cpu_local_visual' } `
            elseif ($Parser -eq 'xberg') { 'full_cpu_layout' } else { 'full_cpu_local' }
        $Metrics = Join-Path $HostOutput "$Parser\deep_smoke\$Profile\metrics.json"
        if (Test-Path $Metrics -PathType Leaf) { $Ready.Add($Parser) }
    }

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

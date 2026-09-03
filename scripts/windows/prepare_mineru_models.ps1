#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Verify')][string]$Mode = 'Prepare',
    [switch]$Force,
    [string]$FixturePath = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"
if ($Mode -eq 'Verify' -and $Force) { throw '-Force is invalid with -Mode Verify.' }

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$Venv = Join-Path $Root '.venvs\mineru'
$Python = Join-Path $Venv 'Scripts\python.exe'
$Downloader = Join-Path $Venv 'Scripts\mineru-models-download.exe'
$MinerU = Join-Path $Venv 'Scripts\mineru.exe'
$ModelRoot = Join-Path $Root 'models\mineru'
$ConfigPath = Join-Path $ModelRoot 'mineru.json'
if ($FixturePath -eq '') { $FixturePath = Join-Path $Root 'fixtures\deep_smoke\deep_smoke.pdf' }
$env:MINERU_TOOLS_CONFIG_JSON = $ConfigPath
$env:HF_HOME = Join-Path $ModelRoot 'huggingface'
$env:BENCHMARK_MINERU_ROOT = $ModelRoot

if ($Mode -eq 'Prepare') {
    if ($Force -and (Test-Path $ModelRoot)) { Remove-Item -LiteralPath $ModelRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null
    Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
    Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
    Invoke-NativeChecked -Cmd $Downloader -Args @('-s', 'huggingface', '-m', 'pipeline')
    $RewriteConfig = @'
import json,os
from pathlib import Path
root=Path(os.environ["BENCHMARK_MINERU_ROOT"]).resolve()
config_path=Path(os.environ["MINERU_TOOLS_CONFIG_JSON"]).resolve()
config=json.loads(config_path.read_text(encoding="utf-8"))
models=config.get("models-dir")
if not isinstance(models,dict) or not models.get("pipeline"):
    raise RuntimeError("official downloader did not configure models-dir.pipeline")
for key,value in list(models.items()):
    path=Path(value).resolve()
    try: path.relative_to(root)
    except ValueError as exc: raise RuntimeError(f"{key} model escaped models/mineru: {path}") from exc
    models[key]=str(path)
config["model-source"]="local"
config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
'@
    Invoke-PythonScriptChecked -Python $Python -ScriptText $RewriteConfig
    Invoke-ModelManifest -Mode Prepare -Python $Python -Component 'mineru' `
        -Version 'pipeline-3.4.4' -ModelRoot $ModelRoot
}

$env:MINERU_MODEL_SOURCE = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'mineru' `
    -Version 'pipeline-3.4.4' -ModelRoot $ModelRoot
if (-not (Test-Path $FixturePath -PathType Leaf)) { throw "Smoke fixture not found: $FixturePath" }
$SmokeOutput = Join-Path ([System.IO.Path]::GetTempPath()) ('mineru-verify-' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $SmokeOutput | Out-Null
    Invoke-NativeChecked -Cmd $MinerU -Args @(
        '-p', $FixturePath, '-o', $SmokeOutput, '-b', 'pipeline', '-m', 'auto',
        '--formula', 'true', '--table', 'true'
    )
} finally {
    if (Test-Path $SmokeOutput) { Remove-Item -LiteralPath $SmokeOutput -Recurse -Force }
}
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'mineru' `
    -Version 'pipeline-3.4.4' -ModelRoot $ModelRoot

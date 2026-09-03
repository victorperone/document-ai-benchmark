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

    # Register help output before acquisition so it is recorded in the log
    Write-Host "=== mineru-models-download --help ===" -ForegroundColor Cyan
    & $Downloader '--help' 2>&1 | ForEach-Object { Write-Host $_ }

    Invoke-NativeChecked -Cmd $Downloader -Args @('-s', 'huggingface', '-m', 'pipeline')

    # Resolve effective snapshot and rewrite config with absolute Windows paths.
    # Handles two cases:
    #   (a) Downloader wrote a valid local path under HF_HOME → use as-is
    #   (b) Downloader wrote a Docker/container path (/models/mineru/...) → locate
    #       snapshot under HF_HOME and copy to models/mineru/pipeline_model
    $RewriteConfig = @'
import json, os, shutil, sys
from pathlib import Path

root = Path(os.environ["BENCHMARK_MINERU_ROOT"]).resolve()
hf_home = Path(os.environ["HF_HOME"]).resolve()
config_path = Path(os.environ["MINERU_TOOLS_CONFIG_JSON"]).resolve()

config = json.loads(config_path.read_text(encoding="utf-8"))
models = config.get("models-dir")
if not isinstance(models, dict) or not models.get("pipeline"):
    raise RuntimeError("official downloader did not configure models-dir.pipeline")

pipeline_raw = Path(models["pipeline"]).resolve()

# Detect Docker/container paths that will not exist on the host
docker_sentinel = "/models/mineru"
pipeline_str = str(Path(models["pipeline"]))
is_docker_path = pipeline_str.startswith(docker_sentinel) or not pipeline_raw.exists()

if is_docker_path:
    print(f"Downloader emitted container path '{pipeline_str}'; resolving from HF_HOME snapshots.")
    # Find snapshots under HF_HOME for mineru pipeline model
    candidate_dirs = sorted(
        hf_home.rglob("snapshots/*/pipeline"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    if not candidate_dirs:
        # Fall back: look for any directory named 'pipeline' under hf_home
        candidate_dirs = sorted(
            [d for d in hf_home.rglob("*") if d.is_dir() and d.name == "pipeline"],
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
    if len(candidate_dirs) == 0:
        raise RuntimeError("No pipeline snapshot found under HF_HOME after download.")
    if len(candidate_dirs) > 1:
        names = [str(c) for c in candidate_dirs]
        raise RuntimeError(
            f"Multiple pipeline snapshots found — cannot resolve without review: {names}"
        )
    src = candidate_dirs[0]
    dest = root / "pipeline_model"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=False)
    print(f"Copied snapshot {src} → {dest}")
    models["pipeline"] = str(dest)
else:
    # Downloader provided a real local path — just validate it stays inside root
    try:
        pipeline_raw.relative_to(root)
    except ValueError:
        raise RuntimeError(
            f"pipeline model path escaped models/mineru: {pipeline_raw}"
        )
    models["pipeline"] = str(pipeline_raw)

# Validate all declared model dirs exist, are non-empty, and have no symlink escapes
for key, value in list(models.items()):
    p = Path(value).resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{key} model escaped models/mineru: {p}") from exc
    if not p.exists():
        raise RuntimeError(f"{key} declared path does not exist: {p}")
    if not any(p.iterdir()):
        raise RuntimeError(f"{key} declared path is empty: {p}")
    # Check for symlinks that could escape the root
    real = p.resolve()
    try:
        real.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{key} symlink escapes models/mineru: {real}") from exc
    models[key] = str(p)

config["model-source"] = "local"
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Config rewritten successfully.")
'@
    Invoke-PythonScriptChecked -Python $Python -ScriptText $RewriteConfig
    Invoke-ModelManifest -Mode Prepare -Python $Python -Component 'mineru' `
        -Version 'pipeline-3.4.4' -ModelRoot $ModelRoot
}

$env:MINERU_MODEL_SOURCE = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'

# Verify mode must NEVER rewrite the config — validate only
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
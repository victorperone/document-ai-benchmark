#Requires -Version 5.1
<#
.SYNOPSIS
    Download and verify the YOLOX layout model for Unstructured hi_res strategy.

.DESCRIPTION
    This script runs ONCE before formal benchmark execution.
    It allows network access only for the duration of the download.
    After download, it verifies offline loading and writes a manifest with SHA-256.

    During the formal benchmark run, set:
        HF_HUB_OFFLINE=1  TRANSFORMERS_OFFLINE=1

.PARAMETER Force
    Re-download even if model files already exist.
#>
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"

$Root      = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath  = Join-Path $Root '.venvs\unstructured'
$ModelRoot = Join-Path $Root 'models\unstructured'
$HfHome    = Join-Path $ModelRoot 'huggingface'
$ManifestDir = Join-Path $ModelRoot 'manifests'

if (-not (Test-Path "$VenvPath\Scripts\python.exe")) {
    throw "[prepare_unstructured_models] Venv not found. Run setup_unstructured.ps1 first."
}

Write-Host "[prepare_unstructured_models] Creating model directories..."
New-Item -ItemType Directory -Force -Path $HfHome | Out-Null
New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null

$prepareScript = @"
import os, sys, json, hashlib, time
from pathlib import Path

model_root = Path(r'$ModelRoot')
hf_home    = Path(r'$HfHome')
force      = $(if ($Force) { 'True' } else { 'False' })

os.environ['HF_HOME'] = str(hf_home)
os.environ['HF_HUB_CACHE'] = str(hf_home / 'hub')
os.environ.pop('HF_HUB_OFFLINE', None)
os.environ.pop('TRANSFORMERS_OFFLINE', None)
os.environ['DO_NOT_TRACK'] = '1'
os.environ['SCARF_NO_ANALYTICS'] = '1'
os.environ['UNSTRUCTURED_DEFAULT_MODEL_NAME'] = 'yolox'
os.environ['UNSTRUCTURED_HI_RES_MODEL_NAME'] = 'yolox'

print("Downloading YOLOX model for Unstructured hi_res...")
try:
    from unstructured_inference.models.base import get_model
    model = get_model('yolox')
    print("Download: OK")
except Exception as exc:
    print(f"Download FAILED: {exc}", file=sys.stderr)
    sys.exit(1)

# Verify offline load
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
try:
    from unstructured_inference.models.base import get_model as get_model_offline
    model2 = get_model_offline('yolox')
    print("Offline model load: PASS")
except Exception as exc:
    print(f"Offline load FAILED: {exc}", file=sys.stderr)
    sys.exit(1)

# Compute SHA-256 of model files and write manifest
manifest = {'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'model': 'yolox', 'files': {}}
for f in sorted(hf_home.rglob('*.onnx')):
    digest = hashlib.sha256(f.read_bytes()).hexdigest()
    manifest['files'][str(f.relative_to(model_root))] = digest
manifest_path = Path(r'$ManifestDir') / 'unstructured_models.json'
manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(f"Manifest: {manifest_path}")
print("Unstructured model preparation: PASS")
"@

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @('-c', $prepareScript)

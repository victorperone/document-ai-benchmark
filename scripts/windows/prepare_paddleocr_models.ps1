#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Verify')][string]$Mode = 'Prepare',
    [switch]$Force
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\_helpers.ps1"
if ($Mode -eq 'Verify' -and $Force) { throw '-Force is invalid with -Mode Verify.' }

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$Python = Join-Path $Root '.venvs\paddleocr\Scripts\python.exe'
$ModelRoot = Join-Path $Root 'models\paddleocr\official_models'
$env:BENCHMARK_PADDLE_ROOT = $ModelRoot
$env:PYTHONPATH = $Root
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'

if ($Mode -eq 'Prepare') {
    if ($Force -and (Test-Path $ModelRoot)) { Remove-Item -LiteralPath $ModelRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null
    Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
    Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
    $Acquire = @'
import os
from pathlib import Path
from huggingface_hub import snapshot_download
root=Path(os.environ["BENCHMARK_PADDLE_ROOT"])
models=(
 "PP-DocLayout_plus-L","PP-DocBlockLayout","PP-LCNet_x1_0_doc_ori","UVDoc",
 "PP-OCRv5_server_det","PP-LCNet_x1_0_textline_ori","PP-OCRv5_server_rec",
 "PP-LCNet_x1_0_table_cls","SLANeXt_wired","SLANet_plus",
 "RT-DETR-L_wired_table_cell_det","RT-DETR-L_wireless_table_cell_det",
 "PP-FormulaNet_plus-L","PP-Chart2Table","PP-OCRv4_server_seal_det",
)
for name in models:
    destination=root/("PP-Chart2Table_safetensors" if name=="PP-Chart2Table" else name)
    snapshot_download(repo_id=f"PaddlePaddle/{name}",local_dir=destination)
'@
    Invoke-PythonScriptChecked -Python $Python -ScriptText $Acquire
    Invoke-ModelManifest -Mode Prepare -Python $Python -Component 'paddleocr' `
        -Version 'PPStructureV3-PP-OCRv5' -ModelRoot $ModelRoot
}

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'paddleocr' `
    -Version 'PPStructureV3-PP-OCRv5' -ModelRoot $ModelRoot
$Inference = @'
import os
from pathlib import Path
import numpy as np
from src.benchmark.config import get_profile
from src.parsers.paddleocr_v2 import build_pipeline,resolve_model_paths
root=Path(os.environ["BENCHMARK_PADDLE_ROOT"])
profile=get_profile("paddleocr","full_cpu_local")
pipeline=build_pipeline(resolve_model_paths(root,profile),profile)
try:
    results=list(pipeline.predict_iter(input=np.full((128,512,3),255,dtype=np.uint8)))
    if not results: raise RuntimeError("PPStructureV3 returned no smoke result")
finally:
    close=getattr(pipeline,"close",None)
    if callable(close): close()
print("PADDLEOCR_MODEL_INFERENCE=PASS")
'@
Invoke-PythonScriptChecked -Python $Python -ScriptText $Inference
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'paddleocr' `
    -Version 'PPStructureV3-PP-OCRv5' -ModelRoot $ModelRoot

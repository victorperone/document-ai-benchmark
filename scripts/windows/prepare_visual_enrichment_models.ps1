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
$Python = Join-Path $Root '.venvs\visual-enrichment\Scripts\python.exe'
$ModelRoot = Join-Path $Root 'models\visual-enrichment'
$env:BENCHMARK_VISUAL_ROOT = $ModelRoot
$env:HF_HUB_DISABLE_TELEMETRY = '1'
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
root=Path(os.environ["BENCHMARK_VISUAL_ROOT"])
for repo,relative in (
    ("PaddlePaddle/PP-OCRv6_server_det","paddleocr/PP-OCRv6_server_det"),
    ("PaddlePaddle/PP-OCRv6_server_rec","paddleocr/PP-OCRv6_server_rec"),
    ("HuggingFaceTB/SmolVLM-256M-Instruct","smolvlm/HuggingFaceTB--SmolVLM-256M-Instruct"),
):
    snapshot_download(repo_id=repo,local_dir=root/relative)
'@
    Invoke-PythonScriptChecked -Python $Python -ScriptText $Acquire
    Invoke-ModelManifest -Mode Prepare -Python $Python -Component 'visual_enrichment' `
        -Version 'PP-OCRv6+SmolVLM-256M' -ModelRoot $ModelRoot
}

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'visual_enrichment' `
    -Version 'PP-OCRv6+SmolVLM-256M' -ModelRoot $ModelRoot
$Inference = @'
import os
from pathlib import Path
import numpy as np
import torch
from PIL import Image
from paddleocr import PaddleOCR
from transformers import AutoModelForImageTextToText,AutoProcessor
root=Path(os.environ["BENCHMARK_VISUAL_ROOT"])
ocr=PaddleOCR(
 use_doc_orientation_classify=False,use_doc_unwarping=False,
 text_detection_model_dir=str(root/"paddleocr/PP-OCRv6_server_det"),
 text_recognition_model_dir=str(root/"paddleocr/PP-OCRv6_server_rec"),
)
list(ocr.predict(np.full((64,256,3),255,dtype=np.uint8)))
model_dir=root/"smolvlm/HuggingFaceTB--SmolVLM-256M-Instruct"
processor=AutoProcessor.from_pretrained(model_dir,local_files_only=True)
model=AutoModelForImageTextToText.from_pretrained(model_dir,local_files_only=True,dtype=torch.float32).to("cpu").eval()
messages=[{"role":"user","content":[{"type":"image"},{"type":"text","text":"Descreva."}]}]
prompt=processor.apply_chat_template(messages,add_generation_prompt=True,tokenize=False)
inputs=processor(text=prompt,images=[Image.new("RGB",(32,32),"white")],return_tensors="pt").to("cpu")
with torch.no_grad(): model.generate(**inputs,max_new_tokens=1,do_sample=False)
print("VISUAL_MODEL_INFERENCE=PASS")
'@
Invoke-PythonScriptChecked -Python $Python -ScriptText $Inference
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'visual_enrichment' `
    -Version 'PP-OCRv6+SmolVLM-256M' -ModelRoot $ModelRoot

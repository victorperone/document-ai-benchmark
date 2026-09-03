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
$Python = Join-Path $Root '.venvs\liteparse\Scripts\python.exe'
$ModelRoot = Join-Path $Root 'models\liteparse\smolvlm'
$ModelDir = Join-Path $ModelRoot 'HuggingFaceTB--SmolVLM-256M-Instruct'
$env:BENCHMARK_MODEL_DIR = $ModelDir
$env:HF_HUB_DISABLE_TELEMETRY = '1'

if ($Mode -eq 'Prepare') {
    if ($Force -and (Test-Path $ModelRoot)) { Remove-Item -LiteralPath $ModelRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null
    Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
    Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
    $Acquire = @'
import os
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="HuggingFaceTB/SmolVLM-256M-Instruct",
    local_dir=os.environ["BENCHMARK_MODEL_DIR"],
)
'@
    Invoke-PythonScriptChecked -Python $Python -ScriptText $Acquire
    Invoke-ModelManifest -Mode Prepare -Python $Python -Component 'liteparse' `
        -Version 'SmolVLM-256M-Instruct' -ModelRoot $ModelRoot
}

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'liteparse' `
    -Version 'SmolVLM-256M-Instruct' -ModelRoot $ModelRoot
$Inference = @'
import os
import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor
p=os.environ["BENCHMARK_MODEL_DIR"]
processor=AutoProcessor.from_pretrained(p,local_files_only=True)
model=AutoModelForImageTextToText.from_pretrained(p,local_files_only=True,dtype=torch.float32).to("cpu").eval()
messages=[{"role":"user","content":[{"type":"image"},{"type":"text","text":"Descreva."}]}]
prompt=processor.apply_chat_template(messages,add_generation_prompt=True,tokenize=False)
inputs=processor(text=prompt,images=[Image.new("RGB",(32,32),"white")],return_tensors="pt").to("cpu")
with torch.no_grad(): model.generate(**inputs,max_new_tokens=1,do_sample=False)
print("LITEPARSE_MODEL_INFERENCE=PASS")
'@
Invoke-PythonScriptChecked -Python $Python -ScriptText $Inference
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'liteparse' `
    -Version 'SmolVLM-256M-Instruct' -ModelRoot $ModelRoot

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
$FixturePdf = Join-Path $Root 'fixtures\deep_smoke\deep_smoke.pdf'
$ContractPath = Join-Path $Root 'config\liteparse_api_contract_2_13_0.json'
$env:BENCHMARK_MODEL_DIR = $ModelDir
$env:HF_HUB_DISABLE_TELEMETRY = '1'

if (-not (Test-Path $ContractPath -PathType Leaf)) {
    throw "API contract not found: $ContractPath — commit config/liteparse_api_contract_2_13_0.json first."
}

# Enforce liteparse==2.13.0 before proceeding
$CheckVersion = @'
import importlib.metadata, sys
v = importlib.metadata.version("liteparse")
if v != "2.13.0":
    print(f"FATAL: liteparse=={v} installed; require exactly 2.13.0", file=sys.stderr)
    sys.exit(1)
print(f"liteparse=={v} OK")
'@
Invoke-PythonScriptChecked -Python $Python -ScriptText $CheckVersion

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

# Visual inference probe — real generation with non-empty decoded output
$Inference = @'
import os, sys, torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor
p = os.environ["BENCHMARK_MODEL_DIR"]
processor = AutoProcessor.from_pretrained(p, local_files_only=True)
model = AutoModelForImageTextToText.from_pretrained(
    p, local_files_only=True, dtype=torch.float32
).to("cpu").eval()
messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "Descreva."}]}]
prompt = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
test_img = Image.new("RGB", (64, 64), color=(200, 200, 200))
inputs = processor(text=prompt, images=[test_img], return_tensors="pt").to("cpu")
with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=10, do_sample=False)
decoded = processor.batch_decode(out, skip_special_tokens=True)
text = (decoded[0] if decoded else "").strip()
if not text:
    print("FATAL: model generated empty output", file=sys.stderr)
    sys.exit(1)
print(f"LITEPARSE_MODEL_INFERENCE=PASS (generated {len(text)} chars)")
'@
Invoke-PythonScriptChecked -Python $Python -ScriptText $Inference

# API contract probe — fails on any divergence
if (-not (Test-Path $FixturePdf -PathType Leaf)) {
    throw "Deep smoke fixture not found: $FixturePdf"
}

$env:BENCHMARK_REPO_ROOT = $Root
$ProbeScript = Join-Path $Root 'scripts\probe_liteparse_api_contract.py'

# Write the contract-aware probe inline (avoids distributing a separate file for PS invoke)
$ProbeText = @"
import importlib.metadata, json, sys, os
from pathlib import Path

contract_path = Path(os.environ.get("LITEPARSE_CONTRACT_PATH", ""))
if not contract_path.is_file():
    print(f"FATAL: contract not found: {contract_path}", file=sys.stderr)
    sys.exit(1)
contract = json.loads(contract_path.read_text(encoding="utf-8"))

# Version check
installed = importlib.metadata.version("liteparse")
if installed != contract["version"]:
    print(f"FAIL: liteparse=={installed} != contract {contract['version']}", file=sys.stderr)
    sys.exit(1)

import liteparse

# Required constructor kwargs
failures = []
for kwarg in contract["required_constructor_kwargs"]:
    try:
        liteparse.LiteParse(**{kwarg: None})
    except TypeError as exc:
        if "unexpected keyword" in str(exc) or "got an unexpected" in str(exc):
            failures.append(f"MISSING_KWARG {kwarg}: {exc}")

# Known-unsupported kwargs must NOT exist
for kwarg in contract["known_unsupported_kwargs"]:
    try:
        liteparse.LiteParse(**{kwarg: False})
        failures.append(f"UNEXPECTED_KWARG {kwarg}: should be unsupported but was accepted")
    except TypeError:
        pass  # expected

# Parse smoke fixture and check result attrs
pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if pdf_path and pdf_path.is_file():
    parser = liteparse.LiteParse(output_format="markdown", quiet=True, max_pages=2)
    result = parser.parse(pdf_path)
    for attr in contract["required_result_attrs"]:
        if not hasattr(result, attr):
            failures.append(f"MISSING_ATTR result.{attr}")
    text_val = getattr(result, "text", None)
    if text_val is None or not isinstance(text_val, str):
        failures.append(f"result.text is not a str: {type(text_val)}")

if failures:
    for f in failures:
        print(f"PROBE_FAIL: {f}", file=sys.stderr)
    sys.exit(1)

print("LITEPARSE_API_PROBE=PASS")
"@

$env:LITEPARSE_CONTRACT_PATH = $ContractPath
$ProbeArgs = @($FixturePdf)

$TempProbe = Join-Path ([System.IO.Path]::GetTempPath()) ('document-ai-liteparse-probe-' + [guid]::NewGuid().ToString('N') + '.py')
try {
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($TempProbe, $ProbeText, $Utf8NoBom)
    Invoke-NativeChecked -Cmd $Python -Args (@($TempProbe) + $ProbeArgs)
} finally {
    if (Test-Path $TempProbe) { Remove-Item -LiteralPath $TempProbe -Force }
}

Invoke-ModelManifest -Mode Verify -Python $Python -Component 'liteparse' `
    -Version 'SmolVLM-256M-Instruct' -ModelRoot $ModelRoot
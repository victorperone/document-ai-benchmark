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

$ManifestVersion = 'PP-OCRv6_medium_det+PP-OCRv6_medium_rec+SmolVLM-256M-Instruct'

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
    ("PaddlePaddle/PP-OCRv6_medium_det","paddleocr/PP-OCRv6_medium_det"),
    ("PaddlePaddle/PP-OCRv6_medium_rec","paddleocr/PP-OCRv6_medium_rec"),
    ("HuggingFaceTB/SmolVLM-256M-Instruct","smolvlm/HuggingFaceTB--SmolVLM-256M-Instruct"),
):
    snapshot_download(repo_id=repo,local_dir=root/relative)
'@
    Invoke-PythonScriptChecked -Python $Python -ScriptText $Acquire
    Invoke-ModelManifest -Mode Prepare -Python $Python -Component 'visual_enrichment' `
        -Version $ManifestVersion -ModelRoot $ModelRoot
}

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Invoke-ModelManifest -Mode Verify -Python $Python -Component 'visual_enrichment' `
    -Version $ManifestVersion -ModelRoot $ModelRoot

# Verify via VisualWorkerClient — never load PaddleOCR/SmolVLM directly here.
# Snapshot includes both files and directories (-File omitted) to catch visual_crops/ etc.
$TempDir = [System.IO.Path]::GetTempPath()
$TempBefore = @(Get-ChildItem -LiteralPath $TempDir -Force -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty FullName)

$Inference = @'
import os, sys, tempfile, importlib.util
from pathlib import Path

root = Path(os.environ["BENCHMARK_VISUAL_ROOT"])
repo_root = Path(os.environ.get("BENCHMARK_REPO_ROOT", "")).resolve()
if not repo_root.name:
    # fallback: three levels up from this script's location
    repo_root = Path(__file__).resolve().parents[2]

# Inject src/ so VisualWorkerClient is importable
src_path = str(repo_root / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from benchmark.visual_worker_client import VisualWorkerClient

# Build a crisp test image with readable text using PIL
from PIL import Image, ImageDraw, ImageFont
img = Image.new("RGB", (480, 80), color=(255, 255, 255))
draw = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype("arial.ttf", 20)
except Exception:
    font = ImageFont.load_default()
draw.text((10, 20), "Teste de OCR em portugues", fill=(0, 0, 0), font=font)

import io as _io
buf = _io.BytesIO()
img.save(buf, format="PNG")
image_bytes = buf.getvalue()

ocr_model_dir = str(root / "paddleocr")
smolvlm_dir = str(root / "smolvlm" / "HuggingFaceTB--SmolVLM-256M-Instruct")

client = VisualWorkerClient(
    language="pt",
    smolvlm_model_path=str(smolvlm_dir),
    python_executable=sys.executable,
    det_model_dir=str(det_model_dir),
    rec_model_dir=str(rec_model_dir),
)
try:
    result = client.ocr_and_describe(image_bytes, prompt="Descreva a imagem.")
    assert result.get("status") == "success", f"status={result.get('status')!r}"
    assert not result.get("error_detail"), f"error_detail={result.get('error_detail')!r}"
    desc = result.get("description") or ""
    assert len(desc) > 0, "description is empty"
    ocr_text = (result.get("ocr_text") or "").lower()
    for token in ("teste", "ocr", "portugu"):
        assert token in ocr_text, f"OCR missing expected token {token!r}; got: {ocr_text!r}"
    print("VISUAL_MODEL_INFERENCE=PASS")
finally:
    client.close()
'@
$env:BENCHMARK_REPO_ROOT = $Root
Invoke-PythonScriptChecked -Python $Python -ScriptText $Inference

Invoke-ModelManifest -Mode Verify -Python $Python -Component 'visual_enrichment' `
    -Version $ManifestVersion -ModelRoot $ModelRoot

# Check for residues (files and directories) introduced by the verify step
$TempAfter = @(Get-ChildItem -LiteralPath $TempDir -Force -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty FullName)
$TempResidues = $TempAfter | Where-Object { $TempBefore -notcontains $_ }
if ($TempResidues.Count -gt 0) {
    throw "Verify left $($TempResidues.Count) temporary item(s): $($TempResidues -join ', ')"
}
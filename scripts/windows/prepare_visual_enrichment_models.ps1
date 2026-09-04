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
import base64
import io
import os
import sys
from pathlib import Path

root = Path(os.environ["BENCHMARK_VISUAL_ROOT"]).resolve()
repo_root = Path(os.environ["BENCHMARK_REPO_ROOT"]).resolve()

if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from PIL import Image, ImageDraw, ImageFont
from src.enrichment.visual_contract import VisualRequest
from src.enrichment.visual_worker_client import VisualWorkerClient

det_model_dir = (
    root
    / "paddleocr"
    / "PP-OCRv6_medium_det"
)

rec_model_dir = (
    root
    / "paddleocr"
    / "PP-OCRv6_medium_rec"
)

smolvlm_dir = (
    root
    / "smolvlm"
    / "HuggingFaceTB--SmolVLM-256M-Instruct"
)

for label, path in (
    ("det model", det_model_dir),
    ("rec model", rec_model_dir),
    ("SmolVLM", smolvlm_dir),
):
    if not path.is_dir():
        raise RuntimeError(
            f"{label} directory not found: {path}"
        )

img = Image.new(
    "RGB",
    (480, 80),
    color=(255, 255, 255),
)

draw = ImageDraw.Draw(img)

try:
    font = ImageFont.truetype(
        "arial.ttf",
        20,
    )
except Exception:
    font = ImageFont.load_default()

draw.text(
    (10, 20),
    "Teste de OCR em portugues",
    fill=(0, 0, 0),
    font=font,
)

buf = io.BytesIO()
img.save(buf, format="PNG")

request = VisualRequest(
    request_id="visual-model-verify",
    operation="ocr_and_describe",
    image_base64=base64.b64encode(
        buf.getvalue()
    ).decode("ascii"),
    language="por",
    prompt="Descreva a imagem.",
    page_number=1,
    region_id="visual-model-verify",
)

with VisualWorkerClient(
    language="por",
    smolvlm_model_path=str(smolvlm_dir),
    python_executable=sys.executable,
    det_model_dir=str(det_model_dir),
    rec_model_dir=str(rec_model_dir),
) as client:
    result = client.process(request)

assert result.status == "success", (
    f"status={result.status!r}; "
    f"error_detail={result.error_detail!r}"
)

assert not result.error_detail, (
    f"error_detail={result.error_detail!r}"
)

description = result.description or ""

assert description.strip(), (
    "description is empty"
)

ocr_text = (result.ocr_text or "").lower()

for token in (
    "teste",
    "ocr",
    "portugu",
):
    assert token in ocr_text, (
        f"OCR missing expected token "
        f"{token!r}; got: {ocr_text!r}"
    )

print("VISUAL_MODEL_INFERENCE=PASS")
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
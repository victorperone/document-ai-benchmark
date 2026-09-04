#Requires -Version 5.1
<#
.SYNOPSIS
    Acquire and certify all local artifacts required by the
    Unstructured full_cpu_local profile.

.DESCRIPTION
    Phase 1 allows network access and acquires:
      - spaCy en_core_web_sm 3.8.0
      - YOLOX layout model
      - Microsoft Table Transformer structure model

    Phase 2 starts a new Python process with Hugging Face offline
    variables and a socket guard. Every required resource must load.

    Phase 3 writes a manifest with versions, resource identities,
    persistent paths and SHA-256 digests.

.PARAMETER Force
    Delete the Unstructured model root and reinstall the pinned
    spaCy model before acquisition.
#>
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Verify')][string]$Mode = 'Prepare',
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\_helpers.ps1"

if ($Mode -eq 'Verify' -and $Force) {
    throw '-Force is invalid with -Mode Verify.'
}

Assert-WindowsLongPathsEnabled

# spaCy en_core_web_sm 3.8.0 — URL is from the official spaCy GitHub release.
# Hash is computed on download and recorded in the manifest (no secret value).
$SpacyModelUrl = (
    'https://github.com/explosion/spacy-models/releases/download/' +
    'en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl'
)

$Root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$VenvPath = Join-Path $Root '.venvs\unstructured'
$Python = Join-Path $VenvPath 'Scripts\python.exe'

$ModelRoot = Join-Path $Root 'models\unstructured'
$HfHome = Join-Path $ModelRoot 'huggingface'
$HfCache = Join-Path $HfHome 'hub'
$SpacyRoot = Join-Path $ModelRoot 'spacy'
$SpacyWheel = Join-Path $SpacyRoot 'en_core_web_sm-3.8.0-py3-none-any.whl'
$ManifestDir = Join-Path $ModelRoot 'manifests'
$ManifestPath = Join-Path $ManifestDir 'unstructured_models_manifest.json'
$CommonManifestPath = Join-Path $ModelRoot 'manifest.json'
$FixturePath = Join-Path $Root 'fixtures\deep_smoke\deep_smoke.pdf'

if (-not (Test-Path $Python -PathType Leaf)) {
    throw (
        "[unstructured-models] Venv not found. " +
        "Run setup_unstructured.ps1 first: $VenvPath"
    )
}

if ($Force) {
    if (Test-Path $ModelRoot) {
        Remove-Item -Recurse -Force $ModelRoot
    }
    Invoke-NativeChecked `
        -Cmd $Python `
        -Args @('-m', 'pip', 'uninstall', '--yes', 'en-core-web-sm')
}

if ($Mode -eq 'Prepare') {
    New-Item -ItemType Directory -Force -Path $HfCache   | Out-Null
    New-Item -ItemType Directory -Force -Path $SpacyRoot  | Out-Null
    New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null
}

$ManagedEnvironmentNames = @(
    'HF_HOME',
    'HF_HUB_CACHE',
    'HF_HUB_OFFLINE',
    'TRANSFORMERS_OFFLINE',
    'HF_HUB_DISABLE_TELEMETRY',
    'DO_NOT_TRACK',
    'SCARF_NO_ANALYTICS',
    'UNSTRUCTURED_DEFAULT_MODEL_NAME',
    'UNSTRUCTURED_HI_RES_MODEL_NAME',
    'BENCHMARK_UNSTRUCTURED_MODEL_ROOT',
    'BENCHMARK_UNSTRUCTURED_SPACY_WHEEL',
    'BENCHMARK_UNSTRUCTURED_SPACY_URL',
    'BENCHMARK_UNSTRUCTURED_MANIFEST',
    'BENCHMARK_DEEP_SMOKE_FIXTURE'
)

$OriginalEnvironment = @{}
foreach ($Name in $ManagedEnvironmentNames) {
    $OriginalEnvironment[$Name] = (
        [Environment]::GetEnvironmentVariable($Name, 'Process')
    )
}

try {
    $env:HF_HOME = $HfHome
    $env:HF_HUB_CACHE = $HfCache
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $env:DO_NOT_TRACK = '1'
    $env:SCARF_NO_ANALYTICS = '1'
    $env:UNSTRUCTURED_DEFAULT_MODEL_NAME = 'yolox'
    $env:UNSTRUCTURED_HI_RES_MODEL_NAME = 'yolox'

    $env:BENCHMARK_UNSTRUCTURED_MODEL_ROOT = $ModelRoot
    $env:BENCHMARK_UNSTRUCTURED_SPACY_WHEEL = $SpacyWheel
    $env:BENCHMARK_UNSTRUCTURED_SPACY_URL = $SpacyModelUrl
    $env:BENCHMARK_UNSTRUCTURED_MANIFEST = $ManifestPath

    if ($Mode -eq 'Verify') {
        $env:HF_HUB_OFFLINE = '1'
        $env:TRANSFORMERS_OFFLINE = '1'
        $env:BENCHMARK_DEEP_SMOKE_FIXTURE = $FixturePath
        Invoke-ModelManifest -Mode Verify -Python $Python -Component 'unstructured' `
            -Version 'full_cpu_local' -ModelRoot $ModelRoot `
            -ManifestPath $CommonManifestPath
        $VerifyInference = @'
import os,socket
from pathlib import Path
def blocked(*args,**kwargs): raise RuntimeError("network attempted during Unstructured Verify")
class BlockedSocket(socket.socket):
    def connect(self,*args,**kwargs): return blocked(*args,**kwargs)
    def connect_ex(self,*args,**kwargs): return blocked(*args,**kwargs)
socket.create_connection=blocked
socket.socket=BlockedSocket
from unstructured.partition.pdf import partition_pdf
fixture=Path(os.environ["BENCHMARK_DEEP_SMOKE_FIXTURE"]).resolve()
elements=partition_pdf(filename=str(fixture),strategy="hi_res",languages=["por","eng"],infer_table_structure=True,hi_res_model_name="yolox",ocr_agent="tesseract",table_ocr_agent="tesseract")
if not elements or not any(str(getattr(item,"text","")).strip() for item in elements):
    raise RuntimeError("Unstructured fixture inference produced no text")
print("UNSTRUCTURED_MODEL_INFERENCE=PASS")
'@
        Invoke-PythonScriptChecked -Python $Python -ScriptText $VerifyInference
        Invoke-ModelManifest -Mode Verify -Python $Python -Component 'unstructured' `
            -Version 'full_cpu_local' -ModelRoot $ModelRoot `
            -ManifestPath $CommonManifestPath
        Write-Host '[unstructured-models] Verify completed successfully.' -ForegroundColor Green
        return
    }

    # ============================================================
    # PHASE 1 - acquisition. Network may be available.
    # ============================================================
    Remove-Item Env:HF_HUB_OFFLINE      -ErrorAction SilentlyContinue
    Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "[unstructured-models] PHASE 1 - acquisition" -ForegroundColor Cyan

    $AcquireSpacyWheel = @'
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

url = os.environ["BENCHMARK_UNSTRUCTURED_SPACY_URL"]
destination = Path(os.environ["BENCHMARK_UNSTRUCTURED_SPACY_WHEEL"])
destination.parent.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if destination.is_file():
    print(f"spaCy wheel already present: {destination}")
    print(f"spaCy wheel SHA-256: {sha256(destination)}")
else:
    temporary = destination.with_suffix(".download")
    if temporary.exists():
        temporary.unlink()

    print(f"Downloading: {url}")

    with urllib.request.urlopen(url, timeout=120) as response:
        with temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)

    temporary.replace(destination)
    print(f"spaCy wheel SHA-256: {sha256(destination)}")

print("spaCy acquisition: PASS")
'@

    Invoke-PythonScriptChecked `
        -Python $Python `
        -ScriptText $AcquireSpacyWheel

    Invoke-NativeChecked `
        -Cmd $Python `
        -Args @(
            '-m', 'pip', 'install',
            '--no-deps',
            '--force-reinstall',
            $SpacyWheel
        )

    Invoke-NativeChecked `
        -Cmd $Python `
        -Args @('-m', 'pip', 'check')

    $AcquireModels = @'
from __future__ import annotations

from pathlib import Path

from unstructured.nlp.tokenize import sent_tokenize
from unstructured_inference.models.base import get_model
from unstructured_inference.models.tables import load_agent, tables_agent

sentences = sent_tokenize(
    "This is a model acquisition smoke. "
    "The sentence boundary must be available."
)
if not sentences:
    raise RuntimeError("spaCy sentence tokenizer returned no sentences")

layout = get_model("yolox")
layout_path = Path(layout.model_path)
if not layout_path.is_file():
    raise RuntimeError(f"YOLOX model path does not exist: {layout_path}")

load_agent()

if tables_agent.model is None:
    raise RuntimeError("Table Transformer model was not initialized")

if tables_agent.feature_extractor is None:
    raise RuntimeError(
        "Table Transformer feature extractor was not initialized"
    )

print("spaCy model: PASS")
print("YOLOX model:", layout_path)
print("Table model: PASS")
print("UNSTRUCTURED MODEL ACQUISITION: PASS")
'@

    Invoke-PythonScriptChecked `
        -Python $Python `
        -ScriptText $AcquireModels

    # ============================================================
    # PHASE 2 - independent offline validation.
    # ============================================================
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'

    Write-Host ""
    Write-Host "[unstructured-models] PHASE 2 - offline validation" -ForegroundColor Cyan

    $OfflineValidation = @'
from __future__ import annotations

import socket
from pathlib import Path


def blocked(*args, **kwargs):
    raise RuntimeError(
        "Network access attempted during offline validation"
    )


class BlockedSocket(socket.socket):
    def connect(self, *args, **kwargs):
        return blocked(*args, **kwargs)

    def connect_ex(self, *args, **kwargs):
        return blocked(*args, **kwargs)


socket.create_connection = blocked
socket.socket = BlockedSocket

import spacy

from unstructured.nlp.tokenize import sent_tokenize
from unstructured_inference.models.base import get_model
from unstructured_inference.models.tables import load_agent, tables_agent

nlp = spacy.load(
    "en_core_web_sm",
    exclude=["ner", "lemmatizer", "attribute_ruler"],
)
if nlp.meta.get("version") != "3.8.0":
    raise RuntimeError(
        "Unexpected spaCy model version: "
        f"{nlp.meta.get('version')!r}"
    )

if not sent_tokenize("Offline validation. Second sentence."):
    raise RuntimeError("spaCy tokenizer unavailable offline")

layout = get_model("yolox")
if not Path(layout.model_path).is_file():
    raise RuntimeError("YOLOX model unavailable offline")

load_agent()
if tables_agent.model is None:
    raise RuntimeError("Table Transformer model unavailable offline")
if tables_agent.feature_extractor is None:
    raise RuntimeError(
        "Table Transformer processor unavailable offline"
    )

print("spaCy offline load: PASS")
print("YOLOX offline load: PASS")
print("Table Transformer offline load: PASS")
print("UNSTRUCTURED OFFLINE VALIDATION: PASS")
'@

    Invoke-PythonScriptChecked `
        -Python $Python `
        -ScriptText $OfflineValidation

    # ============================================================
    # PHASE 3 - deterministic manifest.
    # ============================================================
    Write-Host ""
    Write-Host "[unstructured-models] PHASE 3 - manifest" -ForegroundColor Cyan

    $BuildManifest = @'
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from unstructured_inference.models.base import get_model
from unstructured_inference.models.tables import (
    DEFAULT_MODEL as TABLE_MODEL,
    load_agent,
)

model_root = Path(os.environ["BENCHMARK_UNSTRUCTURED_MODEL_ROOT"]).resolve()
manifest_path = Path(os.environ["BENCHMARK_UNSTRUCTURED_MANIFEST"]).resolve()
spacy_wheel = Path(os.environ["BENCHMARK_UNSTRUCTURED_SPACY_WHEEL"]).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_to_model_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(model_root).as_posix()
    except ValueError as exc:
        raise RuntimeError(
            f"Artifact is outside model root: {path}"
        ) from exc


def file_record(path: Path) -> dict:
    return {
        "path": relative_to_model_root(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def tree_digest(root: Path):
    digest = hashlib.sha256()
    count = 0
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.parts
        and item.suffix.lower() not in {".pyc", ".pyo"}
    ):
        relative = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


layout = get_model("yolox")
layout_path = Path(layout.model_path).resolve()
if not layout_path.is_file():
    raise RuntimeError(f"YOLOX file missing: {layout_path}")

load_agent()

table_root_name = "models--microsoft--table-transformer-structure-recognition"

table_files = sorted(
    path
    for path in model_root.rglob("*")
    if path.is_file()
    and table_root_name in path.as_posix()
    and path.suffix.lower() in {".json", ".bin", ".safetensors", ".txt", ".model"}
)

if not table_files:
    raise RuntimeError("No persistent Table Transformer files were found")

if not any(
    path.suffix.lower() in {".bin", ".safetensors"} for path in table_files
):
    raise RuntimeError("Table Transformer weights were not found")

if not spacy_wheel.is_file():
    raise RuntimeError(f"spaCy wheel missing: {spacy_wheel}")

spec = importlib.util.find_spec("en_core_web_sm")
if spec is None or not spec.submodule_search_locations:
    raise RuntimeError("Installed spaCy model was not found")

spacy_package_root = Path(
    next(iter(spec.submodule_search_locations))
).resolve()
spacy_tree_sha, spacy_file_count = tree_digest(spacy_package_root)

manifest = {
    "schema_version": 1,
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "offline_validation": True,
    "packages": {
        name: metadata.version(name)
        for name in (
            "unstructured",
            "unstructured-inference",
            "spacy",
            "en-core-web-sm",
            "transformers",
            "onnxruntime",
        )
    },
    "resources": {
        "layout": {
            "name": "yolox",
            "repository": "unstructuredio/yolo_x_layout",
            "file": file_record(layout_path),
        },
        "table": {
            "name": TABLE_MODEL,
            "files": [file_record(path) for path in table_files],
        },
        "spacy": {
            "name": "en_core_web_sm",
            "version": metadata.version("en-core-web-sm"),
            "wheel": file_record(spacy_wheel),
            "installed_package_root": str(spacy_package_root),
            "installed_tree_sha256": spacy_tree_sha,
            "installed_file_count": spacy_file_count,
        },
    },
}

manifest_path.parent.mkdir(parents=True, exist_ok=True)
temporary = manifest_path.with_suffix(".json.tmp")
temporary.write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    encoding="utf-8",
)
temporary.replace(manifest_path)

print("Manifest:", manifest_path)
print("Layout file:", layout_path)
print("Table files:", len(table_files))
print("spaCy files:", spacy_file_count)
print("UNSTRUCTURED MODEL MANIFEST: PASS")
'@

    Invoke-PythonScriptChecked `
        -Python $Python `
        -ScriptText $BuildManifest

    if (-not (Test-Path $ManifestPath -PathType Leaf)) {
        throw (
            "[unstructured-models] Manifest was not created: " +
            $ManifestPath
        )
    }

    Invoke-ModelManifest -Mode Prepare -Python $Python -Component 'unstructured' `
        -Version 'full_cpu_local' -ModelRoot $ModelRoot `
        -ManifestPath $CommonManifestPath
    Invoke-ModelManifest -Mode Verify -Python $Python -Component 'unstructured' `
        -Version 'full_cpu_local' -ModelRoot $ModelRoot `
        -ManifestPath $CommonManifestPath

    Write-Host ""
    Write-Host "[unstructured-models] Completed successfully." -ForegroundColor Green
    Write-Host "Manifest: $ManifestPath"
}
finally {
    foreach ($Name in $ManagedEnvironmentNames) {
        $OriginalValue = $OriginalEnvironment[$Name]

        if ($null -eq $OriginalValue) {
            Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path "Env:$Name" -Value $OriginalValue
        }
    }
}

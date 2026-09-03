# Runtime Validation Runbook

This document covers how to run, interpret, and maintain the benchmark runtime
validation campaign. It assumes the codebase is in **PRE-RUNTIME CODE READINESS:
COMPLETE** state — all tests pass, no containers need to run.

---

## Prerequisites

- Docker Engine running (`docker info`)
- Docker Compose available (`docker compose version`)
- All models that a suite requires must be downloaded **before** launching that
  suite. See [Known model blockers](#known-model-blockers).
- Python 3.10+
- All project dependencies installed (`pip install -r requirements.txt`)

---

## How to run the regression suite

Verifies that all code-level contracts hold without launching any container:

```bash
python scripts/run_tests.py
echo $?   # must be 0
```

---

## How to consult available suites

```bash
python scripts/show_benchmark_plan.py
```

Suites defined in `config/benchmark_profiles.json`:

| Suite | Purpose |
|---|---|
| `smoke` | Integration health-check — 4 parsers, simplest profiles |
| `default` | Primary benchmark (identical to `ocr_primary`) |
| `ocr_primary` | Primary OCR benchmark (explicit historical name) |
| `full_corpus` | Expanded benchmark — 8 parser/profile pairs |
| `diagnostic_ocr` | Force-OCR diagnostic across 3 parsers |
| `visual_ablation` | Docling + PaddleOCR visual feature ablation |
| `windows_all_features_host` | Windows Server nativo, sete parsers e todos os artefatos |

---

## How to run a smoke dry-run

Verifies the job plan without executing containers:

```bash
python scripts/run_batch.py \
  --suite smoke \
  --input-dir data/raw/batch \
  --dry-run
```

## Native Windows Server validation

The Windows host flow is separate from the Docker campaign above. WSL can run
the common/unit checks, but it cannot certify native Windows readiness.

On Windows Server, prepare model files while network access is explicitly
allowed:

```powershell
.\scripts\windows\setup_envs.ps1
.\scripts\windows\prepare_all_models.ps1 -Mode Prepare
```

Then enforce the offline release gate:

```powershell
.\scripts\windows\check_server_readiness.ps1 -VerboseOutput
```

The gate enables one real, offline fixture conversion in every isolated parser
test suite and then repeats the complete seven-parser deep smoke. A skipped
functional test or a changed model manifest makes readiness fail.

Useful non-mutating checks and the fresh default run are:

```powershell
.\scripts\windows\run_all_features_host.ps1 -DryRun
.\scripts\windows\run_all_features_host.ps1 -PreflightOnly
.\scripts\windows\run_all_features_host.ps1
```

Use `-Resume` only when intentional. The native status and evidence contract is
maintained in [WINDOWS_SERVER_HOST_STATUS.md](WINDOWS_SERVER_HOST_STATUS.md).

---

## How to run the default suite

```bash
# Equivalent: omitting --suite defaults to 'default'
python scripts/run_batch.py \
  --input-dir data/raw/batch

# Explicit:
python scripts/run_batch.py \
  --suite default \
  --input-dir data/raw/batch
```

---

## How to run the runtime campaign in plan mode

Prints all phases without starting any container:

```bash
python scripts/run_runtime_campaign.py
# or equivalently:
python scripts/run_runtime_campaign.py --plan
echo $?   # must be 0
```

Expected output: 10 phases listed in order, zero containers started.

---

## How to execute a single campaign phase

```bash
python scripts/run_runtime_campaign.py \
  --phase smoke_limit1 \
  --execute
```

The runner calls `scripts/run_batch.py` internally for three sequential steps:

1. **Preflight** (`--preflight`) — validates Docker, models, and infrastructure
2. **Forced fresh execution** (`--force`) — runs all containers unconditionally,
   producing fresh outputs for this phase; does not reuse prior outputs
3. **Read-only resume check** (`--resume-check`) — verifies that every job is
   now reusable (would be SKIP in a future resume); exits 1 if any job is
   still pending, meaning the outputs produced in step 2 are not valid

---

## How to execute the full campaign

```bash
python scripts/run_runtime_campaign.py --execute
```

The campaign stops on the first failing phase. Remaining phases are recorded
as `NOT_RUN`. A JSON + Markdown report is written to `logs/`.

---

## How to prepare models manually when preflight requests it

Preflight will report which models are missing. Follow the installation
instructions for each parser:

- **pymupdf/rapidtess**: Tesseract OCR — `apt install tesseract-ocr`
- **docling/rapidocr**: automatically downloaded on first run inside the
  container if internet access is available
- **mineru**: follow MinerU model download instructions in `docker/`
- **paddleocr**: see [Known model blockers](#known-model-blockers) for models
  that require manual steps

Do **not** modify `config/benchmark_profiles.json` profiles to work around
missing models. If a model is missing, the phase reports `FAIL` and the
campaign stops — that is expected behavior.

---

## How to interpret campaign phase statuses

| Status | Meaning |
|---|---|
| `PASS` | Preflight, execution, and resume check all returned exit 0 |
| `FAIL` | One of the three steps returned a non-zero exit code |
| `NOT_RUN` | Phase was not reached because a prior phase failed |
| `EXPECTED_BLOCK` | Manual annotation: failure was expected (e.g. model not installed) |
| `ENVIRONMENT_BLOCK` | Manual annotation: environment issue (OOM, disk full, etc.) |
| `IMPLEMENTATION_FAIL` | Manual annotation: confirmed code bug |

`EXPECTED_BLOCK`, `ENVIRONMENT_BLOCK`, and `IMPLEMENTATION_FAIL` are manual
annotations for review. The runner only writes `PASS`, `FAIL`, and `NOT_RUN`
automatically.

---

## How to collect logs and results

After execution:

- **Campaign report**: `logs/runtime_campaign_<timestamp>.json` and `.md`
- **Batch logs** (per phase): `logs/batch_<timestamp>.log`
- **Results per phase**: `logs/batch_<timestamp>_results.jsonl`
- **Execution output**: `outputs/_runtime/<phase_name>/`

---

## What not to alter during a campaign

- `config/benchmark_profiles.json` — changing suites or profiles mid-campaign
  invalidates comparisons
- `config/runtime_campaign.json` — changing phase names or output roots
  invalidates resume logic
- Adapter scripts under `src/parsers/` — must remain unchanged
- Model weights already loaded into containers — do not update models between
  phases

---

## Known model blockers

The following models are not auto-downloaded and require manual setup before
the corresponding suite/profile can pass preflight:

| Model | Used by | Notes |
|---|---|---|
| `PP-FormulaNet_plus-L` | `paddleocr/mvp_structured`, `paddleocr/full` | Download manually per PaddleOCR docs |
| `PP-Chart2Table` | `paddleocr/ocr_structured_visual`, `paddleocr/full` | Experimental; may not be available |
| `UVDoc` | `paddleocr/full` (document unwarping) | Requires separate model archive |

These are documented as **environment blockers**, not code bugs. Do not
hardcode them as permanent failures in unit tests — the environment may change.

---

## Suite readiness at runbook creation

| Suite | Code + Tests | Runtime |
|---|---|---|
| smoke | COMPLETE | PENDING |
| default | COMPLETE | PENDING |
| ocr_primary | COMPLETE | PENDING |
| full_corpus | COMPLETE | PENDING |
| diagnostic_ocr | COMPLETE | PENDING |
| visual_ablation | COMPLETE | PENDING |

**PRE-RUNTIME CODE READINESS: COMPLETE**
**RUNTIME VALIDATION: PENDING**

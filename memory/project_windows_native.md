---
name: project-windows-native
description: Runtime nativo Windows Server 2025; branch server/windows-native; venvs por parser; servidor só para homologação
metadata:
  type: project
---

Runtime `host` implementado para executar todos os parsers diretamente no Windows Server 2025 sem Docker.

**Why:** servidor de homologação roda Windows Server 2025, sem Docker instalado.

**How to apply:** ao sugerir alterações de execução, considerar os dois runtimes: `docker` (padrão) e `host` (novo).

## Estado atual

Branch: `server/windows-native`

Testes: 540 passing, 16 failing pré-existentes (`_ExpandedSuiteContractBase` sem `suite_name`).

## Arquitetura

- `.venvs/core`, `.venvs/pymupdf`, `.venvs/docling`, `.venvs/mineru`, `.venvs/paddleocr`, `.venvs/liteparse`
- `python -m src.parsers.<parser>_v2` como modo de execução host
- PATH injection via `_build_host_environment(parser_name, extra_env)` em `run_batch.py`
- `BENCHMARK_RUNTIME` env var sobrescreve default do `--runtime`

## Módulos novos

- `src/benchmark/execution_paths.py` — resolução de paths para ambos os runtimes
- `src/benchmark/external_tools.py` — resolução do Tesseract no Windows
- `src/benchmark/runtime_specs.py` — `PARSER_RUNTIME_SPECS` com module, model_args, model_env, **preflight_kwargs**

## Decisões relevantes

- `preflight_kwargs` em `PARSER_RUNTIME_SPECS` é a fonte única da interface de preflight por parser (não hardcoded em `parser_preflight.py`)
- `_build_host_environment()` centraliza PATH injection; usado em execução, source inventory e preflight
- Scripts PS usam `py -3.12` explicitamente (Python 3.12.10 no Windows Server 2025)
- Scripts filhos PS usam `throw` (não `exit 1`) para propagar falha ao `setup_envs.ps1`
- Nenhum setup atualiza pip automaticamente
- MinerU: torch==2.9.1, torchvision==0.24.1 fixados; CPU only
- PaddleOCR: paddlepaddle==3.2.0 do índice oficial Paddle; CPU only
- GPU removido desta versão inicial

## Arquivos PS (scripts/windows/)

setup_core.ps1, setup_pymupdf.ps1, setup_docling.ps1, setup_liteparse.ps1, setup_mineru.ps1, setup_paddleocr.ps1, setup_envs.ps1, check_envs.ps1

## Requirements Windows (requirements/windows/)

core.txt, pymupdf.txt, docling.txt, liteparse.txt, mineru.txt, paddleocr.txt

## Manifest por batch

`logs/batch_{ts}_manifest.json` com execution_runtime, host_os, orchestrator_python.

## Ambiente de dev vs produção

Dev: WSL (Linux, Python 3.14) — testes rodam com caminhos `bin/python`.
Prod: Windows Server 2025, Python 3.12.10 — caminhos `Scripts\python.exe`.
`execution_paths.py` detecta via `sys.platform == "win32"`.

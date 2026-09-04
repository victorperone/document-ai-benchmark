# Windows Server Host Runtime — Status canônico

## Estado atual

**STATUS DO CÓDIGO: EM CORREÇÃO — BUGS CRÍTICOS IDENTIFICADOS**
**HOMOLOGAÇÃO NO WINDOWS SERVER NATIVO: PENDENTE**

> **Rodada de análise — 2026-09-04**
> Preflight e execução de teste funcionam no servidor (branch `perf/parser-runtime-optimization`).
> Uma revisão completa do código-fonte identificou **11 bugs críticos** de perda de dados e comportamento
> incorreto. Antes da próxima campanha de validação formal, os bugs listados na seção
> "Análise de qualidade — bugs críticos identificados" abaixo devem ser corrigidos.
> Ver também: `docs/PLANO_CORRETIVO_DESENVOLVEDOR.md` para detalhes e priorização.

Este é o documento canônico da execução host. A implementação e os testes
portáveis são feitos no WSL; nenhum resultado obtido no WSL certifica o runtime
Windows. `SERVER_READINESS=PASS` só é válido quando emitido por
`scripts\windows\check_server_readiness.ps1` em Windows Server nativo.

A branch e o commit não são fixados neste documento. Registre o estado real:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
```

O gate recusa árvore de trabalho suja e inclui o SHA executado no relatório.

## Objetivo e política offline

A suíte Windows compara sete conversores locais para documentos heterogêneos:
texto digital, OCR, tabelas, documentos oficiais, orçamentos, fórmulas, imagens,
QR e páginas rotacionadas. Durante `Verify`, preflight, testes e inferência, rede,
APIs remotas e download sob demanda são proibidos. Somente `Prepare` pode usar
rede para adquirir modelos; depois disso os manifests v1 fixam caminho relativo,
tamanho e SHA-256 de cada arquivo.

Docker continua sendo o runtime padrão do projeto. A seleção de host é sempre
explícita e suas saídas ficam sob o namespace `host`.

## Suíte oficial Windows

`windows_all_features_host` contém, nesta ordem:

1. `pymupdf/full_cpu_local_visual`
2. `docling/full_cpu_local`
3. `mineru/full_cpu_local`
4. `paddleocr/full_cpu_local`
5. `liteparse/full_cpu_local`
6. `unstructured/full_cpu_local`
7. `xberg/full_cpu_layout`

## Procedimento oficial

Execute uma vez a preparação, com rede disponível:

```powershell
.\scripts\windows\setup_envs.ps1
.\scripts\windows\prepare_all_models.ps1 -Mode Prepare
```

Depois desconecte/bloqueie a rede e execute o gate completo:

```powershell
.\scripts\windows\check_server_readiness.ps1 -VerboseOutput
```

Para inspecionar ou executar somente a suíte:

```powershell
.\scripts\windows\run_all_features_host.ps1 -DryRun
.\scripts\windows\run_all_features_host.ps1 -PreflightOnly
.\scripts\windows\run_all_features_host.ps1
```

O wrapper é fresco por padrão; use `-Resume` somente para outputs cuja
proveniência, hashes, assets e conteúdo passem a validação integral. O timeout
padrão de cada job é 3.600 segundos e pode ser alterado por
`-JobTimeoutSeconds`.

## Gates e evidências

O readiness verifica: plataforma Windows nativa, repositório limpo/SHA,
versões e `pip check` de todas as venvs, Tesseract/Poppler, manifests e inferência
offline dos modelos, testes comuns, testes isolados dos sete adapters, smoke
profundo sequencial, pós-validação de todos os artefatos, links/asset manifests,
arquivos temporários/downloads e processos descendentes remanescentes.

Os relatórios ficam em:

```text
logs\windows_readiness\<timestamp>\
```

As linhas finais obrigatórias são:

```text
SERVER_READINESS=PASS|FAIL
COMMIT=<sha>
PARSERS_READY=<lista>
PARSERS_FAILED=<lista>
FUNCTIONAL_TESTS_SKIPPED=<n>
```

Qualquer parser ausente, teste funcional pulado, mutação de modelo, tentativa de
rede, link inválido, artifact vazio inesperado ou processo vazado impede PASS.

---

## Análise de qualidade — bugs críticos identificados (2026-09-04)

Revisão completa do código-fonte realizada com o servidor operacional na branch
`perf/parser-runtime-optimization`. Preflight e execução passam. Os itens abaixo
são bugs que causam **perda de dados silenciosa ou comportamento incorreto** em
cenários que o documento de teste atual (TC_007646_2021.pdf, 48 páginas sem
imagens/QR) não exercita.

### 🔴 Bugs críticos

| # | Parser | Arquivo | Problema |
|---|---|---|---|
| 1 | Xberg | `src/parsers/xberg_v2.py` linha ~826 | PDFs com páginas em branco crasham: `_result_to_artifacts()` trata página ausente como erro fatal em vez de string vazia |
| 2 | LiteParse | `src/parsers/liteparse_v2.py` linhas ~41, ~1364 | Preflight sempre retorna `ok=False`: `TRANSFORMERS_REQUIRED_VERSION = "5.16.1"` não existe como versão real; check roda incondicionalmente |
| 3 | LiteParse | `src/parsers/liteparse_v2.py` linhas ~817–820 | OCR de imagens calculado corretamente mas nunca inserido no Markdown: mismatch de chave entre `_process_document_images()` e `_build_page_text_with_enrichments()` |
| 4 | MinerU | `src/parsers/mineru_v2.py` linhas ~1175, ~1241 | Legendas e rodapés de figuras descartados silenciosamente: `render_mineru_item()` sem handler para `"type": "image"`; texto está em `img_caption`/`img_footnote`, não em `text` |
| 5 | Unstructured | `src/parsers/unstructured_v2.py` linhas ~129, ~167 | Tabelas com `rowspan`/`colspan` inserem HTML bruto em `page_texts`, corrompendo o Markdown e as métricas de token |
| 6 | Unstructured | `src/parsers/unstructured_v2.py` linha ~214 | Tabelas que cruzam limites de página (`page_number=None`) nunca são renderizadas em `page_texts` |
| 7 | Todos | `src/benchmark/normalizer.py` linha ~213 | Páginas com menos de 6 linhas não-vazias: `header_indexes` e `footer_indexes` se sobrepõem, causando contagem dupla e remoção de conteúdo real como se fosse cabeçalho/rodapé repetido |

### 🟠 Bugs altos

| # | Parser | Arquivo | Problema |
|---|---|---|---|
| 8 | PaddleOCR | `src/parsers/paddleocr_v2.py` linhas ~798, ~1480 | `result["page_index"]` via subscript dict em objeto Pydantic pode levantar `TypeError`; usar `_result_value()` que já existe |
| 9 | PaddleOCR | `src/parsers/paddleocr_v2.py` linha ~1519 | `expected_indexes = range(page_count)` assume 0-based; PPStructureV3 pode retornar 1-based |
| 10 | LiteParse | `src/parsers/liteparse_v2.py` linhas ~1269, ~1846 | DPI default 150 no parse nativo vs. 300 na passagem OCR: coordenadas incompatíveis corrompem lógica de merge |
| 11 | Docling | `src/parsers/docling_v2.py` linha ~1194 | `export_to_markdown(page_no=N)` com loop 1-based: se `docling==2.122.0` usa 0-based, todo conteúdo de página é exportado com deslocamento +1 |

### Ação requerida antes da próxima campanha formal

1. Corrigir os bugs 1–7 (críticos) antes de executar qualquer suite v3 com documentos que contenham imagens, figuras, tabelas mescladas ou páginas em branco
2. Verificar bugs 8–11 com inspeção do resultado real no servidor (`result["page_index"]` valor concreto; `page_no` comportamento na versão docling instalada)
3. Detalhes e correções propostas: `docs/PLANO_CORRETIVO_DESENVOLVEDOR.md`

---

# Histórico — milestone anterior

O conteúdo abaixo é preservado como registro do milestone anterior. Nomes de
branch, prioridades, comandos e declarações de estado desta seção não substituem
o procedimento canônico acima.

## Windows Server Host Runtime — Current Status (histórico)

## 1. Purpose

This document records the current operational state of native Windows Server execution for the `document-ai-benchmark` project.

It is a temporary development and validation checkpoint for the branch:

```text
server/windows-native
```

It does not redefine the default runtime architecture of the project.

## 2. Runtime policy

The project default runtime remains:

```text
Docker
```

Native Windows host execution is currently being developed and validated as an additional runtime.

During the current development phase, the seven parsers are being executed directly on a Windows Server host to validate that they can operate locally without requiring Docker.

The generic project runtime must therefore continue to default to Docker unless a host runtime is explicitly selected.

Windows specific wrappers may explicitly select:

```text
runtime=host
```

without changing the project wide default.

## 3. Development workflow

All source code changes are performed on the developer workstation using WSL on Windows 11.

The required workflow is:

```text
WSL development environment
        ↓
local implementation
        ↓
local static validation
        ↓
git commit
        ↓
push to GitHub
        ↓
Windows Server
        ↓
git pull / checkout
        ↓
execution only
```

The Windows Server repository is not a development workspace.

No source code modification should be performed directly on the server.

If:

```powershell
git status --short
```

returns modified tracked files on the server, execution should stop until the difference is understood.

The server should always execute a known Git commit.

Before an important validation run, record:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
```

## 4. Docker policy during this phase

No Docker environment changes are required for the current Windows host work.

Docker configuration should not be changed merely to support the current Windows Server validation.

Docker remains the normal project runtime and should continue to work independently of the Windows host implementation.

## 5. Current native Windows parsers

The Windows host runtime currently contains isolated environments for:

```text
PyMuPDF
Docling
LiteParse
MinerU
PaddleOCR
Unstructured
Xberg / Kreuzberg
```

Each parser uses its own Python virtual environment under:

```text
.venvs\<parser>\
```

A separate core environment is used for benchmark and runtime orchestration:

```text
.venvs\core\
```

The objective of this isolation is to prevent dependency conflicts between document conversion engines.

## 6. Current priority

The immediate objective is not comparative benchmark quality.

The immediate objective is:

> Make all seven parsers execute successfully from beginning to end on the Windows Server using local models and host runtime.

The following activities are intentionally secondary until the runtime is stable:

```text
Gold Standard evaluation
detailed quality scoring
benchmark ranking
fine grained token comparison
large scale regression testing
advanced table reconstruction
output optimization
```

## 7. Required execution sequence

The preferred Windows Server validation sequence is:

```text
1. Verify repository state
2. Verify parser environments
3. Run parser preflight
4. Run all seven parsers against one PDF
5. Diagnose individual failures
6. Repeat until all seven complete successfully
7. Test representative difficult PDFs
8. Only then begin the formal benchmark phase
```

### 7.1 Repository state

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected result:

```text
branch = server/windows-native
working tree = clean
```

### 7.2 Environment check

Use the Windows environment validation script before parser execution.

This verifies the isolated Python environments and their basic imports.

### 7.3 Preflight

Run the host preflight for all seven parser/profile combinations.

Preflight should detect problems such as:

```text
missing packages
incorrect package versions
missing local model artifacts
incorrect model paths
invalid runtime configuration
missing external executables
```

Preflight is a gate, not the final validation.

A successful preflight does not prove that inference works.

### 7.4 Real execution

After all preflights pass, execute the seven parsers against one PDF.

A parser is considered operational only after real document processing succeeds and output artifacts are generated.

## 8. Offline execution policy

The final project requirement is that document processing must not depend on internet connectivity.

Models and runtime assets must already exist locally on the server.

Current runtime controls include offline related environment variables such as:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
DO_NOT_TRACK=1
SCARF_NO_ANALYTICS=1
```

Parser specific local model controls are also used where applicable.

Examples include:

```text
MINERU_MODEL_SOURCE=local
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
```

Hugging Face based model loading should additionally use local model paths and `local_files_only=True` where supported.

These controls strongly prevent normal model downloads and remote resolution.

They should not be confused with an operating system level network isolation guarantee.

An optional operational validation can be performed by running the parser processes with invalid process scoped HTTP proxy variables. This does not modify machine wide network configuration.

Formal network isolation validation can be performed later if required.

## 9. LiteParse current work

LiteParse is the parser currently being finalized before the next Windows Server validation cycle.

The current local work changes the SmolVLM integration to use the Transformers API compatible with the selected runtime.

Important changes include:

```text
transformers pinned to 5.16.1

AutoModelForVision2Seq
    replaced by
AutoModelForImageTextToText

SmolVLM receives the actual PIL image through the processor

generated prompt tokens are excluded from decoded model output

empty model responses are treated as failures

SmolVLM runtime failures are no longer silently ignored

image description may execute together with usable Tesseract OCR

Transformers and Torch versions are included in runtime metrics

LiteParse setup performs pip check and an API smoke validation
```

The local changes must be committed and pushed before Windows Server testing.

No equivalent manual source modification should be made on the server.

## 10. LiteParse maximum capability profile

The current maximum capability profile intentionally allows SmolVLM execution even when OCR text is already available.

This is expected behavior.

The objective of this profile is maximum local extraction capability rather than minimum CPU usage.

A separate economical configuration may use visual description only as a fallback.

This distinction should not be changed during the current runtime stabilization work.

## 11. LiteParse visual descriptions

SmolVLM image descriptions are currently stored as parser native enrichment data.

They are not necessarily injected into the final Markdown output.

This does not block the current server runtime validation.

A later enhancement may add a profile controlled option to include visual descriptions in Markdown.

Possible future configuration:

```json
{
  "image_description_in_markdown": true
}
```

This enhancement is currently non blocking.

## 12. Rotated pages

Embedded images already have Tesseract OSD based orientation handling in the LiteParse adapter.

Full PDF pages routed to LiteParse OCR do not currently have an equivalent adapter level rotation correction.

Before implementing another page processing layer, actual execution must be tested with:

```text
normal page
90 degree rotated scanned page
180 degree rotated scanned page
```

If LiteParse successfully processes these cases, no adapter change is necessary.

If it fails, page orientation correction should be implemented as a separate task.

This task must preserve as much LiteParse layout information as possible.

## 13. Tables inside images

Table structure already produced by the parser can be preserved and compacted as Markdown.

However, OCR enrichment of an extracted image currently produces plain OCR text.

Reconstructing an arbitrary table contained only inside an image requires additional layout analysis.

A robust implementation would need to consider word bounding boxes, rows, columns, merged cells and reading order.

This is therefore classified as a backlog enhancement rather than a runtime blocking correction.

The current priority is to make LiteParse and the other parsers execute reliably.

## 14. Immediate validation target

Before expanding functionality, the current success criterion is:

```text
PyMuPDF       PASS
Docling       PASS
LiteParse     PASS
MinerU        PASS
PaddleOCR     PASS
Unstructured  PASS
Xberg         PASS
```

Each PASS should mean:

```text
environment available
preflight successful
model/runtime initialization successful
one PDF processed
expected output artifacts produced
process exits successfully
```

## 15. Difficult document smoke set

After the seven parsers successfully process a normal document, perform a lightweight execution smoke using representative files.

Recommended cases:

```text
native text PDF
scanned PDF
90 degree rotated scan
180 degree rotated scan
simple table
complex table
official document with repeated headers/footers
document containing embedded images
```

At this stage the purpose is only to identify operational failures and obvious extraction problems.

Formal quality scoring is deferred.

## 16. Deferred work

The following tasks are intentionally deferred until all parsers are operational on the Windows Server:

```text
Gold Standard construction and evaluation
formal parser ranking
large benchmark campaign
advanced image table reconstruction
visual description injection into final Markdown
detailed rotated page normalization if LiteParse already handles it
token optimization tuning
benchmark quality thresholds
```

## 17. Definition of the next milestone

The next milestone is reached when:

```text
all seven Windows host preflights pass
        +
all seven parsers successfully process the same PDF
        +
all required models are loaded locally
        +
no parser requires a remote API during execution
```

After this milestone, development can move from runtime stabilization to difficult document validation and, later, the formal comparative benchmark.


## Windows host validation milestone

Validated on 2026-09-01.

Validation commit:

    001ca76

Environment:

    Windows Server
    Windows PowerShell 5.1
    runtime=host
    suite=windows_full_cpu_local_all_host

Validation document:

    TC_007646_2021.pdf
    48 pages

Results:

    preflight: PASS
    jobs completed: 7
    jobs failed: 0
    jobs aborted: 0
    batch exit code: 0

All seven parsers produced their expected metrics.json and
document.md artifacts.

The validated parsers were:

    PyMuPDF
    Docling
    MinerU
    PaddleOCR
    LiteParse
    Unstructured
    Xberg

All required model artifacts were resolved locally.

The runtime was configured with offline Hugging Face behavior,
telemetry disabled, parser specific local model configuration,
and remote services disabled where supported.

No remote API use or model download was observed in the
validation logs.

This validation does not constitute operating system level
network isolation certification.

### LiteParse visual enrichment validation note

The Windows host smoke run successfully validated the LiteParse full_cpu_local parser runtime, its local dependencies, Transformers 5.16.1 compatibility, Tesseract integration, local SmolVLM model discovery, and final artifact generation.

However, the validation document did not exercise the image enrichment pipeline.

The LiteParse metrics reported:

images_detected         : 0
images_extracted        : 0
images_ocr_attempted    : 0
images_with_usable_text : 0
images_described        : 0

Therefore, this milestone does not claim that real SmolVLM image inference has been validated on the Windows Server.

A dedicated visual document smoke test should be performed in a later task using a PDF that is known to trigger LiteParse image extraction and description.

This does not block the Windows host runtime milestone because LiteParse itself completed the shared document successfully using the full_cpu_local profile and produced the expected output artifacts.



### Registered Warnings

PyMuPDF: DPI automaticamente reduzido em páginas grandes
Docling: avisos de OCR vazio e tied weights
PaddleOCR: PP-Chart2Table com embed_tokens recém inicializado
Xberg: mensagens "Empty page!!"
PowerShell: outros scripts auxiliares ainda contêm Unicode


## Schema v3 artifact contract — status

### Introdução do contrato

A partir do commit seguinte ao milestone de validação (001ca76), o projeto
iniciou a fase de qualidade de extração.

O schema 2 gravava `raw.md` com texto normalizado, mascarando a qualidade
real do parser. O schema 3 separa:

```text
raw.md              — saída nativa do parser (sem normalização)
document.md         — saída normalizada (sem conteúdo derivado)
document.enriched.md — conteúdo enriquecido com blocos derived:start
native/             — bundle de arquivos nativos do parser (ex: MinerU)
```

### Commit 1 concluído — contrato base

Arquivos alterados:

```text
src/benchmark/artifact_contract.py  (novo)
src/benchmark/paths.py              (+enriched_markdown, native_dir, ...)
src/benchmark/artifact_policy.py    (+document.enriched.md, +native)
src/benchmark/artifacts.py         (nova assinatura finalize_artifacts)
src/benchmark/config.py             (schema_version check: 2 → 3)
src/benchmark/post_validation.py    (METRICS_SCHEMA_VERSION: 2 → 3)
config/benchmark_profiles.json      (schema_version: 2 → 3)
tests/_support.py                   (schema_version: 3, novos artefatos)
parser_tests/*/test_serialization.py (schema_version: 3)
src/parsers/pymupdf_v2.py           (ParserArtifactInput, schema_version: 3)
src/parsers/mineru_v2.py            (ParserArtifactInput, schema_version: 3)
src/parsers/docling_v2.py           (ParserArtifactInput, schema_version: 3)
src/parsers/paddleocr_v2.py         (ParserArtifactInput, schema_version: 3)
src/parsers/liteparse_v2.py         (ParserArtifactInput, schema_version: 3)
src/parsers/unstructured_v2.py      (ParserArtifactInput, schema_version: 3)
src/parsers/xberg_v2.py             (ParserArtifactInput, schema_version: 3)
```

Todos os 7 adaptadores usam `raw_origin_kind = "adapter_assembled_declared"`
neste commit transitório. A extração de markdown nativo por parser ocorre
nos commits seguintes.

### Commit corretivo concluído — schema v3 completo

Após o Commit 1, uma revisão identificou lacunas no contrato. O commit
corretivo resolve todos os itens P0/P1:

Arquivos alterados no commit corretivo:

```text
src/benchmark/artifact_contract.py  (VALID_PAGE_MAPPING_STATUS, VALID_RAW_ORIGIN_KIND)
src/benchmark/artifacts.py          (source_text, document_jsonl block, derived validation)
src/benchmark/token_metrics.py      (source_text param, normalization_tokens_removed,
                                     raw_to_clean_token_delta, source_markdown_tokens)
src/benchmark/post_validation.py    (_validate_native_dir com parser/profile,
                                     artifacts/quality_eligibility obrigatórios,
                                     coherence checks de enriched)
tests/_support.py                   (fixtures com artifacts.raw/clean, quality_eligibility)
tests/test_artifact_contract.py     (22 casos de teste do contrato)
src/parsers/pymupdf_v2.py           (+artifacts, +quality_eligibility)
src/parsers/docling_v2.py           (+artifacts, +quality_eligibility)
src/parsers/mineru_v2.py            (+artifacts, +quality_eligibility)
src/parsers/paddleocr_v2.py         (+artifacts, +quality_eligibility)
src/parsers/liteparse_v2.py         (+artifacts, +quality_eligibility)
src/parsers/unstructured_v2.py      (+artifacts, +quality_eligibility)
src/parsers/xberg_v2.py             (+artifacts, +quality_eligibility)
```

Estado dos testes em WSL: 780 passando, 0 regressões.

Gates de grep: `schema_version.*2` ausente em src/config/tests (exceto
test_preflight_contract.py); `page_texts=` ausente em src/parsers/.

O schema v3 não deve ser executado no Windows Server até este commit
corretivo ser aprovado e submetido ao pull.

### Commit 2 concluído — OCR português a 150 DPI

```text
feat(pymupdf): enforce portuguese OCR at 150 dpi
```

Corrigidos os fallbacks silenciosos no adapter:
- `ocr_language`: `"eng"` → `"por"`
- `ocr_dpi`: `300` → `150`

Perfis atualizados: `ocr_force_rapidtess` e `full_cpu_local` agora explicitamente
a 150 DPI. Perfis `_200` e `_300` marcados como `diagnostic_only=true`.

Adicionado check de preflight que recusa `write_images=true` ou `embed_images=true`.

### Commit 3 concluído — worker de enriquecimento visual

```text
feat(enrichment): add local in-memory visual enrichment worker
```

Criado módulo `src/enrichment/` com:
- `visual_contract.py` — dataclasses `VisualRequest` / `VisualResponse`
- `visual_worker.py` — processo filho que carrega PaddleOCR + SmolVLM uma vez
- `visual_worker_client.py` — cliente com context manager e registro no ResourceMonitor
- `requirements/windows/visual_enrichment.txt`
- `scripts/windows/setup_visual_enrichment.ps1`

Imagens processadas exclusivamente em memória. `image_base64` nunca gravado em disco.

### Commit 4 concluído — perfil visual não persistente no PyMuPDF

```text
feat(pymupdf): add non-persistent visual enrichment profile
```

Criado `src/parsers/pymupdf_visual_enrichment.py` com pipeline isolado:
- Detecta regiões `picture`, `chart`, `diagram` via `page_boxes`
- Renderiza em memória com `get_pixmap(...).tobytes("png")` — sem `pix.save()`
- `region_id` estável: `p<page>-picture-<index>-<sha256_prefix>`
- Filtragem por área mínima (`0.2%`), largura mínima (80px), dimensão máxima (2500px)
- Blocos `derived:start` inseridos no `enriched_page_markdown`

Novo perfil `full_cpu_local_visual` no `benchmark_profiles.json`:
- `visual_enrichment_enabled: true`
- `visual_description_model: HuggingFaceTB/SmolVLM-256M-Instruct`
- `visual_failure_fatal: false` (falha não aborta job)
- `visual_persist_images: false`

Perfil `full_cpu_local` mantido sem enriquecimento visual (chaves adicionadas com
`visual_enrichment_enabled: false`).

Métricas registradas em `processing.visual_enrichment`:
`regions_detected`, `regions_processed`, `regions_failed`, `images_persisted=0`,
`temporary_files_created=0`.

Parser registra `PyMuPDF4LLM + PaddleOCR + SmolVLM` nas métricas quando visual
ativo; `PyMuPDF4LLM` quando desativado.

### Commits 5+6 concluídos (unificados) — MinerU nativo

```text
fix(mineru): preserve native markdown, bundle and effective formula/table flags
```

Alterações implementadas:

- `native_markdown`: usa o arquivo `.md` oficial do MinerU com leitura
  UTF-8 estrita; `UnicodeDecodeError` agora propaga como `RuntimeError`
  em vez de substituir caracteres silenciosamente

- `ParserArtifactInput`: `raw_origin_kind = "parser_native_exact"`,
  `raw_origin_details = "<document_id>.md"`

- Bundle nativo copiado para `native/` antes do `TemporaryDirectory`
  fechar: `.md`, `_content_list.json`, `_middle.json`, `images/`;
  `manifest.json` criado com `schema_version=1`, `bundle_status=available`,
  SHA-256 por arquivo

- CLI: `--formula true/false` e `--table true/false` adicionados ao
  comando `mineru`; env vars `MINERU_FORMULA_ENABLE`, `MINERU_TABLE_ENABLE`
  e `MINERU_TABLE_MERGE_ENABLE` injetadas no subprocesso

- Perfil `full_cpu_local`: adicionado `table_merge: true`,
  `persist_native_assets: true`, `persist_content_list: true`,
  `persist_middle_json: true`

- Métricas: `table_merge_enabled`, `native_bundle_valid` adicionados a
  `mineru_native`

### Commits 7+8+9 concluídos (unificados) — LiteParse completo

```text
fix(liteparse): preserve native markdown, merge policy and visual enrichment contract
```

Alterações implementadas:

**Native markdown (Commit 7):**
- `ParserArtifactInput.native_markdown = raw_text` (= `result.text` direto)
- `raw_origin_kind = "parser_native_exact"`, `raw_origin_details = "result.text"`
- Removido fallback de divisão por caracteres em `_extract_page_texts`
- `page_mapping_status = "unavailable"` quando não há dados por página

**Merge policy (Commit 8):**
- Adicionada classe `MergeDecision` com valores:
  `keep_native`, `replace_empty_page`, `replace_garbled_page`,
  `merge_missing_regions`, `derived_only`
- `_decide_merge()`: compara alphanum ratio, replacement char ratio e
  tamanho relativo antes de aceitar OCR
- `_merge_page_texts()` retorna `(texts, decisions)` — substitui OCR
  somente quando nativo é vazio, corrompido, ou OCR é substancialmente
  melhor
- Métricas: `pages_replaced_empty`, `pages_replaced_garbled`,
  `pages_kept_native` adicionadas ao bloco `ocr`

**Visual enrichment contract (Commit 9):**
- `_image_file_hash` migrado de MD5 para SHA-256
- `_region_id()` adicionado: `p<page>-image-<index>-<sha256_prefix>`
- `derived_content_by_page` construído por página com `storage_policy=transient`,
  `deleted_after_processing=true`, SHA-256 por imagem — sem paths temporários
- `enriched_page_markdown` populado com blocos `derived:start` quando
  `image_description=true` e descrição SmolVLM disponível
- `source_page_texts` separado de `page_texts` (textos enriquecidos)
  para que `source_page_markdown` na normalização não contenha blocos derivados

---

## Etapa 2 — Docling, PaddleOCR, Unstructured, Xberg

### Commit D1+D2 — `feat(docling): heading hierarchy and table engine selection`

**Status:** implementado — aguardando validação no Windows Server

**Arquivo alterado:** `src/parsers/docling_v2.py`, `config/benchmark_profiles.json`

**Heading hierarchy (D1):**
- Bloco `HeadingHierarchyOptions` adicionado em `_build_pipeline_options()`
  com import guardado por `try/except ImportError` (compatibilidade WSL sem docling)
- Parâmetros configuráveis via perfil: `heading_hierarchy`, `heading_use_bookmarks`,
  `heading_use_numbering`, `heading_use_style`, `heading_use_font_style`,
  `heading_style_size_tolerance`, `heading_max_level`, `heading_bookmark_match_threshold`
- Quando `heading_use_style=true`: `generate_parsed_pages=True` ativado automaticamente
- Check `heading hierarchy support` adicionado ao `preflight_profile()`
- Todos os 6 perfis do docling receberam as novas chaves com valores padrão conservadores

**Table engine selection (D2):**
- Nova chave `table_engine` nos perfis: `"tableformer_v1"` (padrão) ou `"tableformer_v2"`
- Quando `table_engine="tableformer_v2"`: usa `TableStructureV2Options` com import guardado
- Check `table engine v2 support` adicionado ao `preflight_profile()`
- Novo perfil `ocr_auto_table_v2`: idêntico a `ocr_auto` mas com `table_engine="tableformer_v2"`

### Commit D3+D4 — `feat(docling): picture description enrichment and profile tests`

**Status:** implementado — aguardando validação no Windows Server

**Arquivo alterado:** `src/parsers/docling_v2.py`
**Arquivos novos:** `parser_tests/docling/test_heading_table_profiles.py`, `parser_tests/docling/test_enriched_markdown.py`

**Enriched markdown (D3):**
- Nova função `_build_picture_description_blocks()`: itera `PictureItem` com `meta.description`,
  constrói blocos `derived:start` por página com `region_id=p<page>-picture-<index>`
- `build_docling_page_contract()` estendida para retornar também
  `(enriched_page_markdown, derived_content_by_page)` — 7 valores no total
- Nota: `enriched_page_texts` é uma cópia de `page_texts` — a lista original
  (fonte de `source_page_markdown`) nunca recebe blocos `derived:start`
- `ParserArtifactInput` atualizado:
  - `enriched_page_markdown` passa o resultado (ou `None` se não há descrições)
  - `derived_content_by_page` passa os metadados por página
  - `raw_origin_kind="parser_native_per_page_join"` (era `"adapter_assembled_declared"`)
  - `raw_origin_details="export_to_markdown per page"`

**Testes (D4):**
- `test_heading_table_profiles.py`: verifica presença de todas as chaves de heading
  e table_engine em todos os 7 perfis; valores válidos; `ocr_auto_table_v2` usa v2
- `test_enriched_markdown.py`: 10 casos com stubs — sem `torch`/`docling` instalado;
  testa format de `region_id`, múltiplas imagens por página, texto nativo preservado,
  imagem sem proveniência ignorada, `derived:start` não contamina `source_page_texts`
- Ambos os arquivos só rodam no Windows Server (dependência `torch` no import do adapter)

### Commit P1+P2 — `feat(paddleocr): cpu inference runtime settings and complete native results`

**Status:** implementado — aguardando validação no Windows Server

**Arquivo alterado:** `src/parsers/paddleocr_v2.py`, `config/benchmark_profiles.json`

**CPU inference runtime (P1):**
- `build_pipeline_kwargs()` estendido com `device`, `engine`, `enable_mkldnn`,
  `mkldnn_cache_capacity`, `cpu_threads` quando presentes no perfil
- `enable_hpi=False` e `enable_cinn=False` sempre passados (reproducibilidade)
- Novos kwargs validados automaticamente pelo preflight existente via
  `inspect.signature(PPStructureV3.__init__)`
- Bloco `paddle_runtime` adicionado em `processing`: `device`, `engine_requested`,
  `mkldnn_enabled`, `mkldnn_cache_capacity`, `cpu_threads_requested`,
  `hpi_enabled`, `cinn_enabled`
- Todos os 6 perfis receberam: `device="cpu"`, `inference_engine="paddle_static"`,
  `enable_mkldnn=true`, `mkldnn_cache_capacity=10`, `cpu_threads=null`

**Native results completos (P2):**
- Nova função `_json_safe()`: serializa resultados do PPStructureV3 de forma
  segura — elimina bytes de imagem, numpy arrays → tolist(), profundidade máxima 8
- `build_paddleocr_page_contract()` estendido: cada `parser_native_pages[i]` agora
  inclui `parsing_res_list` (serializado), `overall_ocr_res` (serializado),
  `tables_with_html`, `chart_count`, `seal_count`
- `parser_output` atualizado: `tables_with_html`, `charts_detected`, `seals_detected`

### Commit P3+P4 — `feat(paddleocr): threshold configuration and ppocrv6 experimental profile`

**Status:** implementado — aguardando validação no Windows Server

**Arquivo alterado:** `src/parsers/paddleocr_v2.py`, `config/benchmark_profiles.json`

**Thresholds configuráveis (P3):**
- Novas chaves adicionadas a `PROFILE_EXTRA_KEYS` (opcionais, ausência não causa erro):
  `layout_threshold`, `text_det_thresh`, `text_rec_score_thresh`,
  `use_wired_table_cells_trans_to_html`, `use_e2e_wired_table_rec_model`,
  `use_e2e_wireless_table_rec_model`
- `build_pipeline_kwargs()`: passa threshold ao PPStructureV3 somente quando
  declarado no perfil com valor não-nulo; ausente = defaults da biblioteca

**Perfil PPOCRv6 experimental (P4):**
- Novas chaves em `PROFILE_EXTRA_KEYS`: `experimental`,
  `text_detection_model_dir_override`, `text_recognition_model_dir_override`
- `build_pipeline_kwargs()`: quando override não-nulo, substitui o
  `text_detection_model_dir` / `text_recognition_model_dir` resolvido pelo
  `resolve_model_paths()` — permite usar modelos v6 sem alterar a raiz default
- `preflight_profile()`: check `experimental profile` com status `warn` quando
  `experimental=true` — aviso explícito de que o perfil não é elegível para ranking
- Novo perfil `ppstructure_v6_experimental` em `benchmark_profiles.json`:
  baseado em `full_cpu_local`, `experimental=true`,
  `text_detection_model_dir_override=null` e
  `text_recognition_model_dir_override=null` (operador define os paths v6 locais)

### Commit U1–U4 — `feat(unstructured): explicit ocr agent, transient images, per-page metrics and new auto profiles`

**Status:** implementado — aguardando validação no Windows Server

**Arquivos alterados:** `src/parsers/unstructured_v2.py`, `config/benchmark_profiles.json`
**Arquivos novos:** `parser_tests/unstructured/test_per_page_metrics.py`, `parser_tests/unstructured/test_ocr_agent.py`
**Arquivos corrigidos:** `parser_tests/unstructured/test_profiles.py`, `parser_tests/unstructured/test_adapter_contract.py`

**OCR agent explícito (U1):**
- Novas chaves `ocr_agent` e `table_ocr_agent` adicionadas a `_PROFILE_KEYS`
- Constante `_OCR_AGENT_TESSERACT` definida localmente (fallback quando unstructured não instalado)
- `main()`: quando `ocr_enabled` e `ocr_agent` declarado, passa `ocr_agent` e `table_ocr_agent`
  ao `partition_pdf()` usando a constante da biblioteca quando disponível
- Métricas: `strategy_requested`, `strategy_effective`, `ocr_agent_requested`,
  `ocr_agent_effective`, `table_ocr_agent_requested`
- Novos perfis `auto_general` (sem `infer_table_structure`) e `auto_quality`
  (com `infer_table_structure=true`) — ambos com `strategy=auto`, `ocr_agent=tesseract`

**Ciclo de vida de imagens (U2):**
- `image_temp_dir.cleanup()` movido para bloco `finally` com `image_temp_dir = None`
  após cleanup — garante que imagens temporárias são removidas mesmo em caso de exceção
- `parser_native_pages[i]["images_extracted"]`: conta imagens extraídas por página
  sem persistir nenhum path no artefato
- `images_extracted_transient` e `unassigned_elements` nas métricas `ocr`

**Métricas por página corretas (U3):**
- Nova função `_count_elements_by_page()`: distribui contagens por `metadata.page_number`
  em vez de acumular tudo na página 0
- `parser_page_elements` agora usa `per_page_counts` para todos os perfis
- `unassigned_elements` (sem `page_number`) guardados separadamente

**Testes (U4):**
- `test_per_page_metrics.py`: 8 casos — regression test para o bug de acumulação
  na página 1, elementos não atribuídos, out-of-range, PageBreak ignorado
- `test_ocr_agent.py`: 9 casos — chaves presentes, valores corretos, novos perfis
- Corrigidos: `test_profiles.py` (novo `_EXPECTED_PROFILES` + `_REQUIRED_KEYS`) e
  `test_adapter_contract.py` (mock de `finalize_artifacts` com `artifacts` e `quality_eligibility`)

### Commit X1–X4 — `feat(xberg): enable local cpu layout, qr extraction and table diagnostics`

**Status:** implementado — aguardando validação no Windows Server

**Arquivos alterados:** `src/parsers/xberg_v2.py`, `config/benchmark_profiles.json`
**Arquivos novos:** `parser_tests/xberg/test_qr_codes.py`, `parser_tests/xberg/test_layout_config.py`
**Arquivos atualizados:** `parser_tests/xberg/test_profiles.py`

**Layout local CPU (X1):**
- Removido guard que bloqueava `layout_enabled=true` com `XbergConfigurationError`
- Construção de `AccelerationConfig(provider="cpu")` e `LayoutDetectionConfig` quando
  `layout_enabled=true` — com todas as sub-chaves configuráveis via perfil
- Novas chaves em `_PROFILE_KEYS`: `layout_strategy`, `layout_apply_heuristics`,
  `layout_acceleration_provider`, `layout_confidence_threshold`, `layout_enable_chart_understanding`
- Métricas `xberg_layout`: `enabled`, `provider`, `use_layout_for_markdown`

**Layout para Markdown (X2):**
- `use_layout_for_markdown` no `root_config` agora é `layout_enabled` (antes hardcoded `False`)
- Quando `layout_enabled=true`, o Xberg usa o mapa de regiões de layout para gerar o Markdown

**QR codes (X3):**
- `qr_codes` no `root_config` agora lê do perfil (antes hardcoded `False`)
- Nova função `_collect_qr_results()`: coleta QR codes do documento e das páginas individualmente
- Nova função `_build_qr_derived_blocks()`: transforma QR results em `derived_content_by_page`
- Nova função `_render_qr_enriched_page()`: injeta blocos `derived:start / type=qr_code`
  no `enriched_page_markdown` — payload nunca é executado ou buscado na rede
- `_qr_payload_is_safe()`: rejeita payloads > 2000 chars ou com caracteres de controle
- Métricas `qr`: `enabled`, `detected`, `decoded`, `failed`

**Diagnósticos de tabela e Markdown (X4):**
- `allow_single_column_tables` agora lido do perfil (antes hardcoded `False`)
- Nova chave `qr_codes` em `_PROFILE_KEYS`
- `language_detection` permanece `None` fixo (não exposto como chave de perfil)

**Novo perfil `full_cpu_layout`:**
- Baseado em `full_cpu_local` com `layout_enabled=true` e `qr_codes=true`
- `layout_acceleration_provider="cpu"`, `layout_apply_heuristics=true`

**`raw_origin_kind` unificado:**
- Todos os perfis Xberg agora usam `parser_native_per_page_join` com
  `raw_origin_details="page_texts join from ExtractedDocument.pages"`

---

## Commit corretivo pós-Etapa 2 — correções de contrato identificadas antes da validação

**Status:** implementado — aguardando commit e validação no Windows Server

### Itens corrigidos

**LiteParse — derived items com `type`, `source`, `text`:**
- Items agora têm `"type": "image_description"` (VLM) ou `"type": "image_ocr"` (OCR-only)
- Campo `"source": "liteparse"` em todos os items
- Campo `"text"` com o conteúdo real (descrição VLM ou texto OCR)
- `has_derived_text` substitui `has_descriptions`: cobre items de OCR-only, não só VLM
- `enriched_page_markdown` disponível quando há OCR-only (não só quando há descrição VLM)
- Blocos `derived:start` gerados com `type=image_ocr` para OCR-only e `type=image_description` para VLM

**LiteParse — page mapping por cobertura real:**
- `_extract_page_texts()` retorna `tuple[list[str], set[int]]`
- `mapped_pages: set[int]` rastreia páginas mapeadas pela biblioteca (não por conteúdo)
- `page_mapping_status="complete"` somente quando `effective_mapped >= all_expected`

**PyMuPDF — visual worker Python correto:**
- `_resolve_visual_worker_python()`: resolve via `DOCUMENT_AI_VISUAL_WORKER_PYTHON` ou
  `.venvs/visual-enrichment/Scripts/python.exe` (Windows) / `.../bin/python` (Linux)
- Worker antes usava `sys.executable` (Python do venv pymupdf); agora usa o venv dedicado

**PyMuPDF — reabertura do PDF para enriquecimento visual:**
- PDF reaberto explicitamente com `pymupdf.open(input_path)` após fechamento do documento principal
- Evita uso de `document` já fechado no bloco `finally`

**PyMuPDF — model path local para SmolVLM:**
- `visual_description_model` em `full_cpu_local_visual` alterado para
  `"models/liteparse/smolvlm/HuggingFaceTB--SmolVLM-256M-Instruct"` (path relativo local)
- Código resolve como path absoluto se o diretório existir localmente

**MinerU — cópia recursiva do bundle:**
- Assets copiados com `rglob("*")` em vez de `iterdir()` (recursivo)
- Estrutura relativa preservada: `images/` não renomeado para `assets/`
- `_validate_mineru_markdown_links()`: verifica que todos os links relativos do `.md`
  existem no bundle antes de declarar `bundle_status=available`

**Docling — derived items com `type`, `source`, `text`:**
- Description items: `"type": "picture_description"`, `"source": "docling"`,
  `"text": desc_text.strip()`
- Classification items adicionados a `derived_content_by_page` (antes só em `parser_native_pages`):
  `"type": "picture_classification"`, `"source": "docling"`, `"text": "<label> (<score>)"`,
  `"metadata": {...}`
- `has_derived` cobre description + classification; substitui `has_descriptions`

**artifacts.py — JSONL só escrito quando mapping disponível:**
- `jsonl_available = mapping_complete`
- `jsonl_written = jsonl_selected and jsonl_available`
- `output.document_jsonl` = `None` quando não escrito

**post_validation.py — `document.jsonl` com `present=false`:**
- Validação pula checagem de arquivo quando `metrics.artifacts.document_jsonl.present=false`
- Protege tanto `validate_post_execution` quanto `validate_resume_candidate`

**scripts/windows/check_envs.ps1:**
- `visual-enrichment` adicionado à lista de ambientes verificados com check de `paddleocr`

**scripts/windows/setup_visual_enrichment.ps1:**
- `python` → `py -3.12` para criação do venv
- `paddlepaddle` → `paddlepaddle==3.2.0` (versão fixada)

**requirements/windows/visual_enrichment.txt:**
- `paddlepaddle==3.2.0` fixado

**PaddleOCR visual worker — model dirs explícitos:**
- `visual_worker.py._load_paddleocr()` aceita `det_model_dir` e `rec_model_dir`
- `VisualWorkerClient.__init__()` aceita e repassa via config JSON ao worker
- Worker lê os dirs do config de inicialização
- Perfil `full_cpu_local_visual`: `visual_det_model_dir` e `visual_rec_model_dir` com
  paths locais `models/liteparse/paddleocr/det` e `.../rec`
- Demais perfis PyMuPDF recebem as novas chaves com `null`

**PyMuPDF — preflight checks de visual enrichment:**
- Quando `visual_enrichment_enabled=true`, `preflight_profile()` valida:
  1. Worker Python executável (via `_resolve_visual_worker_python`)
  2. Diretório SmolVLM (`visual_description_model`)
  3. Dirs opcionais det/rec (`visual_det_model_dir`, `visual_rec_model_dir`)
  4. Imports do worker via probe subprocess (`paddleocr`, `transformers`, `torch`)

---

## Etapa 3 — Suítes schema v3

**Status:** implementado — aguardando commit e validação no Windows Server

Quatro suítes adicionadas a `config/benchmark_profiles.json`:

### `windows_source_preservation_v3`

13 entradas — todos os 7 parsers com perfis puros (sem enriquecimento visual externo):

```text
pymupdf/native
pymupdf/ocr_auto_rapidtess
docling/native
docling/ocr_auto
mineru/txt
mineru/auto
paddleocr/mvp_structured
liteparse/native
liteparse/ocr_auto_tesseract
unstructured/fast_native
unstructured/auto_ocr
xberg/native_markdown
xberg/ocr_auto_tesseract
```

Artefatos esperados: `raw.md`, `document.md`, `document.jsonl`, `metrics.json`, `run.log`, `native/`.

### `windows_max_quality_cpu_v3`

7 entradas — `full_cpu_local` em todos os 7 parsers.
Capacidade máxima sem enriquecimento visual.

### `windows_version_candidates_v3`

3 entradas — perfis experimentais para comparação de versão:

```text
xberg/full_cpu_layout
paddleocr/ppstructure_v6_experimental
docling/ocr_auto_table_v2
```

Não entra no ranking principal. Destina-se a comparações controladas
de versão/configuração em branch separada.

### `windows_enriched_visual_cpu_v3`

7 entradas — PyMuPDF com `full_cpu_local_visual` + demais com `full_cpu_local`.
Requer `.venvs/visual-enrichment` com PaddleOCR e SmolVLM carregados localmente.
Artefatos incluem `document.enriched.md` com blocos `derived:start`.

---

## Próximo passo

```text
[2026-09-04] Bugs críticos identificados pela revisão completa do código-fonte.

Sequência obrigatória:
  1. Corrigir bugs críticos #1–#7 (ver PLANO_CORRETIVO_DESENVOLVEDOR.md)
  2. Corrigir bugs altos #8–#11 após inspeção no servidor
  3. Validar no Windows Server com documento que exerça: imagens, figuras,
     tabelas mescladas e páginas em branco
  4. Só então avançar para as suítes v3 formais e fixtures schema3
```

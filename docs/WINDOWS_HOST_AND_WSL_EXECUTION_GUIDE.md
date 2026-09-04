# Guia completo de testes e execuções em WSL e Windows host

> Caminho recomendado no repositório: `docs/WINDOWS_HOST_AND_WSL_EXECUTION_GUIDE.md`

> Snapshot revisado: branch `perf/parser-runtime-optimization`, commit `1cb9cfafa719e939cd729e7f1b1366ad8ee9173f`, árvore `12e36214fc59eb497d549d842b045071c19e6528`, commit publicado em `2026-09-03T16:35:48Z`.

> Este documento descreve o código existente nesse snapshot. Como a branch é móvel, confirme o commit antes de executar uma campanha formal.

Este guia reúne os comandos de instalação, preparação de modelos, testes unitários, testes funcionais, preflight, deep smoke, execução por suíte, execução por parser, execução direta dos adaptadores, diagnósticos e pós processamento que existem no repositório para WSL e Windows host nativo.

O objetivo é permitir que uma pessoa execute os caminhos disponíveis sem precisar deduzir argumentos a partir do código.

Arquivos centrais usados como fonte desta documentação:

- [`scripts/run_batch.py`](../scripts/run_batch.py)
- [`scripts/run_runtime_campaign.py`](../scripts/run_runtime_campaign.py)
- [`scripts/parser_preflight.py`](../scripts/parser_preflight.py)
- [`scripts/parser_deep_smoke.py`](../scripts/parser_deep_smoke.py)
- [`config/benchmark_profiles.json`](../config/benchmark_profiles.json)
- [`config/runtime_campaign.json`](../config/runtime_campaign.json)
- [`src/benchmark/runtime_io.py`](../src/benchmark/runtime_io.py)
- [`src/benchmark/artifact_policy.py`](../src/benchmark/artifact_policy.py)
- [`src/benchmark/runtime_specs.py`](../src/benchmark/runtime_specs.py)
- [`src/benchmark/execution_paths.py`](../src/benchmark/execution_paths.py)
- [`src/benchmark/paths.py`](../src/benchmark/paths.py)
- [`scripts/windows/run_benchmark_a.ps1`](../scripts/windows/run_benchmark_a.ps1)
- [`scripts/windows/run_all_features_host.ps1`](../scripts/windows/run_all_features_host.ps1)
- [`scripts/windows/check_server_readiness.ps1`](../scripts/windows/check_server_readiness.ps1)


# Sumário

- 1. Convenções e caminhos usados nos exemplos
- 2. Escolha do ambiente correto
- 3. Sequência recomendada para Windows Server
- 4. WSL: testes comuns, Docker e campanha de runtime
- 5. Windows host: instalação dos ambientes
- 6. Windows host: preparação e verificação dos modelos
- 7. Windows host: testes comuns e testes por parser
- 8. Deep smoke e readiness gate
- 9. Orquestrador run_batch.py: referência completa
- 10. Suítes disponíveis e comandos de execução
- 11. Wrappers PowerShell oficiais
- 12. Execução de um único parser e perfil
- 13. Execução direta de cada adaptador
- 14. Perfis disponíveis e opções internas
- 15. Artefatos e estrutura de saída
- 16. Preflight, dry run, resume, force e resume check
- 17. Diagnósticos e utilitários
- 18. Scripts baseline legados
- 19. Logs, códigos de saída e validação
- 20. Solução de problemas
- 21. Receitas completas copiáveis
- 22. Apêndice: todos os testes e comandos


# 1. Convenções e caminhos usados nos exemplos

Os exemplos de Windows usam o caminho informado para o servidor:

```powershell
$Repo = 'C:\victor.perone\projects\document-ai-benchmark'
$InputDir = Join-Path $Repo 'data\raw\batch'
$OutputBase = Join-Path $Repo 'outputs\v3'
$CorePython = Join-Path $Repo '.venvs\core\Scripts\python.exe'

Set-Location $Repo
```

Variáveis adicionais usadas nos comandos diretos:

```powershell
$Pdf = Join-Path $InputDir 'arquivo.pdf'
$DirectOutput = Join-Path $Repo 'outputs\v3-direct'

$PyMuPDFPython = Join-Path $Repo '.venvs\pymupdf\Scripts\python.exe'
$DoclingPython = Join-Path $Repo '.venvs\docling\Scripts\python.exe'
$MinerUPython = Join-Path $Repo '.venvs\mineru\Scripts\python.exe'
$PaddlePython = Join-Path $Repo '.venvs\paddleocr\Scripts\python.exe'
$LiteParsePython = Join-Path $Repo '.venvs\liteparse\Scripts\python.exe'
$UnstructuredPython = Join-Path $Repo '.venvs\unstructured\Scripts\python.exe'
$XbergPython = Join-Path $Repo '.venvs\xberg\Scripts\python.exe'

$DoclingModelRoot = Join-Path $Repo 'models\docling\docling\models'
$MinerUModelRoot = Join-Path $Repo 'models\mineru'
$PaddleModelRoot = Join-Path $Repo 'models\paddleocr\official_models'
$LiteParseModelRoot = Join-Path $Repo 'models\liteparse\smolvlm'
$UnstructuredModelRoot = Join-Path $Repo 'models\unstructured'
$XbergModelRoot = Join-Path $Repo 'models\xberg'
$VisualModelRoot = Join-Path $Repo 'models\visual-enrichment'
```

> ❗ O `run_batch.py` acrescenta automaticamente o diretório `host` quando `--runtime host` é usado.

Portanto, este comando:

```powershell
& $CorePython .\scripts\run_batch.py `
  --runtime host `
  --output-root 'C:\victor.perone\projects\document-ai-benchmark\outputs\v3' `
  --suite windows_all_features_host `
  --input-dir 'C:\victor.perone\projects\document-ai-benchmark\data\raw\batch' `
  --force
```

grava os jobs em:

```text
C:\victor.perone\projects\document-ai-benchmark\outputs\v3\host\<parser>\<documento>\<perfil>\
```

Não passe `...\outputs\v3\host` como `--output-root`, salvo quando realmente quiser produzir `...\outputs\v3\host\host`.

Na execução direta de um adaptador, o sufixo `host` não é acrescentado. O adaptador usa exatamente o valor recebido em `--output-root`.


## 1.1 PowerShell e o operador de chamada

Quando o executável está armazenado em uma variável, use `&`:

```powershell
& $CorePython --version
```

Quando um argumento contém espaço, mantenha o valor entre aspas ou use uma variável `Path`.


## 1.2 Correção do nome do teste de campanha

O nome correto é:

```bash
python3 ./tests/test_runtime_campaign.py
```

Não existe `tests/test_runtime_campaing.py`. Além disso, `_` não precisa ser escapado no Bash nem no PowerShell.

Os argumentos `--plan`, '`--execute`', `--phase` e `--input-dir` pertencem ao runner `scripts/run_runtime_campaign.py`, não ao arquivo de teste.


# 2. Escolha do ambiente correto

| Tarefa | WSL | Windows host nativo |
|---|---|---|
| Testes comuns de Python | Sim | Sim, pelo venv `core` |
| Build e teste dos containers | Sim | Opcional |
| Parsers PyMuPDF, Docling, MinerU, PaddleOCR e LiteParse via Docker | Sim | Não é o caminho desta campanha host |
| Unstructured | Não há serviço Compose | Sim |
| Xberg | Não há serviço Compose | Sim |
| Readiness gate oficial | Não. O script rejeita WSL. | Sim |
| Deep smoke completo com sete parsers | Não. Apenas validação da fixture. | Sim |
| Campanha `windows_all_features_host` | Não como runtime Docker | Sim |

Suporte declarado em `src/benchmark/runtime_specs.py`:

| Parser | Docker | Host | Ambiente Windows |
|---|---|---|---|
| pymupdf | Sim | Sim | `.venvs\\pymupdf` |
| docling | Sim | Sim | `.venvs\\docling` |
| mineru | Sim | Sim | `.venvs\\mineru` |
| paddleocr | Sim | Sim | `.venvs\\paddleocr` |
| liteparse | Sim | Sim | `.venvs\\liteparse` |
| unstructured | Não | Sim | `.venvs\\unstructured` |
| xberg | Não | Sim | `.venvs\\xberg` |


# 3. Sequência recomendada para Windows Server

A sequência abaixo usa instalação limpa, preparação dos modelos, verificação offline, testes, readiness e campanha completa.

```powershell
$Repo = 'C:\victor.perone\projects\document-ai-benchmark'
$InputDir = Join-Path $Repo 'data\raw\batch'
$OutputBase = Join-Path $Repo 'outputs\v3'

Set-Location $Repo

git fetch origin
git checkout perf/parser-runtime-optimization
git pull --ff-only origin perf/parser-runtime-optimization
git rev-parse HEAD

.\scripts\windows\setup_envs.ps1
.\scripts\windows\check_envs.ps1

.\scripts\windows\prepare_all_models.ps1 -Mode Prepare
.\scripts\windows\prepare_all_models.ps1 -Mode Verify

& .\.venvs\core\Scripts\python.exe .\scripts\run_tests.py

$Parsers = @(
  'pymupdf',
  'docling',
  'mineru',
  'paddleocr',
  'liteparse',
  'unstructured',
  'xberg'
)

foreach ($Parser in $Parsers) {
  .\scripts\windows\run_host_parser_tests.ps1 `
    -Parser $Parser `
    -VerboseOutput
}

.\scripts\windows\run_deep_smoke_all.ps1 `
  -OutputRoot 'outputs\deep_smoke' `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput

.\scripts\windows\check_server_readiness.ps1 `
  -OutputRoot 'outputs\deep_smoke' `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput

.\scripts\windows\run_all_features_host.ps1 `
  -InputDir $InputDir `
  -OutputRoot $OutputBase `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput
```

> ❗ `check_server_readiness.ps1` exige working tree limpo. Um arquivo de documentação ainda não commitado fará esse gate falhar até ser commitado ou removido.

> ❗ A fase `Prepare` pode usar rede. `Verify`, preflight, deep smoke e a execução formal foram desenhados para usar modelos locais e variáveis de modo offline.


# 4. WSL: testes comuns, Docker e campanha de runtime


## 4.1 Entrar no repositório e confirmar o snapshot

```bash
cd ~/workspace/document-ai-benchmark

git fetch origin
git checkout perf/parser-runtime-optimization
git pull --ff-only origin perf/parser-runtime-optimization
git rev-parse HEAD
git status --short
```

O commit documentado é `1cb9cfafa719e939cd729e7f1b1366ad8ee9173f`.


## 4.2 Verificar WSL e Docker

```bash
echo "$WSL_DISTRO_NAME"
uname -r
python3 --version
docker version
docker compose version
docker info
docker compose config
docker compose config --services
```

Serviços Compose presentes no snapshot:

```text
pymupdf
docling
mineru
paddleocr
liteparse
```

Unstructured e Xberg não possuem serviços no `compose.yaml` e devem ser testados no Windows host.


## 4.3 Testes comuns

Runner agregado, sem argumentos:

```bash
python3 scripts/run_tests.py
```

O runner:

1. compila `scripts/`, '`src/`', `tests/` e `parser_tests/`;
2. executa todos os `test_*.py` em `tests/`;
3. não executa os testes específicos dos parsers, pois cada parser tem dependências isoladas.

Comando equivalente de descoberta:

```bash
python3 -m unittest discover \
  --start-directory tests \
  --pattern 'test_*.py' \
  --verbose
```

Teste da campanha de runtime, pelo arquivo:

```bash
python3 ./tests/test_runtime_campaign.py
```

Teste da campanha pelo nome do módulo:

```bash
python3 -m unittest tests.test_runtime_campaign -v
```

Classe ou método específico:

```bash
python3 -m unittest \
  tests.test_runtime_campaign.TestPhaseResultSchema.test_pass_result_has_required_fields \
  -v
```


## 4.4 Executar qualquer teste comum individual

```bash
python3 -m unittest tests.test_run_batch_cli -v
python3 -m unittest tests.test_run_batch_preflight -v
python3 -m unittest tests.test_process_tree -v
python3 -m unittest tests.test_visual_worker -v
```

Padrão geral:

```bash
python3 -m unittest tests.<nome_do_arquivo_sem_py> -v
```


## 4.5 Build dos containers

```bash
docker compose build
```

Build seletivo:

```bash
docker compose build pymupdf docling mineru paddleocr liteparse
```

Build limpo de um serviço:

```bash
docker compose build --no-cache docling
```


## 4.6 Testes específicos dos parsers em Docker

O runner `scripts/run_parser_tests.py` aceita um único argumento posicional: o nome do parser.

```bash
python3 scripts/run_parser_tests.py pymupdf
python3 scripts/run_parser_tests.py docling
python3 scripts/run_parser_tests.py mineru
python3 scripts/run_parser_tests.py paddleocr
python3 scripts/run_parser_tests.py liteparse
```

Não use esse runner para `unstructured` ou `xberg`, pois eles não possuem serviço Compose.


## 4.7 Validar a fixture do deep smoke em WSL

A validação da fixture não executa os sete parsers e pode rodar em WSL:

```bash
python3 scripts/parser_deep_smoke.py --validate-fixture-only
```

Gerar novamente a fixture determinística:

```bash
python3 scripts/generate_deep_smoke_fixture.py
python3 scripts/parser_deep_smoke.py --validate-fixture-only
```

A execução completa de `parser_deep_smoke.py`, sem `--validate-fixture-only`, exige Windows nativo.


## 4.8 Planejar a campanha de runtime

Sem argumentos, o runner apenas imprime o plano:

```bash
python3 scripts/run_runtime_campaign.py
```

Forma explícita:

```bash
python3 scripts/run_runtime_campaign.py --plan
```

Selecionar uma fase:

```bash
python3 scripts/run_runtime_campaign.py \
  --plan \
  --phase smoke_limit1
```

Substituir o diretório de entrada no plano:

```bash
python3 scripts/run_runtime_campaign.py \
  --plan \
  --input-dir data/raw/batch
```


## 4.9 Executar a campanha de runtime

```bash
python3 scripts/run_runtime_campaign.py \
  --execute \
  --input-dir data/raw/batch
```

Executar uma única fase:

```bash
python3 scripts/run_runtime_campaign.py \
  --execute \
  --phase smoke_limit1 \
  --input-dir data/raw/batch
```

Fases configuradas em `config/runtime_campaign.json`:

- `smoke_limit1`
- `smoke_full`
- `default_limit1`
- `default_full`
- `full_corpus_limit1`
- `full_corpus_full`
- `diagnostic_ocr_limit1`
- `diagnostic_ocr_full`
- `visual_ablation_limit1`
- `visual_ablation_full`

Para cada fase, o runner faz exatamente:

1. `run_batch.py --preflight`;
2. `run_batch.py --force`;
3. `run_batch.py --resume-check`.

A campanha para na primeira fase que falhar e grava:

```text
logs/runtime_campaign_<timestamp>.json
logs/runtime_campaign_<timestamp>.md
```

> ❗ `run_runtime_campaign.py` não possui argumento `--runtime`. Por padrão, os processos filhos usam Docker. A variável `BENCHMARK_RUNTIME` pode alterar esse padrão, mas para Windows Server os wrappers PowerShell e `run_batch.py --runtime host` são mais explícitos.


## 4.10 Executar `run_batch.py` em WSL com Docker

```bash
python3 scripts/run_batch.py \
  --suite smoke \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-smoke \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

Planejar sem executar:

```bash
python3 scripts/run_batch.py \
  --suite full_corpus_expanded \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-plan \
  --artifacts all \
  --dry-run
```

Preflight sem inferência:

```bash
python3 scripts/run_batch.py \
  --suite ocr_primary_expanded \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-preflight \
  --artifacts all \
  --preflight
```

As suítes que contêm Unstructured ou Xberg não podem ser executadas com `--runtime docker`.


## 4.11 Execução direta de adaptador em Docker

O caminho recomendado continua sendo `run_batch.py`, pois ele cria o inventário, limpa a saída, aplica modelo local, executa pós validação e registra o lote.

Para executar diretamente, primeiro gere o inventário no mesmo output root:

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/scripts/build_source_inventory.py \
  --input-dir /data/raw/batch \
  --output-dir /outputs/wsl-direct/_source_inventory \
  --only arquivo.pdf
```

Depois execute, por exemplo, Docling:

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  docling \
  /app/src/parsers/docling_v2.py \
  --input /data/raw/batch/arquivo.pdf \
  --output-root /outputs/wsl-direct \
  --profile ocr_auto \
  --artifacts all \
  --verbose
```

Comandos diretos equivalentes para os outros serviços:

```bash
docker compose run --rm -e PYTHONPATH=/app --entrypoint python pymupdf \
  /app/src/parsers/pymupdf_v2.py \
  --input /data/raw/batch/arquivo.pdf \
  --output-root /outputs/wsl-direct \
  --profile ocr_auto_rapidtess \
  --artifacts all \
  --verbose

docker compose run --rm -e PYTHONPATH=/app --entrypoint python mineru \
  /app/src/parsers/mineru_v2.py \
  --input /data/raw/batch/arquivo.pdf \
  --output-root /outputs/wsl-direct \
  --profile auto \
  --artifacts all \
  --verbose

docker compose run --rm -e PYTHONPATH=/app --entrypoint python paddleocr \
  /app/src/parsers/paddleocr_v2.py \
  --input /data/raw/batch/arquivo.pdf \
  --output-root /outputs/wsl-direct \
  --profile mvp_structured \
  --model-root /home/appuser/.paddlex/official_models \
  --artifacts all \
  --verbose

docker compose run --rm -e PYTHONPATH=/app --entrypoint python liteparse \
  /app/src/parsers/liteparse_v2.py \
  --input /data/raw/batch/arquivo.pdf \
  --output-root /outputs/wsl-direct \
  --profile ocr_auto_tesseract \
  --model-artifacts-path /models/liteparse/smolvlm \
  --artifacts all \
  --verbose
```

> ❗ Os entrypoints de PyMuPDF, Docling e MinerU no `compose.yaml` ainda apontam para scripts baseline. O `run_batch.py` substitui o entrypoint pelo adaptador v2. Em execução manual, use `--entrypoint python` e informe explicitamente `..._v2.py` como nos exemplos.


# 5. Windows host: instalação dos ambientes


## 5.1 Verificações prévias

```powershell
$PSVersionTable
[Environment]::OSVersion.VersionString

git --version
py -0p
py -3.12 --version
py -3.11 --version

tesseract --version
tesseract --list-langs
pdfinfo -v
pdftoppm -v

Get-ItemProperty `
  'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
  -Name LongPathsEnabled
```

Python 3.12 é usado por todos os ambientes, exceto LiteParse, que usa Python 3.11 por causa do wheel Windows disponível para `liteparse==2.13.0`.


## 5.2 Instalar todos os ambientes

```powershell
Set-Location 'C:\victor.perone\projects\document-ai-benchmark'

.\scripts\windows\setup_envs.ps1
```

Recriar todos:

```powershell
.\scripts\windows\setup_envs.ps1 -Force
```

Argumentos de `setup_envs.ps1`:

| Argumento | Tipo | Padrão | Efeito |
|---|---|---|---|
| `-Force` | switch | desativado | Remove e recria cada ambiente virtual existente. |

Ordem de instalação:

- `core`
- `pymupdf`
- `docling`
- `liteparse`
- `mineru`
- `paddleocr`
- `visual-enrichment`
- `unstructured`
- `xberg`


## 5.3 Instalar ambientes individualmente

| Componente | Script | Finalidade |
|---|---|---|
| core | setup_core.ps1 | Python 3.12; runner comum e testes. |
| pymupdf | setup_pymupdf.ps1 | Python 3.12; PyMuPDF4LLM 1.28.2. |
| docling | setup_docling.ps1 | Python 3.12; Docling 2.122.0. |
| liteparse | setup_liteparse.ps1 | Python 3.11; LiteParse 2.13.0 e Transformers 5.16.1. |
| mineru | setup_mineru.ps1 | Python 3.12; MinerU 3.4.4 e Torch CPU. |
| paddleocr | setup_paddleocr.ps1 | Python 3.12; PaddleOCR 3.7.0 e PaddlePaddle CPU 3.2.0. |
| visual enrichment | setup_visual_enrichment.ps1 | Python 3.12; PaddleOCR e SmolVLM do worker visual. |
| unstructured | setup_unstructured.ps1 | Python 3.12; Unstructured 0.27.1. |
| xberg | setup_xberg.ps1 | Python 3.12; Xberg 1.0.14 por wheel binário. |

### `setup_core.ps1`

```powershell
.\scripts\windows\setup_core.ps1
.\scripts\windows\setup_core.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.

### `setup_pymupdf.ps1`

```powershell
.\scripts\windows\setup_pymupdf.ps1
.\scripts\windows\setup_pymupdf.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.

### `setup_docling.ps1`

```powershell
.\scripts\windows\setup_docling.ps1
.\scripts\windows\setup_docling.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.

### `setup_liteparse.ps1`

```powershell
.\scripts\windows\setup_liteparse.ps1
.\scripts\windows\setup_liteparse.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.

### `setup_mineru.ps1`

```powershell
.\scripts\windows\setup_mineru.ps1
.\scripts\windows\setup_mineru.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.

### `setup_paddleocr.ps1`

```powershell
.\scripts\windows\setup_paddleocr.ps1
.\scripts\windows\setup_paddleocr.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.

### `setup_visual_enrichment.ps1`

```powershell
.\scripts\windows\setup_visual_enrichment.ps1
.\scripts\windows\setup_visual_enrichment.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.

### `setup_unstructured.ps1`

```powershell
.\scripts\windows\setup_unstructured.ps1
.\scripts\windows\setup_unstructured.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.

### `setup_xberg.ps1`

```powershell
.\scripts\windows\setup_xberg.ps1
.\scripts\windows\setup_xberg.ps1 -Force
```

Único argumento: `-Force`, que recria o ambiente correspondente.


## 5.4 Verificar todos os ambientes e ferramentas externas

```powershell
.\scripts\windows\check_envs.ps1
```

Esse script não possui argumentos. Ele verifica:

- existência dos ambientes;
- versões fixadas;
- `pip check`;
- Tesseract;
- `pdftoppm`;
- `pdfinfo`.

Comandos manuais adicionais:

```powershell
$Venvs = @(
  'core',
  'pymupdf',
  'docling',
  'mineru',
  'paddleocr',
  'liteparse',
  'visual-enrichment',
  'unstructured',
  'xberg'
)

foreach ($Venv in $Venvs) {
  $Python = Join-Path $Repo ".venvs\$Venv\Scripts\python.exe"
  & $Python --version
  & $Python -m pip check
}
```


# 6. Windows host: preparação e verificação dos modelos

A fase `Prepare` pode baixar arquivos. A fase `Verify` deve usar somente artefatos locais.


## 6.1 Todos os componentes

```powershell
.\scripts\windows\prepare_all_models.ps1 -Mode Prepare
.\scripts\windows\prepare_all_models.ps1 -Mode Prepare -Force
.\scripts\windows\prepare_all_models.ps1 -Mode Verify
```

| Argumento | Valores | Padrão | Efeito |
|---|---|---|---|
| `-Mode` | `Prepare`, `Verify` | `Prepare` | Escolhe aquisição/certificação ou verificação offline. |
| `-Force` | switch | desativado | Recria artefatos durante `Prepare`; é inválido com `Verify`. |

Ordem de componentes:

- Docling
- MinerU
- PaddleOCR
- LiteParse
- visual enrichment
- Unstructured
- Xberg


## 6.2 Docling

```powershell
.\scripts\windows\prepare_docling_models.ps1 -Mode Prepare
.\scripts\windows\prepare_docling_models.ps1 -Mode Prepare -Force
.\scripts\windows\prepare_docling_models.ps1 -Mode Verify

.\scripts\windows\prepare_docling_models.ps1 `
  -Python $DoclingPython `
  -ModelRoot $DoclingModelRoot `
  -Mode Verify
```

| Argumento | Valores | Padrão | Descrição |
|---|---|---|---|
| `-Python` | caminho | `.venvs\\docling\\Scripts\\python.exe` | Executável do ambiente Docling. |
| `-ModelRoot` | caminho | `models\\docling\\docling\\models` | Raiz dos artefatos Docling. |
| `-Mode` | `Prepare`, `Verify` | `Prepare` | Aquisição/certificação ou verificação. |
| `-Force` | switch | desativado | Remove e readquire na fase Prepare. |
| `-ValidateOnly` | switch | desativado | Alias legado para `-Mode Verify`. |

Não combine `-Force` com `-Mode Verify` nem com `-ValidateOnly`.


## 6.3 MinerU

```powershell
.\scripts\windows\prepare_mineru_models.ps1 -Mode Prepare
.\scripts\windows\prepare_mineru_models.ps1 -Mode Prepare -Force
.\scripts\windows\prepare_mineru_models.ps1 -Mode Verify

.\scripts\windows\prepare_mineru_models.ps1 `
  -Mode Verify `
  -FixturePath (Join-Path $Repo 'fixtures\deep_smoke\deep_smoke.pdf')
```

| Argumento | Valores | Padrão | Descrição |
|---|---|---|---|
| `-Mode` | `Prepare`, `Verify` | `Prepare` | Prepara ou verifica o bundle local. |
| `-Force` | switch | desativado | Recria o bundle durante Prepare. |
| `-FixturePath` | PDF | fixture de deep smoke | PDF usado no smoke de validação dos modelos. |


## 6.4 PaddleOCR

```powershell
.\scripts\windows\prepare_paddleocr_models.ps1 -Mode Prepare
.\scripts\windows\prepare_paddleocr_models.ps1 -Mode Prepare -Force
.\scripts\windows\prepare_paddleocr_models.ps1 -Mode Verify
```

| Argumento | Valores | Padrão | Descrição |
|---|---|---|---|
| `-Mode` | `Prepare`, `Verify` | `Prepare` | Prepara ou verifica todos os submodelos do perfil completo. |
| `-Force` | switch | desativado | Remove o root antes de preparar novamente. |


## 6.5 LiteParse

```powershell
.\scripts\windows\prepare_liteparse_models.ps1 -Mode Prepare
.\scripts\windows\prepare_liteparse_models.ps1 -Mode Prepare -Force
.\scripts\windows\prepare_liteparse_models.ps1 -Mode Verify
```

| Argumento | Valores | Padrão | Descrição |
|---|---|---|---|
| `-Mode` | `Prepare`, `Verify` | `Prepare` | Prepara ou valida o SmolVLM usado pelo LiteParse. |
| `-Force` | switch | desativado | Recria os artefatos durante Prepare. |


## 6.6 Worker de enriquecimento visual

```powershell
.\scripts\windows\prepare_visual_enrichment_models.ps1 -Mode Prepare
.\scripts\windows\prepare_visual_enrichment_models.ps1 -Mode Prepare -Force
.\scripts\windows\prepare_visual_enrichment_models.ps1 -Mode Verify
```

| Argumento | Valores | Padrão | Descrição |
|---|---|---|---|
| `-Mode` | `Prepare`, `Verify` | `Prepare` | Prepara ou verifica PaddleOCR local e SmolVLM. |
| `-Force` | switch | desativado | Recria os artefatos durante Prepare. |


## 6.7 Unstructured

```powershell
.\scripts\windows\prepare_unstructured_models.ps1 -Mode Prepare
.\scripts\windows\prepare_unstructured_models.ps1 -Mode Prepare -Force
.\scripts\windows\prepare_unstructured_models.ps1 -Mode Verify
```

| Argumento | Valores | Padrão | Descrição |
|---|---|---|---|
| `-Mode` | `Prepare`, `Verify` | `Prepare` | Prepara ou verifica YOLOX, Table Transformer e spaCy. |
| `-Force` | switch | desativado | Recria o bundle durante Prepare. |


## 6.8 Xberg

```powershell
.\scripts\windows\prepare_xberg_models.ps1 -Mode Prepare
.\scripts\windows\prepare_xberg_models.ps1 -Mode Prepare -Force
.\scripts\windows\prepare_xberg_models.ps1 -Mode Verify

.\scripts\windows\prepare_xberg_models.ps1 `
  -Mode Verify `
  -FixturePath (Join-Path $Repo 'fixtures\deep_smoke\deep_smoke.pdf')
```

| Argumento | Valores | Padrão | Descrição |
|---|---|---|---|
| `-Mode` | `Prepare`, `Verify` | `Prepare` | Prepara ou verifica o cache local de layout e demais recursos. |
| `-Force` | switch | desativado | Recria o cache durante Prepare. |
| `-FixturePath` | PDF | fixture de deep smoke | PDF usado na validação funcional. |


# 7. Windows host: testes comuns e testes por parser


## 7.1 Testes comuns

```powershell
& $CorePython .\scripts\run_tests.py
```

Descoberta direta:

```powershell
& $CorePython -m unittest discover `
  --start-directory .\tests `
  --pattern 'test_*.py' `
  --verbose
```

Teste da campanha:

```powershell
& $CorePython .\tests\test_runtime_campaign.py
& $CorePython -m unittest tests.test_runtime_campaign -v
```

Teste comum específico:

```powershell
& $CorePython -m unittest tests.test_run_batch_cli -v
& $CorePython -m unittest tests.test_runtime_specs -v
```


## 7.2 Runner dos testes específicos

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser docling `
  -VerboseOutput
```

| Argumento | Valores | Padrão | Descrição |
|---|---|---|---|
| `-Parser` | `pymupdf`, '`docling`', `mineru`, '`paddleocr`', `liteparse`, '`unstructured`', `xberg` | obrigatório | Seleciona o venv e a pasta de testes. |
| `-TestPath` | arquivo ou subdiretório | todos os testes | Executa somente o alvo indicado dentro de `parser_tests/<parser>`. |
| `-VerboseOutput` | switch | desativado | Adiciona `-v` ao unittest. |
| `-SingleThread` | switch | desativado | Para Unstructured, define `OMP_THREAD_LIMIT=1`. Não use no smoke completo. |
| `-FunctionalTests` | switch | desativado | Define `BENCHMARK_WINDOWS_FUNCTIONAL=1` e libera a inferência real. |
| `-FunctionalTimeoutSeconds` | 1 a 86400 | 3600 | Timeout informado aos testes funcionais. |

Executar todos os parsers, sem inferência funcional:

```powershell
$Parsers = @(
  'pymupdf',
  'docling',
  'mineru',
  'paddleocr',
  'liteparse',
  'unstructured',
  'xberg'
)

foreach ($Parser in $Parsers) {
  .\scripts\windows\run_host_parser_tests.ps1 `
    -Parser $Parser `
    -VerboseOutput
}
```

Executar também o teste funcional de cada parser:

```powershell
foreach ($Parser in $Parsers) {
  .\scripts\windows\run_host_parser_tests.ps1 `
    -Parser $Parser `
    -VerboseOutput `
    -FunctionalTests `
    -FunctionalTimeoutSeconds 7200
}
```

Executar um arquivo específico:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_preflight.py `
  -VerboseOutput
```

Executar somente o arquivo funcional:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_functional_deep_smoke.py `
  -VerboseOutput `
  -FunctionalTests `
  -FunctionalTimeoutSeconds 7200
```

> ❗ Sem `-FunctionalTests`, `test_functional_deep_smoke.py` é pulado por design. O readiness gate trata qualquer skip funcional como falha.


# 8. Deep smoke e readiness gate


## 8.1 Deep smoke dos sete parsers

```powershell
.\scripts\windows\run_deep_smoke_all.ps1
```

Com parâmetros:

```powershell
.\scripts\windows\run_deep_smoke_all.ps1 `
  -OutputRoot 'outputs\deep_smoke' `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput
```

| Argumento | Tipo | Padrão | Descrição |
|---|---|---|---|
| `-OutputRoot` | caminho | `outputs\\deep_smoke` | Root base. O runner host acrescenta `host` aos jobs. |
| `-JobTimeoutSeconds` | 1 a 86400 | 3600 | Timeout de cada parser. |
| `-VerboseOutput` | switch | desativado | Exibe diagnóstico detalhado dos adapters. |

Esse wrapper:

1. define modo offline;
2. executa `-Mode Verify` para todos os bundles;
3. chama `scripts/parser_deep_smoke.py`;
4. exige sucesso dos sete perfis:

- `pymupdf/full_cpu_local_visual`
- `docling/full_cpu_local`
- `mineru/full_cpu_local`
- `paddleocr/full_cpu_local`
- `liteparse/full_cpu_local`
- `unstructured/full_cpu_local`
- `xberg/full_cpu_layout`


## 8.2 CLI direta do deep smoke

```powershell
& $CorePython .\scripts\parser_deep_smoke.py `
  --output-root (Join-Path $Repo 'outputs\deep_smoke') `
  --job-timeout-seconds 7200 `
  --verbose-output
```

| Argumento | Tipo | Padrão | Descrição |
|---|---|---|---|
| `--output-root` | Path | `<repo>\\outputs\\deep_smoke` | Root base do smoke. |
| `--job-timeout-seconds` | inteiro positivo | 3600 | Timeout por job. |
| `--verbose-output` | flag | desativado | Exibe saída detalhada. |
| `--validate-fixture-only` | flag | desativado | Valida somente fixture e manifesto, sem inferência. |


## 8.3 Readiness gate oficial

```powershell
.\scripts\windows\check_server_readiness.ps1 `
  -OutputRoot 'outputs\deep_smoke' `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput
```

| Argumento | Tipo | Padrão | Descrição |
|---|---|---|---|
| `-OutputRoot` | caminho | `outputs\\deep_smoke` | Saída do deep smoke invocado pelo gate. |
| `-JobTimeoutSeconds` | 1 a 86400 | 3600 | Timeout usado nos testes funcionais e no deep smoke. |
| `-VerboseOutput` | switch | desativado | Propaga diagnóstico ao deep smoke. |

Condições importantes:

- deve rodar em Windows nativo;
- rejeita WSL;
- exige Git disponível;
- exige working tree limpo;
- verifica ambientes, modelos, testes comuns, testes por parser e deep smoke;
- procura resíduos temporários, downloads incompletos e processos Python vazados;
- exige zero testes funcionais pulados;
- considera sete parsers prontos somente quando encontra os marcadores do deep smoke.

Relatórios:

```text
logs\windows_readiness\<timestamp>\readiness.log
logs\windows_readiness\<timestamp>\summary.txt
logs\windows_readiness\<timestamp>\failures.txt
logs\windows_readiness\<timestamp>\<gate>.log
```

Marcadores finais:

```text
SERVER_READINESS=PASS
COMMIT=<sha>
PARSERS_READY=pymupdf,docling,mineru,paddleocr,liteparse,unstructured,xberg
PARSERS_FAILED=
FUNCTIONAL_TESTS_SKIPPED=0
```


# 9. Orquestrador `run_batch.py`: referência completa

Fonte: [`scripts/run_batch.py`](../scripts/run_batch.py)


## 9.1 Ajuda

```powershell
& $CorePython .\scripts\run_batch.py --help
```

```bash
python3 scripts/run_batch.py --help
```


## 9.2 Todos os argumentos

| Argumento | Tipo | Padrão | Efeito |
|---|---|---|---|
| `--input-dir DIR` | Diretório de PDFs | Config `data/raw/batch` | Descoberta não recursiva de `*.pdf`, ordenada pelo nome. |
| `--limit N` | Inteiro positivo | sem limite | Executa os primeiros N PDFs da descoberta determinística. |
| `--suite SUITE` | Nome de suíte | default quando não há parser | Seleciona vários pares parser/perfil. |
| `--parser PARSER` | Nome de parser | nenhum | Seleciona um único parser; exige `--profile`. |
| `--profile PROFILE` | Nome de perfil | nenhum | Seleciona um perfil; exige `--parser`. |
| `--output-root DIR` | Diretório base | Config `outputs` | Em host, acrescenta automaticamente `host`. |
| `--artifacts SPEC` | Seletor | `all` | Artefatos separados por espaço, vírgula ou o alias `all`. |
| `--resume` | flag | ativo | Reutiliza jobs cuja proveniência e artefatos passam na validação. |
| `--force` | flag | desativado | Ignora resultados existentes e executa novamente. |
| `--continue-on-error` | flag | desativado | Segue para o próximo job após falha. |
| `--dry-run` | modo exclusivo | desativado | Mostra o plano e não executa. |
| `--preflight` | modo exclusivo | desativado | Valida infraestrutura, parser, perfil e modelos sem inferência. |
| `--resume-check` | modo exclusivo | desativado | Verificação read only: 0 quando todos seriam skip; 1 quando há pendências. |
| `--runtime {docker,host}` | enum | env `BENCHMARK_RUNTIME` ou docker | Escolhe containers ou venvs do host. |
| `--compose-override FILE` | arquivo Compose | nenhum | Overlay adicional. É inválido com runtime host. |
| `--no-summary` | flag | desativado | Não executa scripts de resumo após o lote. |
| `--job-timeout-seconds N` | Inteiro positivo | 3600 | No host, termina a árvore do processo quando o limite é excedido. |
| `--verbose-output` | flag | desativado | Acrescenta `--verbose` ao adaptador. |


## 9.3 Restrições de combinação

- `--parser` sem `--profile`: erro.
- `--profile` sem `--parser`: erro.
- `--suite` e `--parser`: mutuamente exclusivos.
- `--dry-run`, `--preflight` e `--resume-check`: mutuamente exclusivos.
- `--force` com `--resume-check`: erro semântico.
- `--compose-override` com `--runtime host`: erro.
- parser host only com `--runtime docker`: erro antes de inspecionar Docker.


## 9.4 Fases internas de uma execução normal

1. carrega `config/benchmark_profiles.json`;
2. resolve suíte ou parser/perfil;
3. descobre os PDFs;
4. valida parser e perfil;
5. calcula SHA-256;
6. cria ou valida o plano de resume;
7. cria o inventário de cada PDF usando o ambiente PyMuPDF;
8. limpa somente o diretório leaf de um job pendente;
9. chama o adaptador pelo venv correto;
10. executa pós validação dos artefatos;
11. registra logs, manifest e resultados JSONL;
12. opcionalmente executa scripts de resumo.


## 9.5 Comando host genérico por suíte

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```


## 9.6 Comando host genérico por parser e perfil

```powershell
& $CorePython .\scripts\run_batch.py `
  --parser docling `
  --profile full_cpu_local `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```


## 9.7 Diretório exato de um PDF

O `run_batch.py` recebe um diretório, não um `--input` de arquivo. `--limit 1` escolhe o primeiro PDF em ordem alfabética, não um nome específico.

Para um arquivo exato, use uma destas opções:

1. execução direta do adaptador;
2. diretório temporário contendo somente o PDF;
3. renomear ou organizar a entrada para que o arquivo seja o primeiro e usar `--limit 1`.

Exemplo seguro com diretório temporário:

```powershell
$SingleInput = Join-Path $Repo 'data\raw\single-run'
New-Item -ItemType Directory -Force -Path $SingleInput | Out-Null
Remove-Item (Join-Path $SingleInput '*.pdf') -Force -ErrorAction SilentlyContinue
Copy-Item $Pdf $SingleInput

& $CorePython .\scripts\run_batch.py `
  --parser docling `
  --profile full_cpu_local `
  --runtime host `
  --input-dir $SingleInput `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --no-summary
```


# 10. Suítes disponíveis e comandos de execução


## 10.1 Matriz completa

| Suíte | Pode usar Docker | Pares | Conteúdo |
|---|---|---|---|
| `default` | Sim | 4 | `pymupdf/ocr_auto_rapidtess`<br>`docling/ocr_auto`<br>`mineru/auto`<br>`paddleocr/mvp_structured` |
| `full_corpus` | Sim | 8 | `pymupdf/native`<br>`pymupdf/ocr_auto_rapidtess`<br>`docling/native`<br>`docling/ocr_auto`<br>`mineru/txt`<br>`mineru/auto`<br>`paddleocr/lightweight`<br>`paddleocr/ocr_structured_visual` |
| `ocr_primary` | Sim | 4 | `pymupdf/ocr_auto_rapidtess`<br>`docling/ocr_auto`<br>`mineru/auto`<br>`paddleocr/mvp_structured` |
| `diagnostic_ocr` | Sim | 3 | `pymupdf/ocr_force_rapidtess`<br>`mineru/ocr`<br>`paddleocr/full` |
| `visual_ablation` | Sim | 4 | `docling/ocr_auto`<br>`docling/ocr_auto_visual`<br>`paddleocr/default`<br>`paddleocr/ocr_structured_visual` |
| `smoke` | Sim | 4 | `pymupdf/native`<br>`docling/native`<br>`mineru/txt`<br>`paddleocr/lightweight` |
| `smoke_expanded` | Sim | 5 | `pymupdf/native`<br>`docling/native`<br>`mineru/txt`<br>`paddleocr/lightweight`<br>`liteparse/native` |
| `ocr_primary_expanded` | Sim | 5 | `pymupdf/ocr_auto_rapidtess`<br>`docling/ocr_auto`<br>`mineru/auto`<br>`paddleocr/mvp_structured`<br>`liteparse/ocr_auto_tesseract` |
| `visual_ablation_expanded` | Sim | 6 | `docling/ocr_auto`<br>`docling/ocr_auto_visual`<br>`paddleocr/default`<br>`paddleocr/ocr_structured_visual`<br>`liteparse/ocr_auto_tesseract`<br>`liteparse/ocr_auto_visual` |
| `full_corpus_expanded` | Sim | 11 | `pymupdf/native`<br>`pymupdf/ocr_auto_rapidtess`<br>`docling/native`<br>`docling/ocr_auto`<br>`mineru/txt`<br>`mineru/auto`<br>`paddleocr/lightweight`<br>`paddleocr/ocr_structured_visual`<br>`liteparse/native`<br>`liteparse/ocr_auto_tesseract`<br>`liteparse/ocr_auto_visual` |
| `unstructured_smoke_host` | Host somente | 1 | `unstructured/fast_native` |
| `unstructured_ocr_host` | Host somente | 2 | `unstructured/auto_ocr`<br>`unstructured/hi_res_tables` |
| `xberg_smoke_host` | Host somente | 1 | `xberg/native_markdown` |
| `xberg_ocr_host` | Host somente | 2 | `xberg/ocr_auto_tesseract`<br>`xberg/ocr_auto_tesseract_repair` |
| `windows_smoke_all_host` | Host somente | 7 | `pymupdf/native`<br>`docling/native`<br>`mineru/txt`<br>`paddleocr/lightweight`<br>`liteparse/native`<br>`unstructured/fast_native`<br>`xberg/native_markdown` |
| `windows_ocr_auto_all_host` | Host somente | 7 | `pymupdf/ocr_auto_rapidtess`<br>`docling/ocr_auto`<br>`mineru/auto`<br>`paddleocr/mvp_structured`<br>`liteparse/ocr_auto_tesseract`<br>`unstructured/auto_ocr`<br>`xberg/ocr_auto_tesseract` |
| `full_cpu_local` | Sim | 5 | `pymupdf/full_cpu_local`<br>`docling/full_cpu_local`<br>`mineru/full_cpu_local`<br>`paddleocr/full_cpu_local`<br>`liteparse/full_cpu_local` |
| `windows_full_cpu_local_all_host` | Host somente | 7 | `pymupdf/full_cpu_local`<br>`docling/full_cpu_local`<br>`mineru/full_cpu_local`<br>`paddleocr/full_cpu_local`<br>`liteparse/full_cpu_local`<br>`unstructured/full_cpu_local`<br>`xberg/full_cpu_local` |
| `windows_all_features_host` | Host somente | 7 | `pymupdf/full_cpu_local_visual`<br>`docling/full_cpu_local`<br>`mineru/full_cpu_local`<br>`paddleocr/full_cpu_local`<br>`liteparse/full_cpu_local`<br>`unstructured/full_cpu_local`<br>`xberg/full_cpu_layout` |
| `windows_source_preservation_v3` | Host somente | 13 | `pymupdf/native`<br>`pymupdf/ocr_auto_rapidtess`<br>`docling/native`<br>`docling/ocr_auto`<br>`mineru/txt`<br>`mineru/auto`<br>`paddleocr/mvp_structured`<br>`liteparse/native`<br>`liteparse/ocr_auto_tesseract`<br>`unstructured/fast_native`<br>`unstructured/auto_ocr`<br>`xberg/native_markdown`<br>`xberg/ocr_auto_tesseract` |
| `windows_max_quality_cpu_v3` | Host somente | 7 | `pymupdf/full_cpu_local`<br>`docling/full_cpu_local`<br>`mineru/full_cpu_local`<br>`paddleocr/full_cpu_local`<br>`liteparse/full_cpu_local`<br>`unstructured/full_cpu_local`<br>`xberg/full_cpu_local` |
| `windows_version_candidates_v3` | Host somente | 3 | `xberg/full_cpu_layout`<br>`paddleocr/ppstructure_v6_experimental`<br>`docling/ocr_auto_table_v2` |
| `windows_enriched_visual_cpu_v3` | Host somente | 7 | `pymupdf/full_cpu_local_visual`<br>`docling/full_cpu_local`<br>`mineru/full_cpu_local`<br>`paddleocr/full_cpu_local`<br>`liteparse/full_cpu_local`<br>`unstructured/full_cpu_local`<br>`xberg/full_cpu_local` |


## 10.2 Comandos host para todas as suítes

Os comandos abaixo usam as variáveis definidas na seção 1. Cada comando executa todos os PDFs, força nova execução, produz todos os artefatos, continua após falha e não roda resumos.

### `default`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite default `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `full_corpus`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite full_corpus `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `ocr_primary`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite ocr_primary `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `diagnostic_ocr`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite diagnostic_ocr `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `visual_ablation`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite visual_ablation `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `smoke`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite smoke `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `smoke_expanded`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite smoke_expanded `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `ocr_primary_expanded`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite ocr_primary_expanded `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `visual_ablation_expanded`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite visual_ablation_expanded `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `full_corpus_expanded`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite full_corpus_expanded `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `unstructured_smoke_host`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite unstructured_smoke_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `unstructured_ocr_host`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite unstructured_ocr_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `xberg_smoke_host`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite xberg_smoke_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `xberg_ocr_host`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite xberg_ocr_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `windows_smoke_all_host`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_smoke_all_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `windows_ocr_auto_all_host`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_ocr_auto_all_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `full_cpu_local`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite full_cpu_local `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `windows_full_cpu_local_all_host`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_full_cpu_local_all_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `windows_all_features_host`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `windows_source_preservation_v3`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_source_preservation_v3 `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `windows_max_quality_cpu_v3`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_max_quality_cpu_v3 `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `windows_version_candidates_v3`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_version_candidates_v3 `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```

### `windows_enriched_visual_cpu_v3`

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_enriched_visual_cpu_v3 `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```


## 10.3 Comandos WSL/Docker para as suítes compatíveis

### `default`

```bash
python3 scripts/run_batch.py \
  --suite default \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-default \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `full_corpus`

```bash
python3 scripts/run_batch.py \
  --suite full_corpus \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-full_corpus \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `ocr_primary`

```bash
python3 scripts/run_batch.py \
  --suite ocr_primary \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-ocr_primary \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `diagnostic_ocr`

```bash
python3 scripts/run_batch.py \
  --suite diagnostic_ocr \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-diagnostic_ocr \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `visual_ablation`

```bash
python3 scripts/run_batch.py \
  --suite visual_ablation \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-visual_ablation \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `smoke`

```bash
python3 scripts/run_batch.py \
  --suite smoke \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-smoke \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `smoke_expanded`

```bash
python3 scripts/run_batch.py \
  --suite smoke_expanded \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-smoke_expanded \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `ocr_primary_expanded`

```bash
python3 scripts/run_batch.py \
  --suite ocr_primary_expanded \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-ocr_primary_expanded \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `visual_ablation_expanded`

```bash
python3 scripts/run_batch.py \
  --suite visual_ablation_expanded \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-visual_ablation_expanded \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `full_corpus_expanded`

```bash
python3 scripts/run_batch.py \
  --suite full_corpus_expanded \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-full_corpus_expanded \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```

### `full_cpu_local`

```bash
python3 scripts/run_batch.py \
  --suite full_cpu_local \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-full_cpu_local \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output
```


# 11. Wrappers PowerShell oficiais


## 11.1 Benchmark A

Script: [`scripts/windows/run_benchmark_a.ps1`](../scripts/windows/run_benchmark_a.ps1)

Parâmetros:

| Parâmetro | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `-InputDir` | Sim | nenhum | Diretório com os PDFs. |
| `-OutputRoot` | Sim | nenhum | Root base. O Python acrescenta `host`. |
| `-Limit` | Não | 0 | 0 significa todos; valor positivo limita aos primeiros N PDFs. |
| `-DryRun` | Não | desativado | Imprime o plano e termina. |
| `-PreflightOnly` | Não | desativado | Executa somente o preflight. |

Valores fixos pelo wrapper:

- suíte `windows_full_cpu_local_all_host`;
- runtime `host`;
- artefatos `all`;
- continue on error;
- no summary;
- preflight obrigatório antes da execução normal.

Exemplo solicitado para o servidor:

```powershell
.\scripts\windows\run_benchmark_a.ps1 `
  -InputDir 'C:\victor.perone\projects\document-ai-benchmark\data\raw\batch' `
  -OutputRoot 'C:\victor.perone\projects\document-ai-benchmark\outputs\v3'
```

Saída efetiva:

```text
C:\victor.perone\projects\document-ai-benchmark\outputs\v3\host\
```

Dry run:

```powershell
.\scripts\windows\run_benchmark_a.ps1 `
  -InputDir $InputDir `
  -OutputRoot $OutputBase `
  -DryRun
```

Somente preflight:

```powershell
.\scripts\windows\run_benchmark_a.ps1 `
  -InputDir $InputDir `
  -OutputRoot $OutputBase `
  -PreflightOnly
```

Primeiro PDF:

```powershell
.\scripts\windows\run_benchmark_a.ps1 `
  -InputDir $InputDir `
  -OutputRoot $OutputBase `
  -Limit 1
```

> ❗ O wrapper Benchmark A não passa `--force`. Como `run_batch.py` usa resume por padrão, resultados válidos existentes podem ser reutilizados.


## 11.2 Todas as funcionalidades

Script: [`scripts/windows/run_all_features_host.ps1`](../scripts/windows/run_all_features_host.ps1)

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `-InputDir` | string | `data\\raw\\batch` | Diretório de PDFs. Alias: `-InputDirectory`. |
| `-OutputRoot` | string | `outputs` | Root base; `host` é acrescentado. |
| `-Resume` | switch | desativado | Usa resume. Sem ele, o wrapper passa `--force`. |
| `-DryRun` | switch | desativado | Mostra o plano e termina antes do preflight. |
| `-PreflightOnly` | switch | desativado | Faz o preflight obrigatório e não executa o lote. |
| `-VerboseOutput` | switch | desativado | Propaga `--verbose-output`. |
| `-JobTimeoutSeconds` | 1 a 86400 | 3600 | Timeout por job. |

Exemplo completo:

```powershell
.\scripts\windows\run_all_features_host.ps1 `
  -InputDir 'C:\victor.perone\projects\document-ai-benchmark\data\raw\batch' `
  -OutputRoot 'C:\victor.perone\projects\document-ai-benchmark\outputs\v3' `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput
```

Retomar:

```powershell
.\scripts\windows\run_all_features_host.ps1 `
  -InputDir $InputDir `
  -OutputRoot $OutputBase `
  -Resume `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput
```

Dry run:

```powershell
.\scripts\windows\run_all_features_host.ps1 `
  -InputDir $InputDir `
  -OutputRoot $OutputBase `
  -DryRun
```

Somente preflight:

```powershell
.\scripts\windows\run_all_features_host.ps1 `
  -InputDir $InputDir `
  -OutputRoot $OutputBase `
  -PreflightOnly
```


# 12. Execução de um único parser e perfil

O caminho canônico no Windows host é usar `run_batch.py`, porque ele prepara o inventário, escolhe o venv, resolve modelos, aplica variáveis offline, limpa a saída, valida artefatos e registra o lote.

Template:

```powershell
& $CorePython .\scripts\run_batch.py `
  --parser <parser> `
  --profile <perfil> `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```


## 12.1 pymupdf

Comandos para todos os perfis configurados:

```powershell
& $CorePython .\scripts\run_batch.py --parser pymupdf --profile native --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser pymupdf --profile ocr_auto_rapidtess --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser pymupdf --profile ocr_force_rapidtess --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser pymupdf --profile ocr_auto_rapidtess_150 --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser pymupdf --profile ocr_auto_rapidtess_200 --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser pymupdf --profile ocr_auto_rapidtess_300 --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser pymupdf --profile full_cpu_local --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser pymupdf --profile full_cpu_local_visual --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output
```


## 12.2 docling

Comandos para todos os perfis configurados:

```powershell
& $CorePython .\scripts\run_batch.py --parser docling --profile native --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser docling --profile ocr_auto --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser docling --profile ocr_auto_visual --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser docling --profile ocr_auto_formula --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser docling --profile ocr_auto_picture_classification --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser docling --profile full_cpu_local --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser docling --profile ocr_auto_table_v2 --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output
```


## 12.3 mineru

Comandos para todos os perfis configurados:

```powershell
& $CorePython .\scripts\run_batch.py --parser mineru --profile txt --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser mineru --profile auto --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser mineru --profile ocr --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser mineru --profile full_cpu_local --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output
```


## 12.4 paddleocr

Comandos para todos os perfis configurados:

```powershell
& $CorePython .\scripts\run_batch.py --parser paddleocr --profile lightweight --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser paddleocr --profile default --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser paddleocr --profile mvp_structured --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser paddleocr --profile full --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser paddleocr --profile ocr_structured_visual --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser paddleocr --profile full_cpu_local --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser paddleocr --profile ppstructure_v6_experimental --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output
```


## 12.5 liteparse

Comandos para todos os perfis configurados:

```powershell
& $CorePython .\scripts\run_batch.py --parser liteparse --profile native --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser liteparse --profile ocr_auto_tesseract --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser liteparse --profile ocr_auto_visual --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser liteparse --profile full_cpu_local --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output
```


## 12.6 unstructured

Comandos para todos os perfis configurados:

```powershell
& $CorePython .\scripts\run_batch.py --parser unstructured --profile fast_native --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser unstructured --profile auto_ocr --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser unstructured --profile hi_res_tables --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser unstructured --profile ocr_only_diagnostic --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser unstructured --profile full_cpu_local --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser unstructured --profile auto_general --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser unstructured --profile auto_quality --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output
```


## 12.7 xberg

Comandos para todos os perfis configurados:

```powershell
& $CorePython .\scripts\run_batch.py --parser xberg --profile native_markdown --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser xberg --profile ocr_auto_tesseract --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser xberg --profile ocr_force_tesseract --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser xberg --profile ocr_auto_tesseract_repair --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser xberg --profile full_cpu_local --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output

& $CorePython .\scripts\run_batch.py --parser xberg --profile full_cpu_layout --runtime host --input-dir $InputDir --output-root $OutputBase --artifacts all --force --no-summary --job-timeout-seconds 7200 --verbose-output
```


# 13. Execução direta de cada adaptador

> ❗ O caminho real dos adaptadores é `src\parsers\<parser>_v2.py`. O exemplo `src\docling_v2.py` não corresponde à árvore atual.

É preferível executar como módulo:

```powershell
& $DoclingPython -m src.parsers.docling_v2 --help
```

Isso garante que imports `src.*` sejam resolvidos quando o comando é executado a partir da raiz do repositório.


## 13.1 Inventário obrigatório antes de uma execução direta

Docling, MinerU, PaddleOCR, LiteParse, Unstructured e Xberg carregam o inventário já criado. O PyMuPDF consegue criá-lo, mas é seguro usar o mesmo procedimento para todos.

```powershell
New-Item -ItemType Directory -Force `
  -Path (Join-Path $DirectOutput '_source_inventory') |
  Out-Null

& $PyMuPDFPython -m scripts.build_source_inventory `
  --input-dir $InputDir `
  --output-dir (Join-Path $DirectOutput '_source_inventory') `
  --only 'arquivo.pdf'
```

Argumentos de `scripts/build_source_inventory.py`:

| Argumento | Padrão | Descrição |
|---|---|---|
| `--input-dir` | `/data/raw` | Diretório com PDFs. |
| `--output-dir` | `/outputs/_source_inventory` | Destino dos arquivos `<stem>.json`. |
| `--only` | nenhum | Nome exato de um PDF. Sem esse argumento, processa todos os PDFs do diretório. |


## 13.2 Variáveis offline para comandos diretos

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:SCARF_NO_ANALYTICS = '1'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
```


## 13.3 PyMuPDF

```powershell
$env:DOCUMENT_AI_VISUAL_WORKER_PYTHON = `
  (Join-Path $Repo '.venvs\visual-enrichment\Scripts\python.exe')

& $PyMuPDFPython -m src.parsers.pymupdf_v2 `
  --input $Pdf `
  --output-root $DirectOutput `
  --profile full_cpu_local_visual `
  --artifacts all `
  --verbose
```

| Argumento | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `--input PATH` | Sim | nenhum | PDF exato. |
| `--output-root PATH` | Não | `/outputs` | Root de saída exato; não acrescenta host. |
| `--profile NAME` | Não | `ocr_auto_rapidtess` | Perfil configurado. |
| `--artifacts ...` | Não | `document.md run.log` | Artefatos diretos. |
| `-v`, `--verbose` | Não | desativado | Exibe diagnósticos. |

Perfis aceitos:

- `native`
- `ocr_auto_rapidtess`
- `ocr_force_rapidtess`
- `ocr_auto_rapidtess_150`
- `ocr_auto_rapidtess_200`
- `ocr_auto_rapidtess_300`
- `full_cpu_local`
- `full_cpu_local_visual`


## 13.4 Docling

```powershell
& $DoclingPython -m src.parsers.docling_v2 `
  --input $Pdf `
  --output-root $DirectOutput `
  --profile full_cpu_local `
  --device cpu `
  --threads 2 `
  --model-artifacts-path $DoclingModelRoot `
  --artifacts all `
  --verbose
```

| Argumento | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `--input PATH` | Sim | nenhum | PDF exato. |
| `--output-root PATH` | Não | `/outputs` | Root de saída exato. |
| `--profile NAME` | Não | `ocr_auto` | Perfil Docling. |
| `--device {cpu,cuda,auto}` | Não | perfil | Override do dispositivo. |
| `--threads N` | Não | perfil | Override do número de threads. |
| `--model-artifacts-path PATH` | Não | perfil/default interno | Override da raiz de modelos. |
| `--artifacts ...` | Não | `document.md run.log` | Seleção de artefatos. |
| `-v`, `--verbose` | Não | desativado | Diagnóstico. |


## 13.5 MinerU

```powershell
$env:MINERU_MODEL_SOURCE = 'local'
$env:MINERU_TOOLS_CONFIG_JSON = Join-Path $MinerUModelRoot 'mineru.json'
$env:HF_HOME = Join-Path $MinerUModelRoot 'huggingface'

& $MinerUPython -m src.parsers.mineru_v2 `
  --input $Pdf `
  --output-root $DirectOutput `
  --profile full_cpu_local `
  --threads 2 `
  --artifacts all `
  --verbose
```

| Argumento | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `--input PATH` | Sim | nenhum | PDF exato. |
| `--output-root PATH` | Não | `/outputs` | Root de saída exato. |
| `--profile NAME` | Não | `auto` | Perfil MinerU. |
| `--threads N` | Não | default do MinerU | Override dos limites de threads. |
| `--artifacts ...` | Não | `document.md run.log` | Seleção de artefatos. |
| `-v`, `--verbose` | Não | desativado | Exibe a saída do CLI MinerU. |


## 13.6 PaddleOCR

```powershell
& $PaddlePython -m src.parsers.paddleocr_v2 `
  --input $Pdf `
  --output-root $DirectOutput `
  --profile full_cpu_local `
  --model-root $PaddleModelRoot `
  --artifacts all `
  --verbose
```

| Argumento | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `--input PATH` | Sim | nenhum | PDF exato. |
| `--output-root PATH` | Não | `/outputs` | Root de saída exato. |
| `--profile NAME` | Não | `mvp_structured` | Perfil PPStructureV3. |
| `--model-root PATH` | Não | `/home/appuser/.paddlex/official_models` | No Windows, informe o root host. |
| `--artifacts ...` | Não | `document.md run.log` | Seleção de artefatos. |
| `-v`, `--verbose` | Não | desativado | Diagnóstico. |


## 13.7 LiteParse

```powershell
& $LiteParsePython -m src.parsers.liteparse_v2 `
  --input $Pdf `
  --output-root $DirectOutput `
  --profile full_cpu_local `
  --model-artifacts-path $LiteParseModelRoot `
  --artifacts all `
  --verbose
```

| Argumento | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `--input PATH` | Sim | nenhum | PDF exato. |
| `--output-root PATH` | Não | `/outputs` | Root de saída exato. |
| `--profile NAME` | Não | `native` | Perfil LiteParse. |
| `--model-artifacts-path PATH` | Não | `/models/liteparse/smolvlm` | Raiz host do SmolVLM. |
| `--artifacts ...` | Não | `document.md run.log` | Seleção de artefatos. |
| `-v`, `--verbose` | Não | desativado | Diagnóstico. |


## 13.8 Unstructured

```powershell
$env:HF_HOME = Join-Path $UnstructuredModelRoot 'huggingface'
$env:HF_HUB_CACHE = Join-Path $env:HF_HOME 'hub'
$env:UNSTRUCTURED_DEFAULT_MODEL_NAME = 'yolox'
$env:UNSTRUCTURED_HI_RES_MODEL_NAME = 'yolox'
$env:DOCUMENT_AI_VISUAL_WORKER_PYTHON = `
  (Join-Path $Repo '.venvs\visual-enrichment\Scripts\python.exe')

& $UnstructuredPython -m src.parsers.unstructured_v2 `
  --input $Pdf `
  --output-root $DirectOutput `
  --profile full_cpu_local `
  --model-root $UnstructuredModelRoot `
  --artifacts all `
  --verbose
```

| Argumento | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `--input PATH` | Sim | nenhum | PDF exato. |
| `--output-root PATH` | Não | `/outputs` | Root de saída exato. |
| `--profile NAME` | Não | `fast_native` | Perfil Unstructured. |
| `--model-root PATH` | Não | `models/unstructured` | Raiz de modelos e manifesto. |
| `--artifacts ...` | Não | `document.md run.log` | Seleção de artefatos. |
| `-v`, `--verbose` | Não | desativado | Diagnóstico. |


## 13.9 Xberg

```powershell
$env:HF_HOME = Join-Path $XbergModelRoot 'huggingface'

& $XbergPython -m src.parsers.xberg_v2 `
  --input $Pdf `
  --output-root $DirectOutput `
  --profile full_cpu_layout `
  --model-root $XbergModelRoot `
  --artifacts all `
  --verbose
```

| Argumento | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `--input PATH` | Sim | nenhum | PDF exato. |
| `--output-root PATH` | Não | `/outputs` | Root de saída exato. |
| `--profile NAME` | Não | `native_markdown` | Perfil Xberg. |
| `--model-root PATH` | Não | `models/xberg` | Raiz do cache e manifesto. |
| `--artifacts ...` | Não | `document.md run.log` | Seleção de artefatos. |
| `-v`, `--verbose` | Não | desativado | Diagnóstico. |


## 13.10 Todos os perfis por execução direta

### pymupdf

```powershell
& $PyMuPDFPython -m src.parsers.pymupdf_v2 --input $Pdf --output-root $DirectOutput --profile native --artifacts all --verbose

& $PyMuPDFPython -m src.parsers.pymupdf_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_rapidtess --artifacts all --verbose

& $PyMuPDFPython -m src.parsers.pymupdf_v2 --input $Pdf --output-root $DirectOutput --profile ocr_force_rapidtess --artifacts all --verbose

& $PyMuPDFPython -m src.parsers.pymupdf_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_rapidtess_150 --artifacts all --verbose

& $PyMuPDFPython -m src.parsers.pymupdf_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_rapidtess_200 --artifacts all --verbose

& $PyMuPDFPython -m src.parsers.pymupdf_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_rapidtess_300 --artifacts all --verbose

& $PyMuPDFPython -m src.parsers.pymupdf_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_local --artifacts all --verbose

& $PyMuPDFPython -m src.parsers.pymupdf_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_local_visual --artifacts all --verbose
```

### docling

```powershell
& $DoclingPython -m src.parsers.docling_v2 --input $Pdf --output-root $DirectOutput --profile native --model-artifacts-path $DoclingModelRoot --artifacts all --verbose

& $DoclingPython -m src.parsers.docling_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto --model-artifacts-path $DoclingModelRoot --artifacts all --verbose

& $DoclingPython -m src.parsers.docling_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_visual --model-artifacts-path $DoclingModelRoot --artifacts all --verbose

& $DoclingPython -m src.parsers.docling_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_formula --model-artifacts-path $DoclingModelRoot --artifacts all --verbose

& $DoclingPython -m src.parsers.docling_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_picture_classification --model-artifacts-path $DoclingModelRoot --artifacts all --verbose

& $DoclingPython -m src.parsers.docling_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_local --model-artifacts-path $DoclingModelRoot --artifacts all --verbose

& $DoclingPython -m src.parsers.docling_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_table_v2 --model-artifacts-path $DoclingModelRoot --artifacts all --verbose
```

### mineru

```powershell
& $MinerUPython -m src.parsers.mineru_v2 --input $Pdf --output-root $DirectOutput --profile txt --artifacts all --verbose

& $MinerUPython -m src.parsers.mineru_v2 --input $Pdf --output-root $DirectOutput --profile auto --artifacts all --verbose

& $MinerUPython -m src.parsers.mineru_v2 --input $Pdf --output-root $DirectOutput --profile ocr --artifacts all --verbose

& $MinerUPython -m src.parsers.mineru_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_local --artifacts all --verbose
```

### paddleocr

```powershell
& $PaddlePython -m src.parsers.paddleocr_v2 --input $Pdf --output-root $DirectOutput --profile lightweight --model-root $PaddleModelRoot --artifacts all --verbose

& $PaddlePython -m src.parsers.paddleocr_v2 --input $Pdf --output-root $DirectOutput --profile default --model-root $PaddleModelRoot --artifacts all --verbose

& $PaddlePython -m src.parsers.paddleocr_v2 --input $Pdf --output-root $DirectOutput --profile mvp_structured --model-root $PaddleModelRoot --artifacts all --verbose

& $PaddlePython -m src.parsers.paddleocr_v2 --input $Pdf --output-root $DirectOutput --profile full --model-root $PaddleModelRoot --artifacts all --verbose

& $PaddlePython -m src.parsers.paddleocr_v2 --input $Pdf --output-root $DirectOutput --profile ocr_structured_visual --model-root $PaddleModelRoot --artifacts all --verbose

& $PaddlePython -m src.parsers.paddleocr_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_local --model-root $PaddleModelRoot --artifacts all --verbose

& $PaddlePython -m src.parsers.paddleocr_v2 --input $Pdf --output-root $DirectOutput --profile ppstructure_v6_experimental --model-root $PaddleModelRoot --artifacts all --verbose
```

### liteparse

```powershell
& $LiteParsePython -m src.parsers.liteparse_v2 --input $Pdf --output-root $DirectOutput --profile native --model-artifacts-path $LiteParseModelRoot --artifacts all --verbose

& $LiteParsePython -m src.parsers.liteparse_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_tesseract --model-artifacts-path $LiteParseModelRoot --artifacts all --verbose

& $LiteParsePython -m src.parsers.liteparse_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_visual --model-artifacts-path $LiteParseModelRoot --artifacts all --verbose

& $LiteParsePython -m src.parsers.liteparse_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_local --model-artifacts-path $LiteParseModelRoot --artifacts all --verbose
```

### unstructured

```powershell
& $UnstructuredPython -m src.parsers.unstructured_v2 --input $Pdf --output-root $DirectOutput --profile fast_native --model-root $UnstructuredModelRoot --artifacts all --verbose

& $UnstructuredPython -m src.parsers.unstructured_v2 --input $Pdf --output-root $DirectOutput --profile auto_ocr --model-root $UnstructuredModelRoot --artifacts all --verbose

& $UnstructuredPython -m src.parsers.unstructured_v2 --input $Pdf --output-root $DirectOutput --profile hi_res_tables --model-root $UnstructuredModelRoot --artifacts all --verbose

& $UnstructuredPython -m src.parsers.unstructured_v2 --input $Pdf --output-root $DirectOutput --profile ocr_only_diagnostic --model-root $UnstructuredModelRoot --artifacts all --verbose

& $UnstructuredPython -m src.parsers.unstructured_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_local --model-root $UnstructuredModelRoot --artifacts all --verbose

& $UnstructuredPython -m src.parsers.unstructured_v2 --input $Pdf --output-root $DirectOutput --profile auto_general --model-root $UnstructuredModelRoot --artifacts all --verbose

& $UnstructuredPython -m src.parsers.unstructured_v2 --input $Pdf --output-root $DirectOutput --profile auto_quality --model-root $UnstructuredModelRoot --artifacts all --verbose
```

### xberg

```powershell
& $XbergPython -m src.parsers.xberg_v2 --input $Pdf --output-root $DirectOutput --profile native_markdown --model-root $XbergModelRoot --artifacts all --verbose

& $XbergPython -m src.parsers.xberg_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_tesseract --model-root $XbergModelRoot --artifacts all --verbose

& $XbergPython -m src.parsers.xberg_v2 --input $Pdf --output-root $DirectOutput --profile ocr_force_tesseract --model-root $XbergModelRoot --artifacts all --verbose

& $XbergPython -m src.parsers.xberg_v2 --input $Pdf --output-root $DirectOutput --profile ocr_auto_tesseract_repair --model-root $XbergModelRoot --artifacts all --verbose

& $XbergPython -m src.parsers.xberg_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_local --model-root $XbergModelRoot --artifacts all --verbose

& $XbergPython -m src.parsers.xberg_v2 --input $Pdf --output-root $DirectOutput --profile full_cpu_layout --model-root $XbergModelRoot --artifacts all --verbose
```


# 14. Perfis disponíveis e opções internas

Os nomes de perfil são argumentos de execução. Os campos internos abaixo não são argumentos CLI independentes, salvo quando o adapter oferece um override explícito. Para mudar um campo interno de forma persistente, edite `config/benchmark_profiles.json` e use um novo nome de perfil.


## 14.1 pymupdf: perfis

| Perfil | Comportamento |
|---|---|
| `native` | Layout ativo, texto nativo, OCR desativado, cabeçalhos e rodapés preservados para a normalização comum. |
| `ocr_auto_rapidtess` | Layout ativo e OCR automático RapidTess/Tesseract em português (`por`) a 150 DPI. |
| `ocr_force_rapidtess` | OCR RapidTess forçado em todas as páginas a 150 DPI. Perfil diagnóstico. |
| `ocr_auto_rapidtess_150` | OCR automático a 150 DPI. Equivale ao ajuste de DPI do perfil primário. |
| `ocr_auto_rapidtess_200` | OCR automático a 200 DPI. Marcado como diagnóstico. |
| `ocr_auto_rapidtess_300` | OCR automático a 300 DPI. Marcado como diagnóstico. |
| `full_cpu_local` | Perfil completo em CPU sem enriquecimento visual. OCR automático, layout e separadores de página. |
| `full_cpu_local_visual` | Perfil completo com worker visual local: PaddleOCR `pt` e SmolVLM; falha visual é fatal; imagens não são persistidas. |


## 14.2 docling: perfis

| Perfil | Comportamento |
|---|---|
| `native` | OCR desativado; layout, hierarquia de títulos e TableFormer no modo `accurate` permanecem ativos. |
| `ocr_auto` | RapidOCR com backend `torch`, idioma `pt`, escala 3.0 e modo sensível ao PDF e às regiões de layout. |
| `ocr_auto_visual` | Equivale a `ocr_auto`, acrescentando descrição de figuras com SmolVLM e imagens internas em escala 2.0. |
| `ocr_auto_formula` | Equivale a `ocr_auto`, acrescentando enriquecimento de fórmulas. |
| `ocr_auto_picture_classification` | Equivale a `ocr_auto`, acrescentando classificação de figuras. |
| `full_cpu_local` | Ativa OCR, tabelas, descrição e classificação de figuras, gráficos, fórmulas, código e hierarquia em CPU. |
| `ocr_auto_table_v2` | Candidato que solicita TableFormer V2. Deve ser tratado como perfil de validação de versão, não como padrão estável. |


## 14.3 mineru: perfis

| Perfil | Comportamento |
|---|---|
| `txt` | Método `txt`; usa a camada textual e não solicita OCR. |
| `auto` | Método `auto`; o MinerU decide entre texto e OCR. |
| `ocr` | Método `ocr`; força a rota de OCR do MinerU. |
| `full_cpu_local` | Método `auto`, backend `pipeline`, fórmula, tabela e table merge ativos; persiste bundle nativo, content list e middle JSON. |


## 14.4 paddleocr: perfis

| Perfil | Comportamento |
|---|---|
| `lightweight` | OCR, layout, região e tabelas; fórmulas, gráficos, orientação, unwarping e selos desativados. |
| `default` | Acrescenta reconhecimento de fórmulas ao perfil leve. |
| `mvp_structured` | Acrescenta classificação de orientação do documento e das linhas. |
| `full` | Ativa gráfico e unwarping, mas mantém selo desativado; engine configurado como `paddle`. |
| `ocr_structured_visual` | OCR estruturado com fórmulas e gráficos, sem classificação de orientação e sem unwarping. |
| `full_cpu_local` | Todas as capacidades locais configuradas: tabelas, fórmulas, gráficos, orientações, unwarping, regiões, selos e formatação de blocos. |
| `ppstructure_v6_experimental` | Candidato experimental equivalente ao perfil completo, com campos de override para modelos de detecção e reconhecimento. |


## 14.5 liteparse: perfis

| Perfil | Comportamento |
|---|---|
| `native` | Markdown nativo, extração de imagens transitórias, sem OCR e sem descrição visual. |
| `ocr_auto_tesseract` | OCR seletivo Tesseract `por+eng`, 300 DPI, OSD, OCR de imagens e falha de OCR fatal. |
| `ocr_auto_visual` | Acrescenta SmolVLM; descrição visual funciona como fallback quando o OCR da imagem já produz texto útil. |
| `full_cpu_local` | Ativa links, texto pequeno, anotações, campos, árvore estrutural, metadados, vetores, OCR de imagem e descrição visual. |


## 14.6 unstructured: perfis

| Perfil | Comportamento |
|---|---|
| `fast_native` | Estratégia `fast`, sem OCR e sem inferência de estrutura de tabelas. |
| `auto_ocr` | Estratégia `auto`, OCR Tesseract `por` e `eng`, sem inferência de tabela. |
| `hi_res_tables` | Estratégia `hi_res`, YOLOX, OCR e inferência de estrutura de tabelas. |
| `ocr_only_diagnostic` | Estratégia `ocr_only`; OCR de página inteira. Perfil diagnóstico. |
| `full_cpu_local` | Hi res, YOLOX, OCR, tabela, extração transitória de Image/Table e enriquecimento visual com modelos compartilhados. |
| `auto_general` | Estratégia `auto`, OCR e sem inferência de tabela. |
| `auto_quality` | Estratégia `auto` com inferência de tabela; a biblioteca pode resolver a rota efetiva para hi res. |


## 14.7 xberg: perfis

| Perfil | Comportamento |
|---|---|
| `native_markdown` | Markdown, tabelas e metadados; OCR, layout, imagens e QR desativados. |
| `ocr_auto_tesseract` | OCR automático Tesseract `por` e `eng`, rotação automática, 300 DPI e detecção de tabela. |
| `ocr_force_tesseract` | Mesma base do OCR automático, mas `force_ocr=true`. |
| `ocr_auto_tesseract_repair` | OCR automático com deskew, denoise e melhoria de contraste. |
| `full_cpu_local` | Qualidade, estrutura, imagens, OCR em imagens, anotações, campos, ordem de leitura e conteúdo completo; sem layout avançado e sem QR. |
| `full_cpu_layout` | Equivale ao completo e acrescenta layout avançado e QR codes. É o perfil usado na suíte de todas as funcionalidades. |


## 14.8 Chaves internas do perfil PyMuPDF

| Chave | Descrição |
|---|---|
| `layout_module` | Ativa PyMuPDF Layout. |
| `ocr_enabled` | Liga ou desliga OCR. |
| `ocr_mode` | `disabled`, `auto` ou `forced`. |
| `ocr_engine` | Engine; os perfis atuais usam `rapidtess`. |
| `ocr_language` | Código Tesseract, atualmente `por`. |
| `ocr_dpi` | DPI do OCR. |
| `parser_header` | Solicita cabeçalhos. |
| `parser_footer` | Solicita rodapés. |
| `force_text` | Preserva texto em regiões visuais. |
| `write_images` | Grava imagens do Markdown. |
| `embed_images` | Embute imagens. |
| `page_separators` | Insere separadores de página. |
| `diagnostic_only` | Marca perfil diagnóstico. |
| `visual_enrichment_enabled` | Liga o worker visual. |
| `visual_render_dpi` | DPI dos crops visuais. |
| `visual_ocr_language` | Código PaddleOCR; perfil atual usa `pt`. |
| `visual_description_model` | Diretório local do SmolVLM. |
| `visual_det_model_dir` | Modelo local de detecção visual OCR. |
| `visual_rec_model_dir` | Modelo local de reconhecimento visual OCR. |
| `visual_failure_fatal` | Falha o job quando o worker falha. |
| `visual_persist_images` | Política de persistência visual. |


## 14.9 Chaves internas do perfil Docling

| Chave | Descrição |
|---|---|
| `ocr_enabled` | Ativa OCR. |
| `ocr_mode` | Modo OCR Docling. |
| `ocr_engine` | Os perfis atuais usam RapidOCR. |
| `ocr_backend` | Backend RapidOCR, atualmente `torch`. |
| `ocr_language` | Idioma, atualmente `pt`. |
| `ocr_scale` | Escala de rasterização; 3.0 equivale a 216 DPI. |
| `table_structure` | Reconstrução de tabelas. |
| `table_mode` | `accurate` ou `fast`. |
| `table_cell_matching` | Associação de células. |
| `picture_description` | Descrição de figuras. |
| `picture_description_preset` | Preset visual, atualmente `smolvlm`. |
| `picture_description_prompt` | Prompt local. |
| `picture_area_threshold` | Área mínima da figura. |
| `picture_classification` | Classificação de figuras. |
| `chart_extraction` | Extração de gráficos. |
| `formula_enrichment` | Enriquecimento de fórmulas. |
| `code_enrichment` | Enriquecimento de código. |
| `generate_picture_images` | Gera imagens internas para enriquecimento. |
| `images_scale` | Escala das imagens. |
| `remote_services_enabled` | Deve permanecer falso na campanha local. |
| `accelerator_device` | `cpu`, `cuda` ou `auto`. |
| `threads` | Threads solicitadas. |
| `model_artifacts_path` | Root de modelos; normalmente injetado pelo host. |
| `heading_hierarchy` | Hierarquia de títulos. |
| `heading_use_bookmarks` | Usa bookmarks. |
| `heading_use_numbering` | Usa numeração. |
| `heading_use_style` | Usa estilos. |
| `heading_use_font_style` | Usa estilo de fonte. |
| `heading_style_size_tolerance` | Tolerância de tamanho. |
| `heading_max_level` | Nível máximo. |
| `heading_bookmark_match_threshold` | Threshold de matching. |
| `table_engine` | `tableformer_v1` ou `tableformer_v2`. |


## 14.10 Chaves internas do perfil MinerU

| Chave | Descrição |
|---|---|
| `method` | `txt`, `auto` ou `ocr`. |
| `ocr_enabled` | Registra a intenção de OCR. |
| `formula` | Ativa fórmulas. |
| `table` | Ativa tabelas. |
| `table_merge` | Ativa merge de tabelas. |
| `backend` | Backend; perfil completo usa `pipeline`. |
| `persist_native_assets` | Persiste assets nativos. |
| `persist_content_list` | Persiste content list. |
| `persist_middle_json` | Persiste middle JSON. |


## 14.11 Chaves internas do perfil PaddleOCR

| Chave | Descrição |
|---|---|
| `ocr_enabled` | Obrigatoriamente true no adapter PPStructureV3. |
| `table_recognition` | Reconhecimento de tabelas. |
| `formula_recognition` | Reconhecimento de fórmulas. |
| `chart_recognition` | Chart to table. |
| `document_orientation_classification` | Orientação do documento. |
| `textline_orientation` | Orientação das linhas. |
| `document_unwarping` | Correção geométrica. |
| `region_detection` | Detecção de regiões. |
| `seal_recognition` | Selos. |
| `format_block_content` | Formata conteúdo dos blocos. |
| `markdown_ignore_labels` | Labels omitidos do Markdown. |
| `device` | Dispositivo, normalmente CPU. |
| `inference_engine` | `paddle_static` ou `paddle` conforme perfil. |
| `enable_mkldnn` | MKL DNN. |
| `mkldnn_cache_capacity` | Cache MKL DNN. |
| `cpu_threads` | Threads do runtime. |
| `layout_threshold` | Threshold do layout. |
| `text_det_thresh` | Threshold de detecção de texto. |
| `text_rec_score_thresh` | Threshold de reconhecimento. |
| `use_wired_table_cells_trans_to_html` | Transformação das células com linhas. |
| `use_e2e_wired_table_rec_model` | Modelo fim a fim de tabela com linhas. |
| `use_e2e_wireless_table_rec_model` | Modelo fim a fim sem linhas. |
| `experimental` | Marca o perfil experimental. |
| `text_detection_model_dir_override` | Override do modelo de detecção. |
| `text_recognition_model_dir_override` | Override do modelo de reconhecimento. |


## 14.12 Chaves internas do perfil LiteParse

| Chave | Descrição |
|---|---|
| `ocr_enabled` | OCR. |
| `output_format` | Atualmente `markdown`. |
| `extract_images` | Extrai imagens transitórias. |
| `image_mode` | Atualmente `off` para não incorporar binários. |
| `extract_links` | Links. |
| `keep_headers_footers` | Cabeçalhos e rodapés. |
| `preserve_very_small_text` | Texto muito pequeno. |
| `extract_annotations` | Anotações. |
| `extract_form_fields` | Campos de formulário. |
| `extract_structure_tree` | Árvore estrutural. |
| `extract_document_metadata` | Metadados do documento. |
| `extract_vector_graphics` | Gráficos vetoriais. |
| `extract_text_metadata` | Metadados textuais. |
| `extract_screenshots` | Screenshots. |
| `remote_services_enabled` | Serviços remotos; deve ser falso. |
| `accelerator_device` | CPU nos perfis atuais. |
| `num_workers` | Workers. |
| `ocr_strategy` | Estratégia seletiva. |
| `ocr_engine` | Tesseract. |
| `ocr_language` | Atualmente `por+eng`. |
| `ocr_server_url` | Servidor OCR; deve permanecer null. |
| `tessdata_required` | Idiomas exigidos. |
| `dpi` | DPI. |
| `orientation_detection` | OSD. |
| `image_ocr` | OCR de imagens. |
| `image_description` | SmolVLM. |
| `image_description_model` | ID do modelo. |
| `image_description_fallback_only` | Descreve somente sem OCR útil. |
| `image_description_prompt` | Prompt local. |
| `ocr_failure_fatal` | Política de falha. |


## 14.13 Chaves internas do perfil Unstructured

| Chave | Descrição |
|---|---|
| `strategy` | `fast`, '`auto`', `hi_res` ou `ocr_only`. |
| `ocr_enabled` | OCR. |
| `ocr_mode` | Descrição do modo. |
| `ocr_engine` | Tesseract nos perfis atuais. |
| `languages` | Idiomas. |
| `detect_language_per_element` | Detecção por elemento. |
| `infer_table_structure` | Estrutura de tabelas. |
| `include_page_breaks` | PageBreak. |
| `hi_res_model_name` | YOLOX. |
| `extract_image_block_types` | Tipos de crops. |
| `extract_image_block_to_payload` | Base64 no payload; falso nos perfis atuais. |
| `extract_forms` | Desativado porque a versão fixada não implementa. |
| `form_extraction_skip_tables` | Comportamento de forms. |
| `password` | Senha do PDF. |
| `pdfminer_line_margin` | Margem de linha. |
| `pdfminer_char_margin` | Margem de caractere. |
| `pdfminer_line_overlap` | Sobreposição. |
| `pdfminer_word_margin` | Margem de palavra. |
| `remote_services_enabled` | Deve ser falso. |
| `network_allowed_during_run` | Deve ser falso. |
| `ocr_agent` | Agente OCR. |
| `table_ocr_agent` | Agente para tabelas. |
| `visual_enrichment_enabled` | Worker visual local. |
| `visual_ocr_language` | Idioma PaddleOCR. |
| `visual_description_model` | SmolVLM local. |
| `visual_det_model_dir` | Detector visual. |
| `visual_rec_model_dir` | Reconhecedor visual. |
| `visual_failure_fatal` | Política de falha visual. |


## 14.14 Chaves internas do perfil Xberg

| Chave | Descrição |
|---|---|
| `output_format` | Formato de saída. |
| `result_format` | Formato do envelope. |
| `escape_markdown` | Escape Markdown. |
| `table_anchors` | Âncoras de tabela. |
| `include_document_structure` | Estrutura do documento. |
| `use_cache` | Cache. |
| `enable_quality_processing` | Pós processamento de qualidade. |
| `ocr_enabled` | OCR. |
| `ocr_backend` | Tesseract. |
| `ocr_languages` | Idiomas. |
| `ocr_strategy` | `disabled`, `auto` ou estratégia suportada. |
| `force_ocr` | OCR forçado. |
| `auto_rotate` | Rotação. |
| `tesseract_psm` | PSM. |
| `tesseract_oem` | OEM. |
| `min_confidence` | Confiança mínima. |
| `enable_table_detection` | Detecção de tabela no OCR. |
| `tesseract_use_cache` | Cache Tesseract. |
| `target_dpi` | DPI. |
| `deskew` | Deskew. |
| `denoise` | Denoise. |
| `contrast_enhance` | Contraste. |
| `extract_pages` | Páginas. |
| `insert_page_markers` | Marcadores. |
| `extract_tables` | Tabelas. |
| `extract_images` | Imagens. |
| `extract_metadata` | Metadados. |
| `extract_annotations` | Anotações. |
| `extract_form_fields` | Campos. |
| `reading_order` | Ordem de leitura. |
| `ocr_inline_images` | OCR de imagens inline. |
| `run_ocr_on_images` | OCR nas imagens extraídas. |
| `append_ocr_text` | Acrescenta OCR ao Markdown. |
| `include_data_base64` | Base64; falso nos perfis atuais. |
| `include_headers` | Cabeçalhos. |
| `include_footers` | Rodapés. |
| `strip_repeating_text` | Remove repetição no parser. |
| `include_watermarks` | Marcas d'água. |
| `layout_enabled` | Layout avançado. |
| `layout_strategy` | Estratégia de layout. |
| `layout_apply_heuristics` | Heurísticas. |
| `layout_acceleration_provider` | Provider, atualmente CPU. |
| `layout_confidence_threshold` | Threshold. |
| `layout_enable_chart_understanding` | Entendimento de gráfico. |
| `allow_single_column_tables` | Tabelas de uma coluna. |
| `qr_codes` | QR codes. |
| `chunking_enabled` | Chunking; desativado nos perfis primários. |
| `token_reduction_mode` | Redução; `off`. |
| `remote_services_enabled` | Deve ser falso. |
| `network_allowed_during_run` | Deve ser falso. |


# 15. Artefatos e estrutura de saída


## 15.1 Seletores válidos

| Artefato | Finalidade |
|---|---|
| `raw.md` | Markdown nativo ou representação mais próxima da saída oficial. |
| `document.md` | Markdown normalizado comum. |
| `document.enriched.md` | Markdown operacional com conteúdo derivado quando disponível; fallback materializado pelo core. |
| `document.jsonl` | Um registro por página quando o mapeamento é completo. |
| `metrics.json` | Configuração resolvida, versões, tempos, recursos, conteúdo e paths. |
| `removed_content.jsonl` | Auditoria do conteúdo removido pela normalização. |
| `run.log` | Saída capturada do parser. |
| `native` | Bundle nativo e manifesto. |


## 15.2 Sintaxes aceitas

```text
--artifacts all
--artifacts raw.md document.md metrics.json
--artifacts raw.md,document.md,metrics.json
```

No adaptador direto, o padrão é:

```text
document.md run.log
```

No `run_batch.py`, o padrão é:

```text
all
```


## 15.3 Estrutura de saída

```text
<output-root>\
└── host\
    ├── _source_inventory\
    │   └── <documento>.json
    └── <parser>\
        └── <documento>\
            └── <perfil>\
                ├── raw.md
                ├── document.md
                ├── document.enriched.md
                ├── document.jsonl
                ├── metrics.json
                ├── removed_content.jsonl
                ├── run.log
                └── native\
                    ├── manifest.json
                    └── assets\
```

Exemplo:

```text
C:\victor.perone\projects\document-ai-benchmark\outputs\v3\host\
└── docling\
    └── relatorio_2026\
        └── full_cpu_local\
            ├── raw.md
            ├── document.md
            ├── document.enriched.md
            ├── document.jsonl
            ├── metrics.json
            ├── removed_content.jsonl
            ├── run.log
            └── native\
```


# 16. Preflight, dry run, resume, force e resume check


## 16.1 Dry run

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --dry-run
```

Não cria inventário, não inicia inferência e não altera jobs.


## 16.2 Preflight

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --preflight
```

Valida ambiente e perfil, mas não processa o PDF.


## 16.3 Resume

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --resume `
  --no-summary
```

Resume é o padrão do `run_batch.py`. Um job só é reutilizado quando métricas, SHA do PDF, parser, perfil, seleção e artefatos passam na validação.


## 16.4 Force

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --no-summary
```

O diretório leaf do job é removido antes da execução para impedir reaproveitamento de assets antigos.


## 16.5 Resume check

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --resume-check
```

Códigos:

- 0: todos os jobs são reutilizáveis;
- 1: ao menos um job está pendente ou inválido.

É read only e não inicia parser nem container.


## 16.6 Continuar após falha

```powershell
& $CorePython .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --continue-on-error `
  --no-summary
```

Sem essa flag, o lote aborta no primeiro job com falha e marca os restantes como `aborted`.


# 17. Diagnósticos e utilitários


## 17.1 Mostrar um plano de suíte

Script: [`scripts/show_benchmark_plan.py`](../scripts/show_benchmark_plan.py)

```powershell
& $CorePython .\scripts\show_benchmark_plan.py --suite ocr_primary
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--suite` | `ocr_primary` | Nome de uma suíte de `benchmark_profiles.json`. |

Esse script usa o input configurado e exige que o diretório contenha PDFs.


## 17.2 Preflight de um parser

Script: [`scripts/parser_preflight.py`](../scripts/parser_preflight.py)

```powershell
& $DoclingPython -m scripts.parser_preflight `
  --parser docling `
  --profile full_cpu_local `
  --runtime host `
  --project-root $Repo `
  --model-artifacts-path $DoclingModelRoot
```

| Argumento | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `--parser` | Sim | nenhum | Parser. |
| `--profile` | Sim | nenhum | Perfil. |
| `--runtime {docker,host}` | Não | `docker` | Contexto de paths e checks. |
| `--project-root PATH` | Não | raiz inferida | Raiz do repositório; necessária em invocações host fora do root. |
| `--model-artifacts-path PATH` | Não | root resolvido | Override genérico convertido no argumento específico do adapter. |

Saída de protocolo:

```text
PREFLIGHT_JSON={"schema_version":1,...}
```


## 17.3 Gerar fixtures OCR

Script: [`scripts/generate_ocr_regression_fixtures.py`](../scripts/generate_ocr_regression_fixtures.py)

```powershell
& $PyMuPDFPython .\scripts\generate_ocr_regression_fixtures.py `
  --output-dir (Join-Path $Repo 'outputs\_fixtures\ocr_regression') `
  --source-dpi 300
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--output-dir` | `/outputs/_fixtures/ocr_regression` | Destino. |
| `--source-dpi` | 300 | DPI usado para rasterizar as páginas sintéticas. |


## 17.4 Avaliar DPI do PyMuPDF

Script: [`scripts/evaluate_pymupdf_dpi.py`](../scripts/evaluate_pymupdf_dpi.py)

```powershell
& $CorePython .\scripts\evaluate_pymupdf_dpi.py `
  --ground-truth (Join-Path $Repo 'outputs\_fixtures\ocr_regression\ground_truth.json') `
  --results-root (Join-Path $Repo 'outputs\_runtime_feature_test\dpi_ablation\pymupdf\scan_quality_3') `
  --fixture scan_quality_3.pdf `
  --profiles ocr_auto_rapidtess_150 ocr_auto_rapidtess_200 ocr_auto_rapidtess_300 `
  --output (Join-Path $Repo 'metrics\pymupdf_dpi.json')
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--ground-truth` | fixture padrão | JSON de referência. |
| `--results-root` | resultado padrão de ablação | Raiz dos perfis executados. |
| `--fixture` | `scan_quality_3.pdf` | Nome do PDF. |
| `--profiles` | 150, 200 e 300 | Um ou mais perfis. |
| `--output` | nenhum | JSON opcional. |


## 17.5 Avaliar orientação PyMuPDF

Script: [`scripts/evaluate_pymupdf_orientation.py`](../scripts/evaluate_pymupdf_orientation.py)

```powershell
& $CorePython .\scripts\evaluate_pymupdf_orientation.py
```

Esse script não aceita argumentos. Os paths, perfil e fixtures são constantes no código.


## 17.6 Probe de regiões de imagem e OSD

Script: [`scripts/probe_image_region_orientation.py`](../scripts/probe_image_region_orientation.py)

```powershell
& $PyMuPDFPython .\scripts\probe_image_region_orientation.py `
  --input $Pdf `
  --dpi 150
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--input` | obrigatório | PDF. |
| `--dpi` | 150 | DPI de renderização das regiões antes do OSD. |


## 17.7 Probe da estrutura PyMuPDF

Script: [`scripts/probe_pymupdf_structure.py`](../scripts/probe_pymupdf_structure.py)

```powershell
& $PyMuPDFPython .\scripts\probe_pymupdf_structure.py --input $Pdf
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--input` | obrigatório | PDF a inspecionar. |


## 17.8 Probe Tesseract OSD

Script: [`scripts/probe_tesseract_osd.py`](../scripts/probe_tesseract_osd.py)

```powershell
& $PyMuPDFPython .\scripts\probe_tesseract_osd.py `
  --fixtures-dir (Join-Path $Repo 'outputs\_fixtures\ocr_regression') `
  --dpi 150 `
  --files `
    scan_landscape_upright.pdf `
    scan_metadata_rotation_90.pdf `
    scan_pixels_90.pdf `
    scan_pixels_180.pdf `
    scan_pixels_270.pdf
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--fixtures-dir` | `/outputs/_fixtures/ocr_regression` | Diretório das fixtures. |
| `--dpi` | 150 | DPI de renderização. |
| `--files` | cinco fixtures de orientação | Um ou mais nomes. |


## 17.9 Probe Docling

Script: [`scripts/probe_docling_api.py`](../scripts/probe_docling_api.py)

```powershell
& $DoclingPython .\scripts\probe_docling_api.py
```

Não aceita argumentos. Mostra versões, executáveis, variáveis, símbolos e assinaturas.


## 17.10 Probe LiteParse

Script: [`scripts/probe_liteparse_api.py`](../scripts/probe_liteparse_api.py)

```powershell
& $LiteParsePython .\scripts\probe_liteparse_api.py
& $LiteParsePython .\scripts\probe_liteparse_api.py $Pdf
```

O PDF é posicional e opcional. Sem PDF, o script testa a API; com PDF, também executa parse e `is_complex()`.


## 17.11 Probe Unstructured

Script: [`scripts/probe_unstructured_api.py`](../scripts/probe_unstructured_api.py)

```powershell
& $UnstructuredPython .\scripts\probe_unstructured_api.py
```

Não aceita argumentos.


## 17.12 Probe Xberg

Script: [`scripts/probe_xberg_api.py`](../scripts/probe_xberg_api.py)

```powershell
& $XbergPython .\scripts\probe_xberg_api.py
```

Não aceita argumentos.


## 17.13 Validador de modelos Docling

Script: [`scripts/validate_docling_models.py`](../scripts/validate_docling_models.py)

```powershell
& $DoclingPython .\scripts\validate_docling_models.py `
  --model-root $DoclingModelRoot `
  --validate-only

& $DoclingPython .\scripts\validate_docling_models.py `
  --model-root $DoclingModelRoot `
  --check-manifest
```

| Argumento | Descrição |
|---|---|
| `--model-root PATH` | Raiz dos modelos. |
| `--validate-only` | Executa validadores e não gera novo manifesto. |
| `--force` | Regenera manifesto depois de todos os níveis passarem. |
| `--skip-component-load` | Pula o nível B. Não pode ser usado para certificar manifesto. |
| `--skip-pipeline-init` | Pula o nível C. Não pode ser usado para certificar manifesto. |
| `--check-manifest` | Valida somente o manifesto existente. |


## 17.14 Validar regressão de cabeçalho e rodapé

Script: [`scripts/validate_header_footer_regression.py`](../scripts/validate_header_footer_regression.py)

```powershell
& $CorePython .\scripts\validate_header_footer_regression.py `
  --ground-truth (Join-Path $Repo 'outputs\_fixtures\ocr_regression\ground_truth.json') `
  --fixture scan_quality_3.pdf `
  --output-dir (Join-Path $Repo 'outputs\host\pymupdf\scan_quality_3\ocr_auto_rapidtess_150')
```

| Argumento | Obrigatório | Descrição |
|---|---|---|
| `--ground-truth` | Sim | JSON de referência. |
| `--fixture` | Sim | Nome da fixture. |
| `--output-dir` | Sim | Diretório parser/perfil com `document.jsonl` e `removed_content.jsonl`. |


## 17.15 Resumos por parser

```powershell
& $CorePython .\scripts\build_pymupdf_summary.py `
  --profile ocr_auto_rapidtess `
  --output-root (Join-Path $OutputBase 'host') `
  --metrics-root (Join-Path $Repo 'metrics')

& $CorePython .\scripts\build_docling_summary.py `
  --profile full_cpu_local `
  --output-root (Join-Path $OutputBase 'host') `
  --metrics-root (Join-Path $Repo 'metrics')

& $CorePython .\scripts\build_mineru_summary.py `
  --profile full_cpu_local `
  --output-root (Join-Path $OutputBase 'host') `
  --metrics-root (Join-Path $Repo 'metrics')
```

| Script | Argumentos |
|---|---|
| `build_pymupdf_summary.py` | `--profile` obrigatório; `--output-root`; `--metrics-root`. |
| `build_docling_summary.py` | `--profile` obrigatório; `--output-root`; `--metrics-root`. |
| `build_mineru_summary.py` | `--profile` obrigatório; `--output-root`; `--metrics-root`. |


## 17.16 Comparações opcionais

Esses scripts são pós processamento histórico e não são necessários para executar os parsers.

```powershell
& $CorePython .\scripts\build_parser_comparison.py `
  --output-root (Join-Path $OutputBase 'host') `
  --metrics-root (Join-Path $Repo 'metrics')

& $CorePython .\scripts\build_native_parser_comparison.py `
  --output-root (Join-Path $OutputBase 'host') `
  --metrics-root (Join-Path $Repo 'metrics')
```

O primeiro usa perfis fixos `pymupdf/native` e `docling/native`. O segundo acrescenta `mineru/txt`.


# 18. Scripts baseline legados

Os baselines são úteis para diagnósticos históricos, mas não substituem os adaptadores v2 nem o `run_batch.py`.


## 18.1 PyMuPDF baseline

```powershell
& $PyMuPDFPython .\src\parsers\pymupdf_baseline.py `
  --input $Pdf `
  --output-dir (Join-Path $Repo 'outputs\baseline\pymupdf')
```

| Argumento | Descrição |
|---|---|
| `--input` | PDF obrigatório. |
| `--output-dir` | Diretório obrigatório. |


## 18.2 Docling baseline

```powershell
& $DoclingPython .\src\parsers\docling_baseline.py `
  --input $Pdf `
  --output-dir (Join-Path $Repo 'outputs\baseline\docling') `
  --device cpu `
  --threads 2
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--input` | obrigatório | PDF. |
| `--output-dir` | obrigatório | Destino. |
| `--device {cpu,cuda,auto}` | `cpu` | Dispositivo. |
| `--threads N` | CPU count | Threads. |


## 18.3 MinerU baseline

```powershell
& $MinerUPython .\src\parsers\mineru_baseline.py `
  --input $Pdf `
  --output-dir (Join-Path $Repo 'outputs\baseline\mineru') `
  --method auto `
  --threads 2
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--input` | obrigatório | PDF. |
| `--output-dir` | obrigatório | Destino. |
| `--method {txt,auto,ocr}` | `txt` | Método. |
| `--threads N` | CPU física/lógica | Threads. |


# 19. Logs, códigos de saída e validação


## 19.1 Logs do lote

```text
logs\batch_<timestamp>.log
logs\batch_<timestamp>_results.jsonl
logs\batch_<timestamp>_manifest.json
```

O manifest do lote registra, entre outros:

- runtime;
- sistema operacional;
- Python do orquestrador;
- commit Git;
- working tree dirty ou clean;
- SHA da configuração;
- suíte e pares;
- PDFs e SHA-256;
- total de jobs.


## 19.2 Status de job

| Status | Significado |
|---|---|
| `pending` | Ainda não executado. |
| `skip` | Resume validou o job existente. |
| `done` | Parser e pós validação passaram. |
| `fail` | Processo ou pós validação falhou. |
| `aborted` | Não executado porque o lote parou no primeiro erro. |


## 19.3 Códigos de saída úteis

| Comando | 0 | Não zero |
|---|---|---|
| `run_batch.py --preflight` | Todos os checks obrigatórios passaram. | Falha de infraestrutura, parser, perfil ou modelo. |
| `run_batch.py --resume-check` | Todos os jobs são reutilizáveis. | Há job pendente ou inválido. |
| `run_batch.py` | Lote sem falha final. | Houve falha ou validação inválida. |
| `run_benchmark_a.ps1` | Preflight e execução passaram. | Falha de preflight ou lote. |
| `run_all_features_host.ps1` | Preflight e lote passaram. | Falha de preflight ou lote. |
| `check_server_readiness.ps1` | Readiness PASS. | Qualquer gate ou higiene falhou. |


## 19.4 Consultar o último código no PowerShell

```powershell
$LASTEXITCODE
if ($LASTEXITCODE -ne 0) {
  throw "O comando anterior falhou com código $LASTEXITCODE"
}
```


# 20. Solução de problemas

| Sintoma | Correção |
|---|---|
| O output apareceu em `host\host` | Foi passado um `--output-root` que já terminava em `host`. Passe o diretório base, por exemplo `outputs\v3`. |
| `Source Inventory not found` | Em execução direta, rode `scripts.build_source_inventory` no mesmo output root antes do adapter. |
| `Unknown suite` | Confira os nomes da seção 10 ou execute `show_benchmark_plan.py --suite <nome>`. |
| `--profile is required when --parser is used` | Sempre informe os dois argumentos juntos. |
| `--parser is required when --profile is used` | Sempre informe os dois argumentos juntos. |
| `--compose-override has no effect with --runtime host` | Remova o overlay ou mude para Docker. |
| Parser Unstructured ou Xberg rejeitado em Docker | Eles estão marcados como host only e não possuem serviço Compose. |
| Teste funcional foi pulado | Use `-FunctionalTests`; no readiness, skip é falha. |
| Working tree deve estar limpo | Faça commit, stash ou descarte mudanças antes de `check_server_readiness.ps1`. |
| Tesseract não encontrado | Verifique `Get-Command tesseract` e PATH do serviço. |
| Idioma OCR não encontrado | Verifique `tesseract --list-langs` e `TESSDATA_PREFIX`. |
| Poppler não encontrado | Verifique `Get-Command pdfinfo` e `Get-Command pdftoppm`. |
| Modelo tentou baixar durante execução | Interrompa; execute a fase Prepare, depois Verify, e confirme as variáveis offline. |
| Job terminou por timeout | Aumente `--job-timeout-seconds` ou `-JobTimeoutSeconds`, investigando o `run.log`. |
| `python3 ./tests/test_runtime_campaing.py` falhou | O nome correto é `test_runtime_campaign.py`. |
| PowerShell tratou um path como texto | Use o operador `&` antes da variável que contém o executável. |
| Um PDF específico não foi selecionado com `--limit 1` | `--limit` usa ordem alfabética. Use execução direta ou uma pasta com um único PDF. |
| Container executou baseline | Use `run_batch.py` ou sobrescreva o entrypoint e informe `..._v2.py`. |


## 20.1 Conferir os paths resolvidos do host

```powershell
& $CorePython -c @'
from src.benchmark.execution_paths import (
    RUNTIME_HOST,
    resolve_model_root,
    resolve_output_root,
    resolve_venv_python,
)

for parser in (
    "pymupdf",
    "docling",
    "mineru",
    "paddleocr",
    "liteparse",
    "unstructured",
    "xberg",
):
    print(parser)
    print("  python:", resolve_venv_python(parser))
    print("  models:", resolve_model_root(RUNTIME_HOST, parser))

print("default host output:", resolve_output_root(RUNTIME_HOST))
'@
```


# 21. Receitas completas copiáveis


## 21.1 Instalação nova e campanha completa

```powershell
$Repo = 'C:\victor.perone\projects\document-ai-benchmark'
$InputDir = Join-Path $Repo 'data\raw\batch'
$OutputBase = Join-Path $Repo 'outputs\v3'

Set-Location $Repo

git fetch origin
git checkout perf/parser-runtime-optimization
git pull --ff-only origin perf/parser-runtime-optimization

.\scripts\windows\setup_envs.ps1
.\scripts\windows\check_envs.ps1

.\scripts\windows\prepare_all_models.ps1 -Mode Prepare
.\scripts\windows\prepare_all_models.ps1 -Mode Verify

.\scripts\windows\check_server_readiness.ps1 `
  -OutputRoot 'outputs\deep_smoke' `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput

.\scripts\windows\run_all_features_host.ps1 `
  -InputDir $InputDir `
  -OutputRoot $OutputBase `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput
```


## 21.2 Verificação sem baixar novamente

```powershell
Set-Location 'C:\victor.perone\projects\document-ai-benchmark'

.\scripts\windows\check_envs.ps1
.\scripts\windows\prepare_all_models.ps1 -Mode Verify
.\scripts\windows\run_deep_smoke_all.ps1 `
  -OutputRoot 'outputs\deep_smoke' `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput
```


## 21.3 Um único perfil completo Docling

```powershell
$Repo = 'C:\victor.perone\projects\document-ai-benchmark'
$InputDir = Join-Path $Repo 'data\raw\batch'
$OutputBase = Join-Path $Repo 'outputs\v3'
$CorePython = Join-Path $Repo '.venvs\core\Scripts\python.exe'

Set-Location $Repo

& $CorePython .\scripts\run_batch.py `
  --parser docling `
  --profile full_cpu_local `
  --runtime host `
  --input-dir $InputDir `
  --output-root $OutputBase `
  --artifacts all `
  --force `
  --no-summary `
  --job-timeout-seconds 7200 `
  --verbose-output
```


## 21.4 Um único PDF por execução direta Docling

```powershell
$Repo = 'C:\victor.perone\projects\document-ai-benchmark'
$InputDir = Join-Path $Repo 'data\raw\batch'
$Pdf = Join-Path $InputDir 'arquivo.pdf'
$DirectOutput = Join-Path $Repo 'outputs\v3-direct'
$PyMuPDFPython = Join-Path $Repo '.venvs\pymupdf\Scripts\python.exe'
$DoclingPython = Join-Path $Repo '.venvs\docling\Scripts\python.exe'
$DoclingModelRoot = Join-Path $Repo 'models\docling\docling\models'

Set-Location $Repo

& $PyMuPDFPython -m scripts.build_source_inventory `
  --input-dir $InputDir `
  --output-dir (Join-Path $DirectOutput '_source_inventory') `
  --only 'arquivo.pdf'

& $DoclingPython -m src.parsers.docling_v2 `
  --input $Pdf `
  --output-root $DirectOutput `
  --profile full_cpu_local `
  --device cpu `
  --threads 2 `
  --model-artifacts-path $DoclingModelRoot `
  --artifacts all `
  --verbose
```


## 21.5 Planejar a suíte completa sem executar

```powershell
.\scripts\windows\run_all_features_host.ps1 `
  -InputDir 'C:\victor.perone\projects\document-ai-benchmark\data\raw\batch' `
  -OutputRoot 'C:\victor.perone\projects\document-ai-benchmark\outputs\v3' `
  -DryRun
```


## 21.6 Preflight da suíte completa

```powershell
.\scripts\windows\run_all_features_host.ps1 `
  -InputDir 'C:\victor.perone\projects\document-ai-benchmark\data\raw\batch' `
  -OutputRoot 'C:\victor.perone\projects\document-ai-benchmark\outputs\v3' `
  -PreflightOnly
```


## 21.7 Retomar campanha interrompida

```powershell
.\scripts\windows\run_all_features_host.ps1 `
  -InputDir 'C:\victor.perone\projects\document-ai-benchmark\data\raw\batch' `
  -OutputRoot 'C:\victor.perone\projects\document-ai-benchmark\outputs\v3' `
  -Resume `
  -JobTimeoutSeconds 7200 `
  -VerboseOutput
```


## 21.8 Verificar se a campanha está totalmente reutilizável

```powershell
& .\.venvs\core\Scripts\python.exe .\scripts\run_batch.py `
  --suite windows_all_features_host `
  --runtime host `
  --input-dir 'C:\victor.perone\projects\document-ai-benchmark\data\raw\batch' `
  --output-root 'C:\victor.perone\projects\document-ai-benchmark\outputs\v3' `
  --artifacts all `
  --resume-check
```


## 21.9 WSL: ciclo de smoke Docker

```bash
cd ~/workspace/document-ai-benchmark

python3 scripts/run_tests.py
docker compose config
docker compose build

python3 scripts/run_batch.py \
  --suite smoke_expanded \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-smoke \
  --artifacts all \
  --force \
  --continue-on-error \
  --no-summary \
  --verbose-output

python3 scripts/run_batch.py \
  --suite smoke_expanded \
  --runtime docker \
  --input-dir data/raw/batch \
  --output-root outputs/wsl-smoke \
  --artifacts all \
  --resume-check
```


# 22. Apêndice: todos os testes e comandos


## 22.1 Todos os testes comuns

### `test_artifact_contract.py`

```bash
python3 -m unittest tests.test_artifact_contract -v
```

```powershell
& $CorePython -m unittest tests.test_artifact_contract -v
```

### `test_c06_output_isolation.py`

```bash
python3 -m unittest tests.test_c06_output_isolation -v
```

```powershell
& $CorePython -m unittest tests.test_c06_output_isolation -v
```

### `test_content_validation.py`

```bash
python3 -m unittest tests.test_content_validation -v
```

```powershell
& $CorePython -m unittest tests.test_content_validation -v
```

### `test_cpu_resources.py`

```bash
python3 -m unittest tests.test_cpu_resources -v
```

```powershell
& $CorePython -m unittest tests.test_cpu_resources -v
```

### `test_docker_non_regression.py`

```bash
python3 -m unittest tests.test_docker_non_regression -v
```

```powershell
& $CorePython -m unittest tests.test_docker_non_regression -v
```

### `test_docling_validators.py`

```bash
python3 -m unittest tests.test_docling_validators -v
```

```powershell
& $CorePython -m unittest tests.test_docling_validators -v
```

### `test_external_tools.py`

```bash
python3 -m unittest tests.test_external_tools -v
```

```powershell
& $CorePython -m unittest tests.test_external_tools -v
```

### `test_host_only_parser_guard.py`

```bash
python3 -m unittest tests.test_host_only_parser_guard -v
```

```powershell
& $CorePython -m unittest tests.test_host_only_parser_guard -v
```

### `test_model_manifest.py`

```bash
python3 -m unittest tests.test_model_manifest -v
```

```powershell
& $CorePython -m unittest tests.test_model_manifest -v
```

### `test_native_bundle.py`

```bash
python3 -m unittest tests.test_native_bundle -v
```

```powershell
& $CorePython -m unittest tests.test_native_bundle -v
```

### `test_new_runtime_specs.py`

```bash
python3 -m unittest tests.test_new_runtime_specs -v
```

```powershell
& $CorePython -m unittest tests.test_new_runtime_specs -v
```

### `test_new_suite_contracts.py`

```bash
python3 -m unittest tests.test_new_suite_contracts -v
```

```powershell
& $CorePython -m unittest tests.test_new_suite_contracts -v
```

### `test_paddleocr_model_paths.py`

```bash
python3 -m unittest tests.test_paddleocr_model_paths -v
```

```powershell
& $CorePython -m unittest tests.test_paddleocr_model_paths -v
```

### `test_path_portability.py`

```bash
python3 -m unittest tests.test_path_portability -v
```

```powershell
& $CorePython -m unittest tests.test_path_portability -v
```

### `test_plan01_windows_contract.py`

```bash
python3 -m unittest tests.test_plan01_windows_contract -v
```

```powershell
& $CorePython -m unittest tests.test_plan01_windows_contract -v
```

### `test_post_validation.py`

```bash
python3 -m unittest tests.test_post_validation -v
```

```powershell
& $CorePython -m unittest tests.test_post_validation -v
```

### `test_preflight_contract.py`

```bash
python3 -m unittest tests.test_preflight_contract -v
```

```powershell
& $CorePython -m unittest tests.test_preflight_contract -v
```

### `test_process_tree.py`

```bash
python3 -m unittest tests.test_process_tree -v
```

```powershell
& $CorePython -m unittest tests.test_process_tree -v
```

### `test_run_batch_cli.py`

```bash
python3 -m unittest tests.test_run_batch_cli -v
```

```powershell
& $CorePython -m unittest tests.test_run_batch_cli -v
```

### `test_run_batch_execution_validation.py`

```bash
python3 -m unittest tests.test_run_batch_execution_validation -v
```

```powershell
& $CorePython -m unittest tests.test_run_batch_execution_validation -v
```

### `test_run_batch_limit.py`

```bash
python3 -m unittest tests.test_run_batch_limit -v
```

```powershell
& $CorePython -m unittest tests.test_run_batch_limit -v
```

### `test_run_batch_preflight.py`

```bash
python3 -m unittest tests.test_run_batch_preflight -v
```

```powershell
& $CorePython -m unittest tests.test_run_batch_preflight -v
```

### `test_run_batch_resume_check.py`

```bash
python3 -m unittest tests.test_run_batch_resume_check -v
```

```powershell
& $CorePython -m unittest tests.test_run_batch_resume_check -v
```

### `test_run_batch_resume_validation.py`

```bash
python3 -m unittest tests.test_run_batch_resume_validation -v
```

```powershell
& $CorePython -m unittest tests.test_run_batch_resume_validation -v
```

### `test_run_batch_summaries.py`

```bash
python3 -m unittest tests.test_run_batch_summaries -v
```

```powershell
& $CorePython -m unittest tests.test_run_batch_summaries -v
```

### `test_runtime_campaign.py`

```bash
python3 -m unittest tests.test_runtime_campaign -v
```

```powershell
& $CorePython -m unittest tests.test_runtime_campaign -v
```

### `test_runtime_specs.py`

```bash
python3 -m unittest tests.test_runtime_specs -v
```

```powershell
& $CorePython -m unittest tests.test_runtime_specs -v
```

### `test_suite_contracts.py`

```bash
python3 -m unittest tests.test_suite_contracts -v
```

```powershell
& $CorePython -m unittest tests.test_suite_contracts -v
```

### `test_summary_comparisons.py`

```bash
python3 -m unittest tests.test_summary_comparisons -v
```

```powershell
& $CorePython -m unittest tests.test_summary_comparisons -v
```

### `test_summary_io.py`

```bash
python3 -m unittest tests.test_summary_io -v
```

```powershell
& $CorePython -m unittest tests.test_summary_io -v
```

### `test_summary_scripts.py`

```bash
python3 -m unittest tests.test_summary_scripts -v
```

```powershell
& $CorePython -m unittest tests.test_summary_scripts -v
```

### `test_visual_worker.py`

```bash
python3 -m unittest tests.test_visual_worker -v
```

```powershell
& $CorePython -m unittest tests.test_visual_worker -v
```

### `test_windows_setup_registry.py`

```bash
python3 -m unittest tests.test_windows_setup_registry -v
```

```powershell
& $CorePython -m unittest tests.test_windows_setup_registry -v
```


## 22.2 Todos os testes específicos no Windows host


### pymupdf

Toda a pasta:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser pymupdf `
  -VerboseOutput
```

#### `test_api_kwargs.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser pymupdf `
  -TestPath test_api_kwargs.py `
  -VerboseOutput
```

#### `test_functional_deep_smoke.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser pymupdf `
  -TestPath test_functional_deep_smoke.py `
  -VerboseOutput `
  -FunctionalTests `
  -FunctionalTimeoutSeconds 7200
```

#### `test_preflight.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser pymupdf `
  -TestPath test_preflight.py `
  -VerboseOutput
```

#### `test_profiles.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser pymupdf `
  -TestPath test_profiles.py `
  -VerboseOutput
```

#### `test_serialization.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser pymupdf `
  -TestPath test_serialization.py `
  -VerboseOutput
```

#### `test_visual_enrichment.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser pymupdf `
  -TestPath test_visual_enrichment.py `
  -VerboseOutput
```


### docling

Toda a pasta:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser docling `
  -VerboseOutput
```

#### `test_enriched_markdown.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser docling `
  -TestPath test_enriched_markdown.py `
  -VerboseOutput
```

#### `test_functional_deep_smoke.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser docling `
  -TestPath test_functional_deep_smoke.py `
  -VerboseOutput `
  -FunctionalTests `
  -FunctionalTimeoutSeconds 7200
```

#### `test_heading_table_profiles.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser docling `
  -TestPath test_heading_table_profiles.py `
  -VerboseOutput
```

#### `test_picture_description.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser docling `
  -TestPath test_picture_description.py `
  -VerboseOutput
```


### mineru

Toda a pasta:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser mineru `
  -VerboseOutput
```

#### `test_cli_contract.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser mineru `
  -TestPath test_cli_contract.py `
  -VerboseOutput
```

#### `test_functional_deep_smoke.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser mineru `
  -TestPath test_functional_deep_smoke.py `
  -VerboseOutput `
  -FunctionalTests `
  -FunctionalTimeoutSeconds 7200
```

#### `test_preflight.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser mineru `
  -TestPath test_preflight.py `
  -VerboseOutput
```

#### `test_profiles.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser mineru `
  -TestPath test_profiles.py `
  -VerboseOutput
```

#### `test_serialization.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser mineru `
  -TestPath test_serialization.py `
  -VerboseOutput
```


### paddleocr

Toda a pasta:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser paddleocr `
  -VerboseOutput
```

#### `test_api_contract.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser paddleocr `
  -TestPath test_api_contract.py `
  -VerboseOutput
```

#### `test_functional_deep_smoke.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser paddleocr `
  -TestPath test_functional_deep_smoke.py `
  -VerboseOutput `
  -FunctionalTests `
  -FunctionalTimeoutSeconds 7200
```

#### `test_preflight.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser paddleocr `
  -TestPath test_preflight.py `
  -VerboseOutput
```

#### `test_profiles.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser paddleocr `
  -TestPath test_profiles.py `
  -VerboseOutput
```

#### `test_serialization.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser paddleocr `
  -TestPath test_serialization.py `
  -VerboseOutput
```


### liteparse

Toda a pasta:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -VerboseOutput
```

#### `test_canonical_source.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -TestPath test_canonical_source.py `
  -VerboseOutput
```

#### `test_functional_deep_smoke.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -TestPath test_functional_deep_smoke.py `
  -VerboseOutput `
  -FunctionalTests `
  -FunctionalTimeoutSeconds 7200
```

#### `test_images.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -TestPath test_images.py `
  -VerboseOutput
```

#### `test_preflight.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -TestPath test_preflight.py `
  -VerboseOutput
```

#### `test_profiles.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -TestPath test_profiles.py `
  -VerboseOutput
```

#### `test_rotation.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -TestPath test_rotation.py `
  -VerboseOutput
```

#### `test_routing.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -TestPath test_routing.py `
  -VerboseOutput
```

#### `test_serialization.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser liteparse `
  -TestPath test_serialization.py `
  -VerboseOutput
```


### unstructured

Toda a pasta:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -VerboseOutput
```

#### `test_adapter_contract.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_adapter_contract.py `
  -VerboseOutput
```

#### `test_functional_deep_smoke.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_functional_deep_smoke.py `
  -VerboseOutput `
  -FunctionalTests `
  -FunctionalTimeoutSeconds 7200
```

#### `test_native_serialization.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_native_serialization.py `
  -VerboseOutput
```

#### `test_ocr_agent.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_ocr_agent.py `
  -VerboseOutput
```

#### `test_page_contract.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_page_contract.py `
  -VerboseOutput
```

#### `test_page_mapping.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_page_mapping.py `
  -VerboseOutput
```

#### `test_per_page_metrics.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_per_page_metrics.py `
  -VerboseOutput
```

#### `test_preflight.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_preflight.py `
  -VerboseOutput
```

#### `test_profiles.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_profiles.py `
  -VerboseOutput
```

#### `test_renderer.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser unstructured `
  -TestPath test_renderer.py `
  -VerboseOutput
```


### xberg

Toda a pasta:

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -VerboseOutput
```

#### `test_adapter_contract.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_adapter_contract.py `
  -VerboseOutput
```

#### `test_api_probe_contract.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_api_probe_contract.py `
  -VerboseOutput
```

#### `test_config_builder.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_config_builder.py `
  -VerboseOutput
```

#### `test_functional_deep_smoke.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_functional_deep_smoke.py `
  -VerboseOutput `
  -FunctionalTests `
  -FunctionalTimeoutSeconds 7200
```

#### `test_layout_config.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_layout_config.py `
  -VerboseOutput
```

#### `test_page_contract.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_page_contract.py `
  -VerboseOutput
```

#### `test_preflight.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_preflight.py `
  -VerboseOutput
```

#### `test_profiles.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_profiles.py `
  -VerboseOutput
```

#### `test_qr_codes.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_qr_codes.py `
  -VerboseOutput
```

#### `test_result_validation.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_result_validation.py `
  -VerboseOutput
```

#### `test_serialization.py`

```powershell
.\scripts\windows\run_host_parser_tests.ps1 `
  -Parser xberg `
  -TestPath test_serialization.py `
  -VerboseOutput
```


## 22.3 Todos os testes específicos Docker disponíveis no WSL

```bash
python3 scripts/run_parser_tests.py pymupdf
```

```bash
python3 scripts/run_parser_tests.py docling
```

```bash
python3 scripts/run_parser_tests.py mineru
```

```bash
python3 scripts/run_parser_tests.py paddleocr
```

```bash
python3 scripts/run_parser_tests.py liteparse
```


## 22.4 Comandos de ajuda recomendados

```powershell
& $CorePython .\scripts\run_batch.py --help
& $CorePython .\scripts\run_runtime_campaign.py --help
& $CorePython .\scripts\parser_preflight.py --help
& $CorePython .\scripts\parser_deep_smoke.py --help
& $CorePython .\scripts\build_source_inventory.py --help

& $PyMuPDFPython -m src.parsers.pymupdf_v2 --help
& $DoclingPython -m src.parsers.docling_v2 --help
& $MinerUPython -m src.parsers.mineru_v2 --help
& $PaddlePython -m src.parsers.paddleocr_v2 --help
& $LiteParsePython -m src.parsers.liteparse_v2 --help
& $UnstructuredPython -m src.parsers.unstructured_v2 --help
& $XbergPython -m src.parsers.xberg_v2 --help

Get-Help .\scripts\windows\setup_envs.ps1 -Detailed
Get-Help .\scripts\windows\prepare_all_models.ps1 -Detailed
Get-Help .\scripts\windows\run_host_parser_tests.ps1 -Detailed
Get-Help .\scripts\windows\run_deep_smoke_all.ps1 -Detailed
Get-Help .\scripts\windows\check_server_readiness.ps1 -Detailed
Get-Help .\scripts\windows\run_benchmark_a.ps1 -Detailed
Get-Help .\scripts\windows\run_all_features_host.ps1 -Detailed
```


# 23. Registro do snapshot

| Campo | Valor |
|---|---|
| Branch | `perf/parser-runtime-optimization` |
| Commit | `1cb9cfafa719e939cd729e7f1b1366ad8ee9173f` |
| Árvore | `12e36214fc59eb497d549d842b045071c19e6528` |
| Data UTC do commit | `2026-09-03T16:35:48Z` |
| Destino recomendado | `docs/WINDOWS_HOST_AND_WSL_EXECUTION_GUIDE.md` |

Antes de uma campanha formal, registre:

```powershell
git rev-parse HEAD
git status --porcelain
(Get-Date).ToUniversalTime().ToString('o')
```

Se o SHA da branch tiver mudado, compare novamente:

- `scripts/run_batch.py`;
- scripts PowerShell em `scripts/windows`;
- `config/benchmark_profiles.json`;
- `config/runtime_campaign.json`;
- argumentos dos adapters em `src/parsers`;
- `src/benchmark/runtime_specs.py`;
- `src/benchmark/execution_paths.py`.

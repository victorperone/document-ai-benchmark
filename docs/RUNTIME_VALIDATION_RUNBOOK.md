# Runtime Validation Runbook

**Branch:** `perf/parser-runtime-optimization`
**Data:** 2026-09-03
**Status:** Código preparado — homologação nativa Windows Server pendente

---

## 1. Propósito e escopo

Este runbook descreve o protocolo de validação de prontidão do benchmark de PDF para Markdown no Windows Server 2025. Ele cobre duas etapas distintas:

| Etapa | Ambiente | O que valida |
|---|---|---|
| **Validação WSL** | WSL (Linux no Windows) | Corretude de código, sintaxe, contratos de artefatos, testes unitários |
| **Certificação Windows** | Windows Server 2025 nativo | Inferência real, modelos, encerramento de processos, isolamento offline |

**A validação WSL nunca substitui a certificação Windows.** Testes que passam no WSL apenas comprovam que o código está sintaticamente correto e que os contratos lógicos estão satisfeitos. A inferência efetiva de modelos, o comportamento de processos Windows e a ausência de conexões de rede só podem ser comprovados no host nativo.

---

## 2. Validação no WSL (antes de levar para o Windows Server)

Execute no WSL após cada conjunto de alterações:

```bash
python3 scripts/run_tests.py
python3 -m compileall -q src scripts parser_tests tests
python3 scripts/parser_deep_smoke.py --validate-fixture-only
git diff --check
```

Todos devem terminar com código zero. Se qualquer um falhar, **não prosseguir para o Windows Server**.

---

## 3. Fase Prepare — aquisição de modelos (requer rede)

Execute **com acesso à internet**, antes de aplicar qualquer isolamento de rede.

```powershell
.\scripts\windows\setup_envs.ps1
.\scripts\windows\check_envs.ps1
.\scripts\windows\prepare_all_models.ps1 -Mode Prepare
```

O que acontece nessa fase:
- Ambientes virtuais por parser são criados e verificados
- Modelos são baixados do Hugging Face para diretórios locais sob `models/`
- Manifestos de modelo são gravados com componente, versão, data e hashes de arquivos
- Nenhuma inferência real ocorre ainda

Ao final, **desconecte a rede ou aplique firewall externo** antes de prosseguir para a fase Verify.

---

## 4. Fase Verify — verificação offline (sem rede)

Após isolar a rede, defina as variáveis de confirmação e execute:

```powershell
# Confirmação manual do operador após isolar a rede
$env:DOCUMENT_AI_NETWORK_ISOLATED = '1'
$env:DOCUMENT_AI_ENFORCE_OFFLINE = '1'

.\scripts\windows\prepare_all_models.ps1 -Mode Verify
```

**`DOCUMENT_AI_NETWORK_ISOLATED`** é uma variável de confirmação — o script **não modifica o firewall**. O operador é responsável por garantir o isolamento real antes de definir essa variável.

**`DOCUMENT_AI_ENFORCE_OFFLINE`** ativa o `sitecustomize.py` (injetado via `PYTHONPATH`) que intercepta tentativas de conexão Python e as registra em `logs/offline_guard.jsonl`. Qualquer tentativa registrada reprova o gate.

O que a fase Verify valida:
- Manifesto de cada componente corresponde aos arquivos presentes (hash SHA-256)
- Inferência real funciona offline (PaddleOCR, SmolVLM, MinerU, etc.)
- Nenhum arquivo temporário é deixado após a verificação

> **Isolamento de rede no nível do SO é um pré-requisito externo.** Bibliotecas nativas (como PaddlePaddle ou PyTorch) podem abrir sockets sem passar pelo Python, contornando o `sitecustomize.py`. O firewall externo é a única garantia completa.

---

## 5. Execução completa e gate de readiness

```powershell
.\scripts\windows\run_all_features_host.ps1 -DryRun
.\scripts\windows\check_server_readiness.ps1 -VerboseOutput
```

O dry-run deve exibir exatamente **7 jobs** com os perfis definidos. Se exibir número diferente, há erro na configuração da suíte.

### Critério de aceite

O `check_server_readiness.ps1` é aceito somente com:

```
SERVER_READINESS=PASS
PARSERS_READY=pymupdf,docling,mineru,paddleocr,liteparse,unstructured,xberg
PARSERS_FAILED=
FUNCTIONAL_TESTS_SKIPPED=0
```

Além disso:
- Manifestos idênticos antes e depois da execução
- Zero tentativas de conexão externa (`logs/offline_guard.jsonl` vazio ou ausente)
- Zero processos Python residuais do repositório
- Zero arquivos temporários com prefixos `document-ai-*`, `document-ai-visual-*`, `unstructured_images_*`, `mineru-verify-*`, `visual_crops`
- Zero links Markdown quebrados nos artefatos
- Zero Markdowns inesperadamente vazios

### Como `PARSERS_READY` é calculado

`PARSERS_READY` é derivado **exclusivamente** de linhas `DEEP_SMOKE_PARSER=PASS parser=<nome>` presentes no log do deep smoke (`logs/windows_readiness/<timestamp>/deep_smoke.log`), e somente quando o gate `deep_smoke` terminou com código zero (`GATE_deep_smoke=PASS`).

**A existência de `metrics.json` não conta como parser pronto.**

---

## 6. Testes funcionais — proibição de pular

Testes funcionais marcados como `skip` em ambiente Windows são **falha**, não neutros. O campo `FUNCTIONAL_TESTS_SKIPPED` na saída do readiness deve ser zero. Qualquer valor diferente de zero indica que o ambiente não estava pronto para executar os testes, e o resultado não pode ser considerado válido.

---

## 7. Onde encontrar os logs

| Artefato | Local |
|---|---|
| Relatório de readiness | `logs/windows_readiness/<timestamp>/summary.txt` |
| Falhas detalhadas | `logs/windows_readiness/<timestamp>/failures.txt` |
| Log do deep smoke | `logs/windows_readiness/<timestamp>/deep_smoke.log` |
| Tentativas de rede bloqueadas | `logs/offline_guard.jsonl` |
| Resíduos de temp no gate | `logs/windows_readiness/<timestamp>/hygiene_temp_residues.log` |
| Leaks de processo | `logs/windows_readiness/<timestamp>/process_leaks.log` |

---

## 8. Resumo das variáveis de ambiente relevantes

| Variável | Quem define | Significado |
|---|---|---|
| `DOCUMENT_AI_NETWORK_ISOLATED` | Operador (manual) | Confirma que o isolamento de rede foi aplicado externamente |
| `DOCUMENT_AI_ENFORCE_OFFLINE` | Operador (manual) | Ativa o `sitecustomize.py` para bloquear conexões Python |
| `DOCUMENT_AI_OFFLINE_LOG` | Opcional | Caminho alternativo para o log JSONL do guard offline |
| `BENCHMARK_VISUAL_ROOT` | Scripts de prepare | Raiz dos modelos do worker visual |
| `BENCHMARK_MINERU_ROOT` | Scripts de prepare | Raiz dos modelos MinerU |
| `MINERU_TOOLS_CONFIG_JSON` | Scripts de prepare | Caminho do `mineru.json` local |
| `HF_HUB_OFFLINE` | Scripts de verify | Força Hugging Face a não tentar rede |
| `TRANSFORMERS_OFFLINE` | Scripts de verify | Força Transformers a não tentar rede |
| `LITEPARSE_CONTRACT_PATH` | Script de probe | Caminho do JSON de contrato da API LiteParse |

---

## 9. Fluxo completo resumido

```
[WSL] python3 scripts/run_tests.py → zero
[WSL] python3 -m compileall -q src scripts parser_tests tests → zero
[WSL] python3 scripts/parser_deep_smoke.py --validate-fixture-only → zero

[Windows — com rede]
setup_envs.ps1
check_envs.ps1
prepare_all_models.ps1 -Mode Prepare

[Operador: desconectar rede / aplicar firewall externo]

[Windows — sem rede]
$env:DOCUMENT_AI_NETWORK_ISOLATED = '1'
$env:DOCUMENT_AI_ENFORCE_OFFLINE  = '1'
prepare_all_models.ps1 -Mode Verify
run_all_features_host.ps1 -DryRun        → exibe exatamente 7 jobs
check_server_readiness.ps1 -VerboseOutput → SERVER_READINESS=PASS
```

**A entrega está completa somente quando `SERVER_READINESS=PASS` for obtido no Windows Server nativo.**
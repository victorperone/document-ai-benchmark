# Plano 01 — Prontidão nativa no Windows Server

## Resumo

- [x] A revisão do anexo foi confirmada contra a branch limpa `perf/parser-runtime-optimization`, commit `5e7e88522ba4f902fb2c8653a1ea30c81ec22aa3`. Os bloqueios principais são reais: suíte incompleta, inferência funcional ausente, artefatos vazios aceitos, modelos não certificados e falhas silenciosas nos adaptadores.
- [x] Corrigir também uma lacuna não registrada no anexo: `python3 scripts/run_tests.py` coleta 804 testes, mas falha ao importar `pytest` em `test_artifact_contract.py`; converter os 22 casos para `unittest` e corrigir os testes Docker que procuram `docker-compose.yml` em vez de `compose.yaml`.
- [x] O desenvolvimento e os testes unitários serão feitos no WSL, mas todo código de host deverá usar caminhos Windows, PowerShell 5.1, `python.exe`, encerramento de processos Windows e modelos abaixo do repositório.
- [x] A entrega escolhida é “código preparado”: não declarar `SERVER_READINESS=PASS` sem uma execução posterior no Windows Server.
- [x] Materializar este plano integralmente em `plan01.md`, na raiz, antes da primeira alteração de implementação, mantendo os itens como checklist.

## Contratos e interfaces

- [x] Adicionar a suíte `windows_all_features_host` com exatamente: `pymupdf/full_cpu_local_visual`, `docling/full_cpu_local`, `mineru/full_cpu_local`, `paddleocr/full_cpu_local`, `liteparse/full_cpu_local`, `unstructured/full_cpu_local` e `xberg/full_cpu_layout`. Preservar as suítes históricas.
- [x] Criar `run_all_features_host.ps1` com execução host, todos os artefatos, modo fresco por padrão e opções `-Resume`, `-DryRun`, `-PreflightOnly`, `-VerboseOutput` e `-JobTimeoutSeconds`. O `OutputRoot` padrão será `outputs`, pois o runner já acrescenta `host`.
- [x] Estender `ParserArtifactInput` com `enriched_document_markdown`, usado quando há Markdown enriquecido global sem mapeamento confiável por página. Precedência: enriquecido global, páginas enriquecidas, `document.md`, Markdown nativo.
- [x] Quando selecionado, `document.enriched.md` sempre existirá. Métricas distinguirão `selected`, `present`, `enrichment_applied`, `contains_derived_content` e a origem do fallback.
- [x] Quando `page_mapping_status=unavailable`, normalizar o Markdown nativo global sem heurísticas de repetição entre páginas; registrar `normalization_mode=global_without_page_repetition` e manter `document.jsonl` explicitamente indisponível.
- [x] Permitir em `raw_origin_kind` uma origem “nativa com links realocados”, limitada à reescrita segura de assets oficiais. Nenhum outro conteúdo do Markdown poderá ser alterado.
- [x] Adicionar `content_validation` às métricas, com existência, UTF-8, bytes, presença alfanumérica, expectativa e justificativa por artefato. Saída vazia, somente comentários ou somente separadores falhará quando o inventário e o perfil exigirem conteúdo.
- [x] Introduzir resolução de raízes por componente, mantendo `resolve_model_root` compatível. `visual_enrichment` apontará para `models/visual-enrichment`; todos os caminhos host serão absolutos e descendentes de `models/`.
- [x] Criar o contrato comum `ProcessResult`/`run_process_tree`: Job Object via `ctypes` no Windows, `CREATE_NEW_PROCESS_GROUP`, fallback `taskkill /T /F`, espera do encerramento e fallback POSIX testável no WSL.
- [x] Padronizar scripts de modelos em `-Mode Prepare|Verify`. `Prepare` pode usar rede e grava o manifesto; `Verify` é offline e somente leitura, valida hashes e executa inferência real. Manifesto v1: componente, versão, data de preparação e arquivos com caminho relativo, tamanho e SHA-256.

## Implementação em fases

### 1. Base comum e segurança operacional

- [x] Corrigir o runner de testes para `unittest`, ativar os testes de contrato e o teste real de não regressão Docker.
- [x] Incluir `setup_visual_enrichment.ps1` em `setup_envs.ps1`; reforçar `check_envs.ps1` com versões, `pip check` e executáveis externos.
- [ ] Criar os preparadores de MinerU, PaddleOCR, LiteParse, enriquecimento visual e Xberg; adaptar Docling/Unstructured ao contrato comum; agregar na ordem Docling, MinerU, PaddleOCR, LiteParse, visual, Unstructured e Xberg.
- [x] Criar helpers compartilhados para limpar bundles, coletar links Markdown locais, bloquear path traversal, copiar para `native/assets`, reescrever links e produzir manifestos.
- [x] Limpar somente o diretório-folha exato de cada job antes de toda execução pendente/fresca. Em `--resume`, reutilizar somente após validação completa de proveniência, hashes, assets e conteúdo.
- [x] Aplicar timeout de 3.600 segundos aos jobs host e ao MinerU; aplicar 300/180/10 segundos ao startup/request/shutdown do worker visual. Inventários, preflights e CLIs auxiliares também usarão o helper de árvore.
- [x] Manter Docker como runtime padrão e não alterar mounts ou imagens apenas para atender o Windows.

### 2. Worker visual e PyMuPDF

- [ ] Corrigir a inicialização PaddleOCR: remover `show_log`, usar os nomes 3.7 atuais e tratar diretórios explícitos como fonte de verdade; `pt` será o identificador PaddleOCR e `por` continuará no RapidOCR/Tesseract.
- [ ] Preparar PP-OCRv6 det/rec e SmolVLM em `models/visual-enrichment`; não reutilizar diretórios do LiteParse. Como modelos explícitos fazem `lang`/`ocr_version` perderem efeito, o manifesto certificará os modelos realmente carregados.
- [ ] Tornar falha visual fatal no perfil usado pela nova suíte.
- [ ] Drenar `stdout` e `stderr` em threads, usar filas com timeout, anexar o tail de erro às exceções e garantir encerramento da árvore.
- [ ] Aceitar resultados PaddleOCR como dicionário, subscritível ou objeto; corrigir o template SmolVLM com `tokenize=False`, tensores em CPU e `torch.no_grad()`.
- [ ] Detectar regiões de layout e imagens embutidas não classificadas, excluir máscaras, deduplicar por hash, não persistir imagens e inserir blocos derivados junto à posição original sempre que houver `pos`.

### 3. Adaptadores

- [ ] **LiteParse:** usar exclusivamente `result.text` como Markdown nativo; relegar `text_items` a diagnóstico. Sem páginas confiáveis, usar mapping indisponível e apêndice derivado global. Somente executar merge regional com geometria compatível; caso contrário usar `derived_only`. Separar fonte/enriquecido/derivados, impedir OCR duplicado e mapear integralmente todas as opções do perfil. Preparar e testar SmolVLM local.
- [ ] **Unstructured:** processar crops de Image/Table com o worker visual antes do `TemporaryDirectory` fechar; persistir somente texto, descrição, hash, dimensões, página, bbox e estado do cleanup. Remover comentários com caminhos mortos, aceitar `auto` para tabelas, tornar `-SingleThread` opcional, preservar conteúdo útil sem página e declarar mapping completo somente quando comprovado.
- [ ] **PaddleOCR:** preparar todos os modelos do perfil PP-OCRv5, incluindo layout, OCR, orientação, unwarping, tabelas, células, fórmula, gráfico e selo. Separar argumentos de inicialização e inferência pela assinatura instalada, iterar com `predict_iter`, fechar o pipeline em `finally`, usar o agregador Markdown oficial e persistir suas imagens. Serializar integralmente OCR, tabelas, fórmulas, gráficos, selos e preprocessamento. Manter PP-OCRv6 fora da primeira campanha principal.
- [x] **Xberg:** usar `full_cpu_layout`, cache exclusivamente em `models/xberg`, layout e QR offline. Preservar `document.content` como Markdown global; página ausente será erro, salvo API comprovadamente global. Serializar tipos conhecidos antes do fallback textual e persistir/referenciar assets oficiais quando existirem. Manter `language_detection=None` e idiomas `por, eng`.
- [ ] **MinerU:** adquirir modelos pela ferramenta oficial, reescrever `mineru.json` com caminhos Windows absolutos sob `models/mineru` e validar modo local. Usar timeout com árvore, recriar o bundle, preservar `content_list`, `middle` e todo asset local referenciado. `raw.md` será o Markdown oficial com apenas links realocados; o enriquecido usará a mesma saída oficial válida.
- [ ] **Docling:** usar o export global oficial em `raw.md`; falhar em erro de exportação de página ou marcar mapping indisponível quando a API for somente global. Recursos solicitados nunca poderão cair em `ImportError` silencioso. Manter TableFormer V1 na suíte inicial, impedir mutação das páginas-fonte, enriquecer proveniência visual e derivar a versão registrada do pacote real.

### 4. Smoke profundo, readiness e documentação

- [x] Criar uma fixture determinística, local e versionada de duas páginas contendo título, texto digital em português, tabela, fórmula, código, gráfico/diagrama, imagem com texto, QR válido, selo e uma região rasterizada/rotacionada. Versionar PDF, assets e manifesto com SHA-256.
- [x] Criar `parser_deep_smoke.py` e `run_deep_smoke_all.ps1`. Executar os sete perfis sequencialmente, offline, em saída limpa, com todos os artefatos, pós-validação, verificação de hashes dos modelos e ausência de descendentes.
- [x] Criar `check_server_readiness.ps1`: repositório limpo/SHA, ambiente, executáveis, modelos `Verify`, testes comuns, testes de cada parser, smoke profundo, links, temporários, downloads e leaks. Gravar relatório em `logs/windows_readiness/<timestamp>/` e imprimir `SERVER_READINESS`, `COMMIT`, `PARSERS_READY`, `PARSERS_FAILED` e `FUNCTIONAL_TESTS_SKIPPED`.
- [ ] Reestruturar `docs/WINDOWS_SERVER_HOST_STATUS.md` como documento canônico: branch/SHA dinâmicos, separação WSL versus Windows nativo, milestone antigo preservado como histórico, gates atuais, comandos oficiais e status “código preparado; homologação Windows pendente”. Não criar um novo guia.
- [ ] Atualizar `plan01.md` ao concluir cada fase, sem marcar readiness real como concluído até receber os logs do Windows Server.

## Testes e critérios de aceite

- [ ] No WSL: `python3 scripts/run_tests.py` deve terminar em zero, coletar os 22 testes de artefatos, não ocultar o teste de `compose.yaml` e cobrir caminhos Windows por mocks.
- [ ] Testar fallback enriquecido, Markdown global, conteúdo vazio/comentários, PDF comprovadamente vazio, limpeza de assets antigos, resume íntegro/corrompido, links e traversal.
- [x] Testar árvore de processos com pai e filho bloqueados; ambos devem desaparecer após timeout.
- [ ] Para cada parser, adicionar testes unitários de contratos e testes funcionais condicionados ao ambiente Windows/modelos. O readiness habilitará os funcionais e falhará se algum for pulado.
- [ ] Critérios específicos da fixture: QR exato no Xberg; imagem textual inserida uma vez no LiteParse/Unstructured/PyMuPDF; estruturas de tabela/fórmula presentes nos parsers compatíveis; pipelines fechados; zero imagens visuais temporárias persistidas.
- [ ] O dry-run da nova suíte deve mostrar exatamente sete jobs e os perfis definidos. As suítes antigas e o runtime Docker padrão devem continuar inalterados.
- [ ] O aceite desta entrega termina com testes WSL verdes, scripts e documentação preparados. `SERVER_READINESS=PASS` permanece pendente até o operador executar `check_server_readiness.ps1` no Windows Server nativo.

## Homologação pendente

- [ ] Executar `scripts\windows\check_server_readiness.ps1` no Windows Server nativo e anexar um relatório com `SERVER_READINESS=PASS`; esta etapa não pode ser concluída nem simulada no WSL.

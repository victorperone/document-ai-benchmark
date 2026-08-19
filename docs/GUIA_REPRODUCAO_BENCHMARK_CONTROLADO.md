# Guia completo de reprodução do benchmark controlado de parsers PDF

**Projeto:** `victorperone/document-ai-benchmark`  
**Branch reproduzida:** `milestone/mvp-ocr-auto-v2`  
**Documento:** `data/benchmark/controlled/benchmark_controlado_v1.pdf`  
**Parsers:** PyMuPDF4LLM, Docling, MinerU e PaddleOCR / PPStructureV3  
**Ambiente de referência:** Linux ou Windows com WSL2, Bash, Docker Engine e Docker Compose  
**Público:** pessoas sem experiência prévia em OCR, parsers de PDF ou Docker

---

## 1. Objetivo deste guia

Este guia leva uma pessoa desde uma máquina sem o repositório até a reprodução completa do experimento Controlled12. Ao terminar, a pessoa terá:

1. clonado a branch correta do GitHub;
2. validado Git, Docker e Docker Compose;
3. construído quatro imagens Docker independentes;
4. baixado e persistido os modelos locais necessários;
5. executado testes rápidos de cada ambiente;
6. criado um inventário objetivo do PDF;
7. executado o mesmo documento com os quatro parsers;
8. produzido o mesmo contrato de seis artefatos por parser;
9. validado schema, documento, páginas, tokenizer, normalizador e monitor;
10. comparado tokens, tempo, memória, I/O, robustez e estrutura;
11. aberto e executado uma cópia do notebook de análise usando os resultados reproduzidos;
12. arquivado os resultados e as informações do ambiente.

Este é um benchmark operacional e estrutural. Ele mostra diferenças de processamento e preservação observáveis, mas não transforma automaticamente essas diferenças em um ranking universal de qualidade. Contagens internas de tabelas, fórmulas ou imagens são diagnósticos do parser, não ground truth.

---

## 2. O que o documento controlado testa

O PDF possui 12 páginas e combina casos deliberadamente diferentes:

- página 1: capa e tratamento de cabeçalho e rodapé especiais;
- página 2: tabela comum, acentos, moedas, números e caracteres especiais;
- página 3: tabela financeira com descrições em múltiplas linhas;
- página 4: tabela estreita com colunas difíceis e palavras quebradas;
- páginas 5 e 6: texto corrido, acentuação e formatação de parágrafos;
- página 7: listas, estilos mistos, símbolos matemáticos e início de tabela;
- página 8: continuação de tabela, texto sublinhado e fórmulas;
- página 9: tabela visual em orientação normal;
- páginas 10 e 11: tabelas visuais fisicamente rotacionadas;
- página 12: página quase vazia destinada à avaliação de cabeçalho, rodapé e normalização.

Esses casos permitem observar leitura de texto nativo, OCR seletivo ou integral, tabelas, fórmulas, rotação, ruído, redução de tokens e integridade por página.

---

## 3. Resultados de referência e limites de comparação

A execução oficial congelada no repositório apresentou aproximadamente:

| Parser | Perfil | Pipeline | Pico de RAM | Leitura em disco | Tokens limpos |
|---|---|---:|---:|---:|---:|
| PyMuPDF | `ocr_auto_rapidtess` | 8,15 s | 729 MB | 59 MB | 4.406 |
| Docling | `ocr_auto` | 31,31 s | 2.999 MB | 719 MB | 3.730 |
| MinerU | `auto` | 46,73 s | 3.240 MB | 4.365 MB | 6.085 |
| PaddleOCR | `mvp_structured` | 116,28 s | 6.204 MB | 2.217 MB | 4.666 |

Esses valores são referências, não critérios rígidos de aprovação.

- SHA-256, número de páginas, schema, tokenizer e configuração devem coincidir.
- Tempos, CPU, RAM e I/O variam com processador, memória, disco, Docker, temperatura e carga do sistema.
- Tokens tendem a ser estáveis quando commit, versões, modelos e configuração são idênticos, mas mudanças no ambiente podem alterar o resultado.
- A execução oficial foi feita em WSL2 com 20 CPUs lógicas. Outra máquina não deve ser reprovada apenas por ser mais lenta.

---

## 4. Decisões importantes antes de começar

### 4.1 Use Bash

Os comandos deste guia foram escritos para Bash em Linux ou WSL2. No Windows, abra uma distribuição WSL2 e execute tudo dentro dela. Não cole os comandos diretamente no Prompt de Comando clássico.

### 4.2 Use Docker para os parsers

Cada parser possui dependências grandes e potencialmente incompatíveis. Docker mantém PyMuPDF, Docling, MinerU e PaddleOCR em ambientes separados. Isso reduz conflitos e melhora a reprodutibilidade.

### 4.3 Nem todo parser possui uma pasta de modelos no host

PyMuPDF não usa uma pasta `models/pymupdf` neste projeto. Tesseract, RapidOCR, ONNX Runtime e as bibliotecas de layout são preparados na imagem Docker.

Os modelos persistidos no host são:

```text
models/
├── docling/
│   └── docling/models/
├── mineru/
│   ├── huggingface/
│   └── mineru.json
└── paddleocr/
    └── official_models/
```

Não crie uma pasta de modelos fictícia para PyMuPDF apenas para deixar a estrutura simétrica.

### 4.4 Downloads não fazem parte da medição

Primeiro as imagens e os modelos são preparados. Somente depois os comandos formais são executados. Tempo de download, instalação ou criação inicial do cache não deve ser interpretado como tempo do parser.

### 4.5 Resultados reproduzidos ficam separados

A branch contém um snapshot oficial em `outputs/`. Este guia grava a nova execução em:

```text
outputs/reproduction/
```

Isso impede que o experimento local sobrescreva os resultados oficiais.

---

# Parte I — Preparação da máquina e do repositório

## Passo 1 — Abrir o terminal correto

**Objetivo:** garantir que os comandos sejam executados em Bash.

Execute:

```bash
echo "$SHELL"
uname -a
```

**Explicação:**

- `echo "$SHELL"` mostra o shell padrão;
- `uname -a` mostra kernel e arquitetura;
- em WSL2, a linha normalmente contém `microsoft-standard-WSL2`.

**Resultado esperado:** uma linha contendo algo como `/bin/bash` e outra identificando Linux ou WSL2.

**Divergência:** se estiver em PowerShell ou `cmd.exe`, abra o WSL2. Se estiver em Linux com outro shell, inicie Bash com `bash`.

---

## Passo 2 — Verificar o Git

Execute:

```bash
git --version
```

**Explicação:** `git` será usado para clonar o repositório e registrar o commit reproduzido.

**Resultado esperado:**

```text
git version 2.x.x
```

A versão exata pode ser diferente.

**Divergência:** se aparecer `command not found`, o Git precisa ser instalado antes de continuar.

---

## Passo 3 — Verificar o cliente e o servidor Docker

Execute:

```bash
docker version
```

**Explicação:** o comando consulta duas partes:

- `Client`: programa usado no terminal;
- `Server`: Docker Engine que cria e executa contêineres.

**Resultado esperado:** seções `Client` e `Server`, sem erro de conexão.

**Divergências comuns:**

- `Cannot connect to the Docker daemon`: inicie o Docker Desktop ou o Docker Engine;
- apenas `Client`: o serviço Docker não está acessível;
- em WSL2: habilite a integração da distribuição no Docker Desktop.

---

## Passo 4 — Verificar o Docker Compose

Execute:

```bash
docker compose version
```

**Resultado esperado:**

```text
Docker Compose version v2.x.x
```

O projeto usa `docker compose` com espaço. O comando antigo `docker-compose` não é necessário.

---

## Passo 5 — Confirmar que o Docker consegue executar um contêiner

Execute:

```bash
docker run --rm hello-world
```

**Argumentos:**

- `run`: cria e executa um contêiner;
- `--rm`: remove o contêiner depois do teste;
- `hello-world`: imagem mínima usada para validar o Docker.

**Resultado esperado:** texto contendo:

```text
Hello from Docker!
```

Na primeira execução, o Docker pode baixar essa pequena imagem. Isso não faz parte do benchmark.

---

## Passo 6 — Conferir CPU, memória e disco

Execute:

```bash
nproc
free -h
df -h .
docker info --format 'CPUs={{.NCPU}} DockerMemoryBytes={{.MemTotal}}'
```

**Explicação:**

- `nproc`: CPUs lógicas visíveis ao Linux;
- `free -h`: memória total e disponível;
- `df -h .`: espaço livre no disco atual;
- `docker info --format`: CPUs e memória visíveis ao Docker.

**Resultado esperado:** valores não vazios e espaço suficiente.

**Recomendação prática:**

- 16 GB de RAM no host;
- pelo menos 10 a 12 GB disponíveis ao Docker;
- 30 GB ou mais de espaço livre antes de baixar imagens e modelos.

Esses valores são recomendações, não uma validação codificada. O PaddleOCR atingiu cerca de 6,2 GB de RSS na execução de referência, além do consumo do sistema e do Docker.

---

## Passo 7 — Escolher uma pasta de trabalho

Exemplo:

```bash
mkdir -p ~/workspace
cd ~/workspace
pwd
```

**Argumentos:**

- `mkdir -p`: cria a pasta e não falha se ela já existir;
- `cd`: entra na pasta;
- `pwd`: imprime o caminho atual.

**Resultado esperado:** caminho terminando em `/workspace`.

---

## Passo 8 — Clonar a branch do benchmark

Execute:

```bash
git clone \
  --branch milestone/mvp-ocr-auto-v2 \
  --single-branch \
  https://github.com/victorperone/document-ai-benchmark.git
```

**Argumentos:**

- `clone`: copia o repositório;
- `--branch milestone/mvp-ocr-auto-v2`: seleciona a branch usada no experimento;
- `--single-branch`: baixa somente o histórico necessário dessa branch;
- a última linha é a origem pública do repositório.

**Resultado esperado:** linhas de progresso e uma pasta `document-ai-benchmark`.

**Divergência:** se a pasta já existir, não clone por cima dela. Renomeie a pasta antiga ou execute o guia em outro diretório.

---

## Passo 9 — Entrar no repositório

Execute:

```bash
cd document-ai-benchmark
pwd
```

**Resultado esperado:** caminho terminando em `/document-ai-benchmark`.

Todos os comandos seguintes, salvo indicação explícita, são executados nessa pasta.

---

## Passo 10 — Confirmar branch, commit e estado do Git

Execute:

```bash
git branch --show-current
git log -1 --oneline
git status --short
```

**Resultado esperado:**

- branch: `milestone/mvp-ocr-auto-v2`;
- uma linha com hash e mensagem do commit atual;
- `git status --short` sem saída.

Salve o hash mostrado. Ele identifica exatamente o código reproduzido.

**Divergência:** arquivos modificados logo após o clone indicam problema no checkout ou ferramenta externa alterando arquivos. Não continue até entender a causa.

---

## Passo 11 — Inspecionar a estrutura principal

Execute:

```bash
find . -maxdepth 2 -type d | sort
```

**Resultado esperado:** diretórios como:

```text
./config
./data
./docker
./docs
./notebooks
./outputs
./scripts
./src
```

---

## Passo 12 — Validar o JSON de configuração

Execute:

```bash
python3 -m json.tool \
  config/benchmark_profiles.json \
  >/dev/null \
  && echo "CONFIG JSON: OK"
```

**Argumentos:**

- `python3 -m json.tool`: interpreta o arquivo como JSON;
- `>/dev/null`: descarta a impressão formatada;
- `&&`: executa o próximo comando somente se o JSON for válido.

**Resultado esperado:**

```text
CONFIG JSON: OK
```

---

## Passo 13 — Validar o arquivo Compose

Execute:

```bash
docker compose config >/dev/null \
  && echo "COMPOSE CONFIG: OK"
```

**Resultado esperado:**

```text
COMPOSE CONFIG: OK
```

Esse teste valida sintaxe, serviços, volumes e caminhos do `compose.yaml`.

---

## Passo 14 — Conferir os quatro serviços

Execute:

```bash
docker compose config --services
```

**Resultado esperado:**

```text
pymupdf
docling
mineru
paddleocr
```

A ordem pode variar, mas os quatro nomes devem aparecer.

---

## Passo 15 — Validar o PDF controlado

Execute:

```bash
sha256sum \
  data/benchmark/controlled/benchmark_controlado_v1.pdf
```

**Resultado esperado:**

```text
8089a3e142f9e8bcc5b92e5b2cc5313ff9be41ef5f2947aae69984ee07a749f7  data/benchmark/controlled/benchmark_controlado_v1.pdf
```

**Importância:** todos os parsers precisam receber exatamente os mesmos bytes. Se o hash for diferente, a comparação não reproduz o snapshot oficial.

---

## Passo 16 — Criar pastas persistentes e conferir permissões

Execute:

```bash
mkdir -p \
  models/docling \
  models/mineru/huggingface \
  models/paddleocr

id -u
ls -ld models outputs
```

**Resultado esperado:**

- as pastas existem;
- `id -u` costuma mostrar `1000` em WSL2/Linux;
- o usuário atual possui permissão de escrita.

**Divergência `Permission denied`:** ajuste apenas se necessário:

```bash
sudo chown -R 1000:1000 models outputs
```

Esse comando transfere a propriedade para o UID usado pelos contêineres do projeto. Não o execute sem necessidade.

---

## Passo 17 — Registrar o ambiente antes da execução

Execute:

```bash
{
  echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "BRANCH=$(git branch --show-current)"
  echo "COMMIT=$(git rev-parse HEAD)"
  echo "KERNEL=$(uname -a)"
  echo "CPUS=$(nproc)"
  free -h
  docker version
  docker compose version
} > /tmp/document_ai_environment_preflight.txt

cat /tmp/document_ai_environment_preflight.txt
```

**Resultado esperado:** arquivo temporário com data, branch, commit, kernel, CPUs, memória e versões do Docker. O manifesto definitivo será gravado depois que a pasta limpa de reprodução for criada.

---

# Parte II — Construção das imagens Docker

## Passo 18 — Construir as quatro imagens

Execute:

```bash
docker compose build \
  && echo "DOCKER IMAGES BUILD: OK"
```

**O que acontece:**

- PyMuPDF instala PyMuPDF4LLM, RapidOCR, ONNX Runtime, Tesseract e idiomas;
- Docling instala Docling e dependências;
- MinerU instala MinerU e PyTorch CPU;
- PaddleOCR instala PaddlePaddle CPU e PaddleOCR.

A primeira construção pode levar vários minutos e baixar muitos pacotes.

**Resultado esperado:** última linha:

```text
DOCKER IMAGES BUILD: OK
```

**Divergências:**

- erro de rede: verifique proxy, certificados e acesso aos repositórios de pacotes;
- `no space left on device`: libere espaço e confira `docker system df`;
- encerramento abrupto: verifique memória disponível ao Docker.

---

## Passo 19 — Listar as imagens construídas

Execute:

```bash
docker compose images
```

**Resultado esperado:** uma linha para cada serviço, com repository, tag, image ID e tamanho.

---

## Passo 20 — Testar o carregamento dos quatro adaptadores v2

Execute:

```bash
for spec in \
  "pymupdf:/app/src/parsers/pymupdf_v2.py" \
  "docling:/app/src/parsers/docling_v2.py" \
  "mineru:/app/src/parsers/mineru_v2.py" \
  "paddleocr:/app/src/parsers/paddleocr_v2.py"
do
  service="${spec%%:*}"
  script="${spec#*:}"

  docker compose run --rm -T \
    -e PYTHONPATH=/app \
    --entrypoint python \
    "$service" \
    "$script" \
    --help >/dev/null \
    || exit 1

  echo "$service adapter import: OK"
done
```

**Argumentos principais:**

- `docker compose run`: executa um contêiner temporário;
- `--rm`: remove o contêiner ao terminar;
- `-T`: não cria terminal virtual, tornando a saída mais estável;
- `-e PYTHONPATH=/app`: permite importar `src.*`;
- `--entrypoint python`: substitui o entrypoint legado do serviço;
- `--help`: carrega o adaptador e imprime a CLI sem processar PDF;
- `>/dev/null`: descarta o texto de ajuda.

**Resultado esperado:** quatro linhas terminando em `adapter import: OK`.

---

# Parte III — Preparação dos modelos locais

## Passo 21 — Verificar o ambiente PyMuPDF e Tesseract

PyMuPDF não precisa de download separado para `models/`. Execute:

```bash
docker compose run --rm -T \
  --entrypoint sh \
  pymupdf \
  -lc '
set -eu

python -c "import importlib.metadata as m; \
print(\"pymupdf4llm=\" + m.version(\"pymupdf4llm\")); \
print(\"rapidocr=\" + m.version(\"rapidocr\")); \
print(\"onnxruntime=\" + m.version(\"onnxruntime\"))"

tesseract --version | head -n 1
tesseract --list-langs | grep -x por

echo "PYMUPDF ENVIRONMENT: OK"
'
```

**Resultado esperado:** versões instaladas, `tesseract 5.5.0`, idioma `por` e:

```text
PYMUPDF ENVIRONMENT: OK
```

---

## Passo 22 — Baixar os modelos do Docling

Execute antes de qualquer medição Docling:

```bash
docker compose run --rm -T \
  --entrypoint sh \
  docling \
  -lc '
set -eu

docling-tools models download \
  --output-dir /home/appuser/.cache/docling/models \
  --rapidocr-backend-lang torch:pt \
  layout \
  tableformer \
  rapidocr

echo "DOCLING MODEL DOWNLOAD: OK"
'
```

**Argumentos:**

- `models download`: subcomando de download do Docling;
- `--output-dir`: destino dentro do contêiner;
- `--rapidocr-backend-lang torch:pt`: backend Torch e idioma português;
- `layout`: modelos de layout;
- `tableformer`: modelos de estrutura tabular;
- `rapidocr`: modelos OCR.

O volume do Compose mapeia `/home/appuser/.cache` para `models/docling` no host. Por isso o conteúdo costuma aparecer em:

```text
models/docling/docling/models/
```

**Resultado esperado:** logs de download ou confirmação de cache e a linha:

```text
DOCLING MODEL DOWNLOAD: OK
```

---

## Passo 23 — Verificar modelos e versão do Docling

Execute:

```bash
docker compose run --rm -T \
  --entrypoint sh \
  docling \
  -lc '
set -eu

test -d /home/appuser/.cache/docling/models
find /home/appuser/.cache/docling/models \
  -mindepth 1 -maxdepth 2 | head -n 20

python -c "import importlib.metadata as m; \
print(\"docling=\" + m.version(\"docling\")); \
print(\"docling-core=\" + m.version(\"docling-core\"))"

echo "DOCLING MODEL CHECK: OK"
'
```

**Resultado esperado:** caminhos de modelos, versões e:

```text
DOCLING MODEL CHECK: OK
```

---

## Passo 24 — Baixar os modelos pipeline do MinerU

Execute:

```bash
docker compose run --rm -T \
  --entrypoint sh \
  mineru \
  -lc '
set -eu

mineru-models-download \
  -s huggingface \
  -m pipeline

test -f /models/mineru/mineru.json

echo "MINERU MODEL DOWNLOAD: OK"
'
```

**Argumentos:**

- `mineru-models-download`: ferramenta oficial de preparação de modelos;
- `-s huggingface`: usa Hugging Face como fonte de download;
- `-m pipeline`: baixa somente os modelos do pipeline usado no benchmark, não o conjunto VLM;
- `test -f`: falha se o arquivo de configuração não foi criado.

O Compose define:

```text
MINERU_MODEL_SOURCE=local
MINERU_TOOLS_CONFIG_JSON=/models/mineru/mineru.json
HF_HOME=/models/mineru/huggingface
```

Assim os dados permanecem em `models/mineru` no host e são reutilizados nas execuções posteriores.

**Resultado esperado:** logs dos modelos e:

```text
MINERU MODEL DOWNLOAD: OK
```

---

## Passo 25 — Verificar o cache do MinerU

Execute:

```bash
docker compose run --rm -T \
  --entrypoint sh \
  mineru \
  -lc '
set -eu

test -f /models/mineru/mineru.json
test -d /models/mineru/huggingface

python -c "import importlib.metadata as m; \
print(\"mineru=\" + m.version(\"mineru\")); \
print(\"torch=\" + m.version(\"torch\"))"

python -m json.tool \
  /models/mineru/mineru.json >/dev/null

echo "MINERU MODEL CHECK: OK"
'
```

**Resultado esperado:** versões e:

```text
MINERU MODEL CHECK: OK
```

---

## Passo 26 — Pré baixar os modelos do PaddleOCR

O adaptador exige 12 diretórios de modelos locais. O comando abaixo instancia o mesmo conjunto usado pelo perfil `mvp_structured`, fazendo o download somente se os modelos ainda não estiverem no volume persistente.

Execute:

```bash
docker compose run --rm -T \
  --entrypoint python \
  paddleocr - <<'PY'
from paddleocr import PPStructureV3

PPStructureV3(
    layout_detection_model_name="PP-DocLayout_plus-L",
    region_detection_model_name="PP-DocBlockLayout",
    doc_orientation_classify_model_name="PP-LCNet_x1_0_doc_ori",
    text_detection_model_name="PP-OCRv5_server_det",
    textline_orientation_model_name="PP-LCNet_x1_0_textline_ori",
    text_recognition_model_name="PP-OCRv5_server_rec",
    table_classification_model_name="PP-LCNet_x1_0_table_cls",
    wired_table_structure_recognition_model_name="SLANeXt_wired",
    wireless_table_structure_recognition_model_name="SLANet_plus",
    wired_table_cells_detection_model_name="RT-DETR-L_wired_table_cell_det",
    wireless_table_cells_detection_model_name="RT-DETR-L_wireless_table_cell_det",
    table_orientation_classify_model_name="PP-LCNet_x1_0_doc_ori",
    formula_recognition_model_name="PP-FormulaNet_plus-L",
    use_doc_orientation_classify=True,
    use_doc_unwarping=False,
    use_textline_orientation=True,
    use_seal_recognition=False,
    use_table_recognition=True,
    use_formula_recognition=True,
    use_chart_recognition=False,
    use_region_detection=True,
)

print("PADDLEOCR MODEL DOWNLOAD: OK")
PY
```

**Como funciona:** o serviço monta `models/paddleocr` em `/home/appuser/.paddlex`. O PaddleX guarda modelos oficiais em `/home/appuser/.paddlex/official_models`, que corresponde a:

```text
models/paddleocr/official_models/
```

**Resultado esperado:** logs de obtenção ou carregamento dos modelos e:

```text
PADDLEOCR MODEL DOWNLOAD: OK
```

Esse passo pode ser o mais demorado e consumir bastante disco.

---

## Passo 27 — Verificar todos os modelos do PaddleOCR

Execute:

```bash
docker compose run --rm -T \
  --entrypoint sh \
  paddleocr \
  -lc '
set -eu

root=/home/appuser/.paddlex/official_models

for model in \
  PP-DocLayout_plus-L \
  PP-DocBlockLayout \
  PP-LCNet_x1_0_doc_ori \
  PP-OCRv5_server_det \
  PP-LCNet_x1_0_textline_ori \
  PP-OCRv5_server_rec \
  PP-LCNet_x1_0_table_cls \
  SLANeXt_wired \
  SLANet_plus \
  RT-DETR-L_wired_table_cell_det \
  RT-DETR-L_wireless_table_cell_det \
  PP-FormulaNet_plus-L
do
  test -d "$root/$model" \
    || { echo "MISSING: $model"; exit 1; }
done

python -c "import importlib.metadata as m; \
print(\"paddleocr=\" + m.version(\"paddleocr\")); \
print(\"paddlepaddle=\" + m.version(\"paddlepaddle\")); \
print(\"paddlex=\" + m.version(\"paddlex\"))"

echo "PADDLEOCR MODEL CHECK: OK"
'
```

**Resultado esperado:** versões e:

```text
PADDLEOCR MODEL CHECK: OK
```

Se aparecer `MISSING`, repita o Passo 26 e examine o primeiro erro de download.

---

## Passo 28 — Conferir o espaço ocupado pelos modelos

Execute:

```bash
du -sh models/*
```

**Resultado esperado:** três linhas não vazias para Docling, MinerU e PaddleOCR. Os tamanhos exatos variam.

Salve essa saída se o objetivo inclui documentar custo de armazenamento.

---

# Parte IV — Preparação da execução reproduzida

## Passo 29 — Preservar uma reprodução anterior

Execute:

```bash
if [ -d outputs/reproduction ] \
  && [ -n "$(find outputs/reproduction -mindepth 1 -maxdepth 1 2>/dev/null)" ]
then
  backup="outputs/reproduction_backup_$(date +%Y%m%d_%H%M%S)"
  mv outputs/reproduction "$backup"
  echo "Previous reproduction moved to: $backup"
fi

mkdir -p \
  outputs/reproduction/_logs \
  outputs/reproduction/_environment

echo "REPRODUCTION DIRECTORY: READY"
```

**Resultado esperado:**

```text
REPRODUCTION DIRECTORY: READY
```

Se existiam resultados anteriores, o caminho do backup também é mostrado. Nada é apagado.

---

## Passo 30 — Registrar novamente o ambiente no diretório novo

Execute:

```bash
{
  echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "BRANCH=$(git branch --show-current)"
  echo "COMMIT=$(git rev-parse HEAD)"
  echo "KERNEL=$(uname -a)"
  echo "CPUS=$(nproc)"
  free -h
  docker version
  docker compose version
  docker compose images
  du -sh models/*
} > outputs/reproduction/_environment/environment.txt

head -n 10 outputs/reproduction/_environment/environment.txt
```

**Resultado esperado:** primeiras linhas do manifesto do ambiente.

---

## Passo 31 — Gerar o Source Inventory fora da medição dos parsers

Execute:

```bash
docker compose run --rm -T \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/scripts/build_source_inventory.py \
  --input-dir /data/benchmark/controlled \
  --output-dir /outputs/reproduction/_source_inventory \
  --only benchmark_controlado_v1.pdf
```

**Argumentos:**

- `--input-dir`: diretório do PDF dentro do contêiner;
- `--output-dir`: pasta do inventário reproduzido;
- `--only`: limita a descoberta ao documento controlado.

**Resultado esperado:** aproximadamente:

```text
Documents found: 1
[1/1] benchmark_controlado_v1.pdf
  pages: 12
  native coverage: 100.00%
  embedded images: 3
  output: /outputs/reproduction/_source_inventory/benchmark_controlado_v1.json
```

O tempo do inventário não deve ser somado ao tempo de nenhum parser.

---

## Passo 32 — Validar o inventário

Execute:

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path(
    "outputs/reproduction/_source_inventory/"
    "benchmark_controlado_v1.json"
)

data = json.loads(path.read_text(encoding="utf-8"))

assert data["file"] == "benchmark_controlado_v1.pdf"
assert data["sha256"] == (
    "8089a3e142f9e8bcc5b92e5b2cc5313f"
    "f9be41ef5f2947aae69984ee07a749f7"
)
assert data["pages"] == 12
assert len(data["per_page"]) == 12
assert data["images"]["embedded_image_occurrences"] == 3

print("SOURCE INVENTORY VALIDATION: OK")
PY
```

**Resultado esperado:**

```text
SOURCE INVENTORY VALIDATION: OK
```

---

# Parte V — Condições para a medição formal

## Passo 33 — Evitar interferência externa

Antes de cada parser:

1. feche aplicações pesadas;
2. não execute dois parsers ao mesmo tempo;
3. não execute atualização do sistema ou cópia grande de arquivos;
4. confirme que nenhum contêiner antigo do benchmark ficou ativo;
5. use os modelos já preparados;
6. aguarde o sistema ficar ocioso se acabou de baixar ou descompactar modelos.

Confira contêineres ativos:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

**Resultado esperado:** nenhum contêiner do benchmark em execução. Outros contêineres do usuário devem ser avaliados e, se consumirem recursos, interrompidos antes da medição.

---

## Passo 34 — Entender os argumentos comuns dos parsers

Os quatro comandos formais usam:

- `--input`: PDF dentro do contêiner;
- `--output-root`: raiz que receberá inventário e resultados;
- `--profile`: configuração central do parser;
- `--artifacts all`: grava os seis artefatos;
- `--verbose`: mostra progresso e preserva mensagens no log;
- `PYTHONPATH=/app`: habilita imports do projeto;
- `--entrypoint python`: ignora o entrypoint de baseline do Compose e usa o adaptador v2.

Não troque perfis silenciosamente. Uma mudança de perfil altera o workload e invalida a comparação direta.

---

# Parte VI — Execução dos quatro parsers

## Passo 35 — Executar PyMuPDF4LLM

Execute:

```bash
docker compose run --rm -T \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/src/parsers/pymupdf_v2.py \
  --input /data/benchmark/controlled/benchmark_controlado_v1.pdf \
  --output-root /outputs/reproduction \
  --profile ocr_auto_rapidtess \
  --artifacts all \
  --verbose \
  && test -f \
    outputs/reproduction/pymupdf/benchmark_controlado_v1/ocr_auto_rapidtess/metrics.json \
  && echo "PYMUPDF FORMAL RUN: OK"
```

**Resultado esperado ao final:**

```text
PYMUPDF FORMAL RUN: OK
```

A execução de referência processou 12/12 páginas, solicitou OCR nas páginas 9, 10 e 11 e não registrou falha.

**Divergência:** se falhar, examine:

```bash
tail -n 100 \
  outputs/reproduction/pymupdf/benchmark_controlado_v1/ocr_auto_rapidtess/run.log
```

---

## Passo 36 — Validar rapidamente PyMuPDF

Execute:

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path(
    "outputs/reproduction/pymupdf/benchmark_controlado_v1/"
    "ocr_auto_rapidtess/metrics.json"
)
m = json.loads(p.read_text(encoding="utf-8"))

assert m["processing"]["pages_processed"] == 12
assert m["processing"]["failed_pages"] == 0
assert m["processing"]["ocr"]["requested_page_numbers"] == [9, 10, 11]
assert m["processing"]["errors_count"] == 0

print("PYMUPDF QUICK VALIDATION: OK")
PY
```

**Resultado esperado:**

```text
PYMUPDF QUICK VALIDATION: OK
```

---

## Passo 37 — Executar Docling

Execute:

```bash
docker compose run --rm -T \
  -e PYTHONPATH=/app \
  --entrypoint python \
  docling \
  /app/src/parsers/docling_v2.py \
  --input /data/benchmark/controlled/benchmark_controlado_v1.pdf \
  --output-root /outputs/reproduction \
  --profile ocr_auto \
  --artifacts all \
  --verbose \
  && test -f \
    outputs/reproduction/docling/benchmark_controlado_v1/ocr_auto/metrics.json \
  && echo "DOCLING FORMAL RUN: OK"
```

**Resultado esperado:**

```text
DOCLING FORMAL RUN: OK
```

O perfil usa OCR document aware, RapidOCR, português, tabelas em modo preciso, CPU e modelos locais. Avisos de depreciação podem aparecer sem significar falha.

**Divergência de modelos:** se a mensagem indicar diretório inexistente, repita os Passos 22 e 23.

---

## Passo 38 — Validar rapidamente Docling

Execute:

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path(
    "outputs/reproduction/docling/benchmark_controlado_v1/"
    "ocr_auto/metrics.json"
)
m = json.loads(p.read_text(encoding="utf-8"))

assert m["processing"]["pages_processed"] == 12
assert m["processing"]["failed_pages"] == 0
assert m["processing"]["conversion_status"] == "success"
assert m["processing"]["errors_count"] == 0

print("DOCLING QUICK VALIDATION: OK")
PY
```

**Resultado esperado:**

```text
DOCLING QUICK VALIDATION: OK
```

Os contadores de páginas OCR podem ser `null`. Isso significa indisponível, não zero.

---

## Passo 39 — Executar MinerU

Execute:

```bash
docker compose run --rm -T \
  -e PYTHONPATH=/app \
  --entrypoint python \
  mineru \
  /app/src/parsers/mineru_v2.py \
  --input /data/benchmark/controlled/benchmark_controlado_v1.pdf \
  --output-root /outputs/reproduction \
  --profile auto \
  --artifacts all \
  --verbose \
  && test -f \
    outputs/reproduction/mineru/benchmark_controlado_v1/auto/metrics.json \
  && echo "MINERU FORMAL RUN: OK"
```

**Resultado esperado:**

```text
MINERU FORMAL RUN: OK
```

O perfil usa backend `pipeline` e método `auto`. O adaptador cria dados nativos temporários, converte o resultado para o contrato comum e remove os intermediários ao final.

**Divergência de cache:** confirme `models/mineru/mineru.json`, a pasta `models/mineru/huggingface` e as variáveis do serviço Compose.

---

## Passo 40 — Validar rapidamente MinerU

Execute:

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path(
    "outputs/reproduction/mineru/benchmark_controlado_v1/"
    "auto/metrics.json"
)
m = json.loads(p.read_text(encoding="utf-8"))

assert m["processing"]["pages_processed"] == 12
assert m["processing"]["failed_pages"] == 0
assert m["processing"]["conversion_status"] == "success"
assert m["processing"]["errors_count"] == 0

print("MINERU QUICK VALIDATION: OK")
PY
```

**Resultado esperado:**

```text
MINERU QUICK VALIDATION: OK
```

Contadores de OCR por página podem ser `null`, porque a API do modo `auto` não expõe um callback estável no adaptador.

---

## Passo 41 — Executar PaddleOCR / PPStructureV3

Execute:

```bash
docker compose run --rm -T \
  -e PYTHONPATH=/app \
  --entrypoint python \
  paddleocr \
  /app/src/parsers/paddleocr_v2.py \
  --input /data/benchmark/controlled/benchmark_controlado_v1.pdf \
  --output-root /outputs/reproduction \
  --profile mvp_structured \
  --artifacts all \
  --verbose \
  && test -f \
    outputs/reproduction/paddleocr/benchmark_controlado_v1/mvp_structured/metrics.json \
  && echo "PADDLEOCR FORMAL RUN: OK"
```

**Resultado esperado:**

```text
PADDLEOCR FORMAL RUN: OK
```

Esse é normalmente o job mais demorado e com maior uso de RAM. O perfil habilita OCR, tabelas, fórmulas, orientação do documento, orientação das linhas e detecção de regiões. Gráficos, unwarping e selos ficam desabilitados.

**Divergência `Required local PaddleOCR models are missing`:** volte ao Passo 27 e identifique o diretório ausente.

**Divergência `Killed` ou código 137:** o processo provavelmente ficou sem memória. Aumente a memória disponível ao Docker e repita apenas esse job.

---

## Passo 42 — Validar rapidamente PaddleOCR

Execute:

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path(
    "outputs/reproduction/paddleocr/benchmark_controlado_v1/"
    "mvp_structured/metrics.json"
)
m = json.loads(p.read_text(encoding="utf-8"))

assert m["processing"]["pages_processed"] == 12
assert m["processing"]["failed_pages"] == 0
assert m["processing"]["conversion_status"] == "success"
assert m["processing"]["errors_count"] == 0
assert m["processing"]["ocr"]["pages_processed"] == 12

print("PADDLEOCR QUICK VALIDATION: OK")
PY
```

**Resultado esperado:**

```text
PADDLEOCR QUICK VALIDATION: OK
```

---

# Parte VII — Validação comum dos resultados

## Passo 43 — Conferir a árvore de artefatos

Execute:

```bash
find outputs/reproduction \
  -maxdepth 5 \
  -type f \
  | sort
```

Cada parser deve possuir:

```text
raw.md
document.md
document.jsonl
metrics.json
removed_content.jsonl
run.log
```

O arquivo `removed_content.jsonl` pode ter tamanho zero quando o normalizador não remove conteúdo, mas precisa existir.

---

## Passo 44 — Validar presença, JSONL e contrato comum

Execute:

```bash
python3 - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("outputs/reproduction")
DOC = "benchmark_controlado_v1"
EXPECTED_SHA = (
    "8089a3e142f9e8bcc5b92e5b2cc5313f"
    "f9be41ef5f2947aae69984ee07a749f7"
)

JOBS = {
    "PyMuPDF": ROOT / "pymupdf" / DOC / "ocr_auto_rapidtess",
    "Docling": ROOT / "docling" / DOC / "ocr_auto",
    "MinerU": ROOT / "mineru" / DOC / "auto",
    "PaddleOCR": ROOT / "paddleocr" / DOC / "mvp_structured",
}

ARTIFACTS = (
    "raw.md",
    "document.md",
    "document.jsonl",
    "metrics.json",
    "removed_content.jsonl",
    "run.log",
)

normalization_configs = set()
monitor_intervals = set()

for label, job in JOBS.items():
    for name in ARTIFACTS:
        path = job / name
        assert path.is_file(), f"{label}: missing {path}"

    metrics = json.loads(
        (job / "metrics.json").read_text(encoding="utf-8")
    )

    records = [
        json.loads(line)
        for line in (job / "document.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    assert metrics["benchmark"]["schema_version"] == 2
    assert metrics["benchmark"]["reference_tokenizer"] == "o200k_base"
    assert metrics["document"]["sha256"] == EXPECTED_SHA
    assert metrics["document"]["pages"] == 12
    assert metrics["processing"]["pages_total"] == 12
    assert metrics["processing"]["pages_processed"] == 12
    assert metrics["processing"]["failed_pages"] == 0
    assert metrics["processing"]["errors_count"] == 0
    assert metrics["resources"]["monitor_version"] == "process_tree_v2"
    assert len(records) == 12
    assert [r["page_number"] for r in records] == list(range(1, 13))

    normalization_configs.add(
        json.dumps(
            metrics["normalization"]["config"],
            sort_keys=True,
            ensure_ascii=False,
        )
    )

    monitor_intervals.add(
        metrics["resources"]["sampling_interval_seconds"]
    )

    print(f"{label}: PASS")

assert len(normalization_configs) == 1, "Normalization config differs"
assert len(monitor_intervals) == 1, "Monitor interval differs"

print("COMMON CONTRACT VALIDATION: PASS")
PY
```

**Resultado esperado:**

```text
PyMuPDF: PASS
Docling: PASS
MinerU: PASS
PaddleOCR: PASS
COMMON CONTRACT VALIDATION: PASS
```

---

## Passo 45 — Gerar um resumo operacional no terminal

Execute:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path("outputs/reproduction")
doc = "benchmark_controlado_v1"

jobs = {
    "PyMuPDF": root / "pymupdf" / doc / "ocr_auto_rapidtess",
    "Docling": root / "docling" / doc / "ocr_auto",
    "MinerU": root / "mineru" / doc / "auto",
    "PaddleOCR": root / "paddleocr" / doc / "mvp_structured",
}

header = (
    f"{'Parser':<12} {'Seconds':>10} {'Peak MB':>10} "
    f"{'Read MB':>10} {'Write MB':>10} {'Tokens':>10}"
)

print(header)
print("-" * len(header))

for label, path in jobs.items():
    m = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
    print(
        f"{label:<12} "
        f"{m['processing']['pipeline_seconds']:>10.3f} "
        f"{m['resources']['peak_rss_mb']:>10.1f} "
        f"{m['resources']['disk_read_mb']:>10.1f} "
        f"{m['resources']['disk_write_mb']:>10.1f} "
        f"{m['tokens']['reference']['clean_markdown_tokens']:>10d}"
    )
PY
```

**Resultado esperado:** tabela com quatro linhas. Os números de desempenho podem diferir da referência.

---

## Passo 46 — Comparar com o snapshot oficial sem exigir igualdade de desempenho

Use esta referência:

```text
PyMuPDF    8.15 s    729 MB    59 MB lidos     4406 tokens
Docling   31.31 s   2999 MB   719 MB lidos     3730 tokens
MinerU    46.73 s   3240 MB  4365 MB lidos     6085 tokens
Paddle   116.28 s   6204 MB  2217 MB lidos     4666 tokens
```

Interprete assim:

- diferença de tempo ou RAM não significa falha;
- documento, schema, páginas, tokenizer, normalizador e monitor precisam coincidir;
- uma diferença grande de tokens exige revisar versões, perfil, modelos e Markdown;
- não conclua “melhor parser” usando apenas uma coluna.

---

## Passo 47 — Verificar se downloads apareceram durante os jobs formais

Execute:

```bash
for log in \
  outputs/reproduction/pymupdf/benchmark_controlado_v1/ocr_auto_rapidtess/run.log \
  outputs/reproduction/docling/benchmark_controlado_v1/ocr_auto/run.log \
  outputs/reproduction/mineru/benchmark_controlado_v1/auto/run.log \
  outputs/reproduction/paddleocr/benchmark_controlado_v1/mvp_structured/run.log
do
  echo "===== $log ====="
  grep -Ein \
    'downloading model|download model|huggingface.co|modelscope.cn|fetching model' \
    "$log" \
    || echo "No model-download signature found"
done
```

**Resultado esperado:** `No model-download signature found` para cada log.

Esse teste é uma heurística. A evidência principal é que os caches foram preparados e validados antes da execução.

---

## Passo 48 — Inspecionar o Markdown bruto e limpo

Exemplo PyMuPDF:

```bash
less \
  outputs/reproduction/pymupdf/benchmark_controlado_v1/ocr_auto_rapidtess/raw.md
```

Saia de `less` pressionando `q`.

Compare bruto e limpo:

```bash
diff -u \
  outputs/reproduction/pymupdf/benchmark_controlado_v1/ocr_auto_rapidtess/raw.md \
  outputs/reproduction/pymupdf/benchmark_controlado_v1/ocr_auto_rapidtess/document.md \
  | less
```

**Resultado esperado:** diferenças principalmente relacionadas a cabeçalhos e rodapés repetidos. `diff` pode encerrar com status 1 quando encontrou diferenças; isso é normal.

Repita substituindo o caminho para cada parser.

---

## Passo 49 — Auditar o conteúdo removido

Execute:

```bash
for file in \
  outputs/reproduction/pymupdf/benchmark_controlado_v1/ocr_auto_rapidtess/removed_content.jsonl \
  outputs/reproduction/docling/benchmark_controlado_v1/ocr_auto/removed_content.jsonl \
  outputs/reproduction/mineru/benchmark_controlado_v1/auto/removed_content.jsonl \
  outputs/reproduction/paddleocr/benchmark_controlado_v1/mvp_structured/removed_content.jsonl
do
  echo "===== $file ====="
  if [ -s "$file" ]; then
    head -n 20 "$file"
  else
    echo "<empty>"
  fi
done
```

**Resultado esperado:**

- PyMuPDF e MinerU normalmente apresentam registros removidos;
- Docling e PaddleOCR podem produzir arquivo vazio;
- nenhum conteúdo técnico importante deve ser removido silenciosamente.

---

## Passo 50 — Examinar as páginas críticas no JSONL

As páginas 2, 3, 4, 8, 9, 10, 11 e 12 são especialmente úteis.

Exemplo para imprimir o Markdown limpo da página 10 de cada parser:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path("outputs/reproduction")
doc = "benchmark_controlado_v1"

jobs = {
    "PyMuPDF": root / "pymupdf" / doc / "ocr_auto_rapidtess",
    "Docling": root / "docling" / doc / "ocr_auto",
    "MinerU": root / "mineru" / doc / "auto",
    "PaddleOCR": root / "paddleocr" / doc / "mvp_structured",
}

for label, job in jobs.items():
    records = [
        json.loads(line)
        for line in (job / "document.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    page = records[9]
    print("\n" + "=" * 20 + f" {label} PAGE 10 " + "=" * 20)
    print(page["clean_markdown"][:4000])
PY
```

**Resultado esperado:** quatro versões da página rotacionada. Avalie orientação, leitura das células e preservação dos valores.

Para outra página, altere `records[9]`: página N corresponde ao índice `N - 1`.

---

## Passo 51 — Entender as métricas que podem ser comparadas

Use como métricas comuns:

- `processing.pipeline_seconds`;
- `processing.pages_processed` e falhas;
- `resources.peak_rss_mb`;
- `resources.process_cpu_time_seconds`;
- `resources.disk_read_mb` e `disk_write_mb`;
- `tokens.reference.clean_markdown_tokens`;
- ruído de `heuristics.cleaned`;
- estruturas presentes em `content_elements.clean_markdown`;
- registros de normalização;
- artefatos por página.

Use com cuidado:

- `parser_output.tables_detected`;
- `parser_output.formulas_detected`;
- classes de layout nativas;
- número de páginas OCR quando o parser não expõe o contador.

Contagens nativas diferentes podem representar classificações diferentes do mesmo objeto.

---

# Parte VIII — Reprodução da análise no notebook

## Passo 52 — Verificar o Python local para o notebook

Execute:

```bash
python3 --version
```

**Resultado recomendado:** Python 3.12.x.

O processamento dos PDFs continua em Docker. O Python local é usado apenas para tabelas, gráficos e notebook.

---

## Passo 53 — Criar um ambiente virtual de análise

Execute:

```bash
python3 -m venv .venv-analysis
source .venv-analysis/bin/activate
python -m pip install --upgrade pip
```

**Argumentos:**

- `-m venv`: cria ambiente isolado;
- `.venv-analysis`: nome da pasta;
- `source .../activate`: ativa o ambiente;
- `python -m pip`: garante que o pip pertence ao Python ativo.

**Resultado esperado:** o prompt normalmente passa a mostrar `(.venv-analysis)`.

---

## Passo 54 — Instalar dependências do notebook

Execute:

```bash
python -m pip install \
  -r notebooks/requirements.txt

python -m pip install \
  jupyterlab \
  nbconvert

echo "NOTEBOOK ENVIRONMENT: OK"
```

**Resultado esperado:** instalações concluídas e:

```text
NOTEBOOK ENVIRONMENT: OK
```

As bibliotecas numéricas e gráficas estão fixadas em `notebooks/requirements.txt`. JupyterLab e nbconvert são ferramentas de interface e exportação.

---

## Passo 55 — Registrar o kernel

Execute:

```bash
python -m ipykernel install \
  --user \
  --name document-ai-benchmark \
  --display-name "Python (document-ai-benchmark)"
```

**Argumentos:**

- `--user`: registra somente para o usuário atual;
- `--name`: identificador interno;
- `--display-name`: nome mostrado no Jupyter.

**Resultado esperado:** mensagem informando instalação do kernelspec.

---

## Passo 56 — Criar uma cópia do notebook para a reprodução

Execute:

```bash
cp \
  notebooks/controlled_benchmark_analysis.ipynb \
  notebooks/controlled_benchmark_reproduction.ipynb

ls -lh notebooks/controlled_benchmark_reproduction.ipynb
```

**Resultado esperado:** o novo arquivo existe.

A cópia evita modificar o notebook oficial congelado.

---

## Passo 57 — Ajustar a cópia para ler `outputs/reproduction`

O notebook oficial lê o snapshot em `outputs/`. Abra a cópia e localize a célula que define:

```python
SOURCE_INVENTORY = ...
JOBS = {...}
```

Substitua a célula inteira por:

```python
REPO_ROOT = find_repo_root()

CONTROLLED_PDF = (
    REPO_ROOT
    / "data"
    / "benchmark"
    / "controlled"
    / "benchmark_controlado_v1.pdf"
)

OUTPUT_ROOT = (
    REPO_ROOT
    / "outputs"
    / "reproduction"
)

SOURCE_INVENTORY = (
    OUTPUT_ROOT
    / "_source_inventory"
    / "benchmark_controlado_v1.json"
)

JOBS = {
    "PyMuPDF": (
        OUTPUT_ROOT / "pymupdf" / "benchmark_controlado_v1"
        / "ocr_auto_rapidtess"
    ),
    "Docling": (
        OUTPUT_ROOT / "docling" / "benchmark_controlado_v1"
        / "ocr_auto"
    ),
    "MinerU": (
        OUTPUT_ROOT / "mineru" / "benchmark_controlado_v1"
        / "auto"
    ),
    "PaddleOCR": (
        OUTPUT_ROOT / "paddleocr" / "benchmark_controlado_v1"
        / "mvp_structured"
    ),
}

print("Repository root:", REPO_ROOT)
print("Controlled PDF:", CONTROLLED_PDF)
print("Output root:", OUTPUT_ROOT)
print("Jobs:", ", ".join(JOBS))
```

**Resultado esperado ao executar a célula:** `Output root` termina em `outputs/reproduction`.

❗ Não pule este passo. Caso contrário, o notebook analisará o snapshot oficial em vez da nova execução.

---

## Passo 58 — Iniciar o JupyterLab

Execute na raiz do repositório, com o ambiente virtual ativo:

```bash
jupyter lab
```

**Resultado esperado:** terminal mostra uma URL local com token, normalmente iniciada por:

```text
http://localhost:8888/lab?token=...
```

Abra a URL no navegador e selecione:

```text
notebooks/controlled_benchmark_reproduction.ipynb
```

Escolha o kernel:

```text
Python (document-ai-benchmark)
```

---

## Passo 59 — Executar todas as células

No JupyterLab, use:

```text
Run > Run All Cells
```

**Resultado esperado:**

- presença de artefatos: PASS;
- gate de comparabilidade: PASS;
- integridade de processamento: PASS;
- validação de rastreamento OCR: PASS para os contadores disponíveis;
- tabelas e gráficos preenchidos para quatro parsers;
- nenhuma exceção vermelha interrompendo o notebook.

Avisos podem aparecer sem invalidar a execução. Examine qualquer traceback.

---

## Passo 60 — Interpretar os gates do notebook

A sequência lógica do notebook é:

1. carregar artefatos;
2. validar invariantes compartilhadas;
3. validar integridade de páginas e erros;
4. descrever comportamento OCR sem inferir valores ausentes;
5. comparar tokens e normalização;
6. comparar tempo, CPU, memória e I/O;
7. comparar estrutura e ruído do Markdown;
8. aprofundar anomalias por página;
9. apresentar trade offs operacionais e limitações.

Um parser não deve avançar para comparação se documento, schema, páginas, tokenizer, monitor ou normalizador forem incompatíveis.

---

## Passo 61 — Exportar o notebook executado para HTML

Depois de salvar o notebook:

```bash
jupyter nbconvert \
  --to html \
  notebooks/controlled_benchmark_reproduction.ipynb \
  --output controlled_benchmark_reproduction.html
```

**Argumentos:**

- `nbconvert`: converte notebook;
- `--to html`: formato de saída;
- `--output`: nome do HTML.

**Resultado esperado:** mensagem contendo `Writing` e um arquivo HTML em `notebooks/`.

Confira:

```bash
ls -lh notebooks/controlled_benchmark_reproduction.html
```

---

# Parte IX — Arquivamento e evidência de reprodução

## Passo 62 — Salvar versões instaladas nos contêineres

Execute:

```bash
for service in pymupdf docling mineru paddleocr
do
  docker compose run --rm -T \
    --entrypoint python \
    "$service" \
    -m pip freeze \
    > "outputs/reproduction/_environment/${service}_pip_freeze.txt"
done

ls outputs/reproduction/_environment/*_pip_freeze.txt
```

**Resultado esperado:** quatro arquivos.

---

## Passo 63 — Criar checksums dos resultados

Execute:

```bash
find outputs/reproduction \
  -type f \
  ! -name checksums.sha256 \
  -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > outputs/reproduction/checksums.sha256

head outputs/reproduction/checksums.sha256
```

**Resultado esperado:** linhas com SHA-256 e caminhos.

---

## Passo 64 — Criar um arquivo compactado da reprodução

Execute:

```bash
tar -czf \
  controlled12_reproduction_$(date +%Y%m%d_%H%M%S).tar.gz \
  outputs/reproduction \
  notebooks/controlled_benchmark_reproduction.ipynb \
  notebooks/controlled_benchmark_reproduction.html
```

**Argumentos:**

- `tar`: cria arquivo;
- `-c`: criar;
- `-z`: compactar com gzip;
- `-f`: nome do arquivo;
- `$(date ...)`: adiciona timestamp.

**Resultado esperado:** arquivo `.tar.gz` na raiz do repositório.

---

## Passo 65 — Conferir o estado do Git

Execute:

```bash
git status --short
```

**Resultado esperado:**

- `outputs/reproduction` e `models` normalmente não aparecem porque são ignorados;
- a cópia do notebook e o HTML podem aparecer como arquivos novos.

Não execute `git add .` automaticamente. Resultados, modelos, PDFs e notebooks executados podem ser grandes ou conter dados que não devem ser versionados.

---

# Parte X — Repetição opcional para desempenho

## Passo 66 — Diferenciar reprodução funcional de benchmark estatístico

Uma execução por parser é suficiente para reproduzir o fluxo e o snapshot operacional. Para comparar desempenho com maior confiança, execute cada parser pelo menos três vezes em condições semelhantes e use a mediana.

Não sobrescreva os jobs anteriores. Use raízes diferentes, por exemplo:

```text
outputs/repetitions/run_01/
outputs/repetitions/run_02/
outputs/repetitions/run_03/
```

Cada raiz precisa de seu próprio `_source_inventory` ou de uma cópia validada do inventário.

A ordem dos parsers pode influenciar cache de disco e temperatura. Para estudo formal, documente a ordem ou alterne a sequência entre repetições.

---

# Parte XI — Solução de problemas

## Problema 1 — Docker daemon inacessível

**Sintoma:**

```text
Cannot connect to the Docker daemon
```

**Ação:** inicie Docker Desktop ou Docker Engine e repita `docker version`.

---

## Problema 2 — WSL2 não integrado ao Docker Desktop

**Sintoma:** `docker` funciona no Windows, mas não dentro da distribuição WSL.

**Ação:** habilite a distribuição em Docker Desktop > Settings > Resources > WSL Integration e reinicie o terminal WSL.

---

## Problema 3 — Sem espaço no Docker

Execute:

```bash
docker system df
df -h .
```

Não use `docker system prune -a` sem entender o impacto. Esse comando pode apagar imagens e caches usados por outros projetos.

---

## Problema 4 — Permissão negada em `models` ou `outputs`

Confira:

```bash
id
ls -ld models outputs
```

Se o host for Linux/WSL2 e os contêineres usarem UID 1000, corrija somente os diretórios do projeto:

```bash
sudo chown -R 1000:1000 models outputs
```

---

## Problema 5 — Docling não encontra modelos

Confira:

```bash
find models/docling -maxdepth 3 -type d | head -n 30
```

O caminho interno esperado é `/home/appuser/.cache/docling/models`. Repita os Passos 22 e 23.

---

## Problema 6 — MinerU não encontra `mineru.json`

Confira:

```bash
ls -l models/mineru/mineru.json
python3 -m json.tool models/mineru/mineru.json >/dev/null
```

Se faltar, repita o Passo 24. Não crie manualmente um JSON vazio.

---

## Problema 7 — PaddleOCR informa modelos ausentes

Execute novamente o Passo 27. O primeiro nome marcado como `MISSING` identifica o diretório necessário.

Não renomeie pastas aleatoriamente. Os nomes são parte da configuração congelada do adaptador.

---

## Problema 8 — `Source Inventory not found`

O inventário precisa estar na mesma raiz passada em `--output-root`:

```text
outputs/reproduction/_source_inventory/benchmark_controlado_v1.json
```

Repita os Passos 31 e 32.

---

## Problema 9 — `ModuleNotFoundError: No module named 'src'`

Confirme a presença de:

```text
-e PYTHONPATH=/app
```

nos comandos dos adaptadores.

---

## Problema 10 — PaddleOCR termina com `Killed` ou código 137

Isso geralmente indica falta de memória. Feche aplicações, aumente a memória do Docker e confirme `free -h` e `docker info` antes de repetir.

---

## Problema 11 — Tempos muito diferentes do snapshot

Verifique:

1. número de CPUs;
2. memória disponível;
3. tipo de disco;
4. outros processos;
5. cache de modelos;
6. downloads durante o job;
7. commit e imagens Docker;
8. temperatura e throttling.

Não altere o código para “forçar” o mesmo tempo.

---

## Problema 12 — Tokens diferentes

Confira, nesta ordem:

1. SHA-256 do PDF;
2. branch e commit;
3. perfil;
4. versões no `metrics.json`;
5. tokenizer `o200k_base`;
6. configuração de normalização;
7. modelos locais;
8. conteúdo de `raw.md` e `document.md`.

Uma diferença de token é um sinal para investigar conteúdo, não um motivo para editar manualmente `metrics.json`.

---

## Problema 13 — Notebook analisa o snapshot oficial

Confira a impressão da célula de configuração. Ela precisa mostrar:

```text
Output root: .../outputs/reproduction
```

Se mostrar apenas `.../outputs`, repita o Passo 57 na cópia do notebook.

---

## Problema 14 — Um arquivo `:Zone.Identifier` aparece

Esse é um metadado do Windows e não faz parte da análise. Não é necessário para executar o notebook. Evite criar novos arquivos desse tipo ao copiar entre Windows e WSL.

---

# Parte XII — Checklist final

A reprodução está tecnicamente completa quando todos os itens abaixo forem verdadeiros:

- [ ] branch `milestone/mvp-ocr-auto-v2` confirmada;
- [ ] hash do PDF igual a `8089a3e...a749f7`;
- [ ] Docker e Compose funcionando;
- [ ] quatro imagens construídas;
- [ ] adaptadores v2 carregando;
- [ ] modelos Docling presentes;
- [ ] cache e `mineru.json` presentes;
- [ ] 12 modelos PaddleOCR presentes;
- [ ] Source Inventory validado;
- [ ] PyMuPDF processou 12 páginas;
- [ ] Docling processou 12 páginas;
- [ ] MinerU processou 12 páginas;
- [ ] PaddleOCR processou 12 páginas;
- [ ] seis artefatos por parser;
- [ ] schema v2 em todos os `metrics.json`;
- [ ] tokenizer `o200k_base` em todos;
- [ ] monitor `process_tree_v2` em todos;
- [ ] normalização idêntica;
- [ ] zero página com falha;
- [ ] zero erro contabilizado;
- [ ] notebook apontando para `outputs/reproduction`;
- [ ] gates do notebook aprovados;
- [ ] resultados e ambiente arquivados.

---

# Apêndice A — Mapa de saída esperado

```text
outputs/reproduction/
├── _environment/
├── _logs/
├── _source_inventory/
│   └── benchmark_controlado_v1.json
├── pymupdf/
│   └── benchmark_controlado_v1/
│       └── ocr_auto_rapidtess/
├── docling/
│   └── benchmark_controlado_v1/
│       └── ocr_auto/
├── mineru/
│   └── benchmark_controlado_v1/
│       └── auto/
└── paddleocr/
    └── benchmark_controlado_v1/
        └── mvp_structured/
```

Cada diretório final contém:

```text
raw.md
document.md
document.jsonl
metrics.json
removed_content.jsonl
run.log
```

---

# Apêndice B — Significado dos seis artefatos

## `raw.md`

Representação textual mais próxima da saída do parser, antes da normalização comum.

## `document.md`

Markdown depois da normalização. É a representação candidata para chunking, recuperação e envio seletivo a LLMs.

## `document.jsonl`

Um registro por página, contendo Markdown bruto, Markdown limpo, elementos diagnósticos e metadados nativos.

## `metrics.json`

Métricas de identificação, documento, processamento, OCR, recursos, estrutura, ruído, tokens, normalização e saída.

## `removed_content.jsonl`

Auditoria de cada cabeçalho, rodapé ou outro registro removido pelo normalizador.

## `run.log`

Mensagens, avisos e erros emitidos durante a execução.

---

# Apêndice C — Perfis congelados nesta reprodução

## PyMuPDF — `ocr_auto_rapidtess`

- OCR habilitado;
- modo automático;
- engine RapidTess;
- idioma `por`;
- 150 DPI;
- layout habilitado;
- imagens não incorporadas ao Markdown.

## Docling — `ocr_auto`

- OCR document aware;
- RapidOCR com backend Torch;
- idioma português;
- escala 3.0;
- TableFormer em modo preciso;
- CPU e 10 threads;
- serviços remotos desabilitados.

## MinerU — `auto`

- backend pipeline;
- método automático;
- OCR habilitado pelo pipeline;
- threads do runtime, salvo override explícito.

## PaddleOCR — `mvp_structured`

- PPStructureV3;
- OCR, tabelas e fórmulas habilitados;
- orientação de documento e linhas habilitada;
- detecção de região habilitada;
- gráfico, unwarping e selo desabilitados.

---

# Apêndice D — Fontes de rastreabilidade

Este guia foi construído a partir de:

1. branch `milestone/mvp-ocr-auto-v2` do repositório;
2. `compose.yaml` e seus volumes de modelos;
3. `config/benchmark_profiles.json` schema v2;
4. adaptadores `pymupdf_v2.py`, `docling_v2.py`, `mineru_v2.py` e `paddleocr_v2.py`;
5. `notebooks/controlled_benchmark_analysis.ipynb`;
6. `notebooks/requirements.txt`;
7. snapshot oficial em `outputs/`;
8. documento `benchmark_controlado_v1.pdf`;
9. ferramentas oficiais de preparação de modelos de Docling, MinerU e PaddleOCR.

---

## Conclusão

A ordem deste guia separa preparação, smoke tests, modelos, inventário, medição, validação e análise. Essa separação é essencial: downloads e falhas de ambiente são resolvidos antes da medição; todos os parsers recebem o mesmo PDF; e os resultados só são comparados depois de passar pelos gates comuns.

O resultado final não deve ser reduzido a “qual parser tem menos tokens” ou “qual parser é mais rápido”. A decisão deve considerar preservação do conteúdo, comportamento nas páginas difíceis, robustez, custo computacional, estrutura do Markdown e objetivo real do pipeline de LLM.

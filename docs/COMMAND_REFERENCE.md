# Document AI Benchmark — Complete Command Reference

> **Recommended repository path:** `docs/COMMAND_REFERENCE.md`

This document is the operational companion to the main `README.md`. It explains the commands currently used in the repository, what each command does, what the important arguments mean, what result to expect, and whether the command is part of the formal benchmark, a diagnostic step, or a development-only check.

The repository should link to this document from the main README:

```markdown
## Detailed command reference

For a complete operational guide covering Docker, benchmark execution,
diagnostics, validation, and Git workflow, see:

[`docs/COMMAND_REFERENCE.md`](docs/COMMAND_REFERENCE.md)
```

---

# 1. Assumed environment

Unless stated otherwise, commands in this document assume:

```text
Host OS:       Windows 11
Linux layer:   WSL2
Distribution:  Ubuntu
Containers:    Docker Desktop / Linux containers
Shell:         Bash
Repository:    /home/victor-wsl/workspace/document-ai-benchmark
```

All repository-relative commands should be executed from:

```text
~/workspace/document-ai-benchmark
```

---

# 2. Enter the repository

```bash
cd ~/workspace/document-ai-benchmark
```

`cd` means **change directory**.

The `~` character expands to the current Linux user's home directory.

Verify:

```bash
pwd
```

Expected:

```text
/home/victor-wsl/workspace/document-ai-benchmark
```

`pwd` means **print working directory**.

---

# 3. Inspect repository files

Basic listing:

```bash
ls
```

Detailed listing including hidden files:

```bash
ls -la
```

Arguments:

- `-l`: long format with permissions, size, owner, and timestamps;
- `-a`: include hidden files such as `.gitignore`, `.dockerignore`, and `.env.example`.

Directory tree, when `tree` is installed:

```bash
tree -L 3
```

`-L 3` limits output to three directory levels.

Alternative:

```bash
find . -maxdepth 3 -type d | sort
```

Explanation:

- `find .`: search from current directory;
- `-maxdepth 3`: maximum recursion depth;
- `-type d`: directories only;
- `|`: pipe output to the next command;
- `sort`: sort alphabetically.

---

# 4. WSL verification

Distribution:

```bash
echo "$WSL_DISTRO_NAME"
```

Expected:

```text
Ubuntu
```

Kernel:

```bash
uname -r
```

Expected to contain something similar to:

```text
microsoft-standard-WSL2
```

---

# 5. Docker verification

Docker client/server:

```bash
docker version
```

Docker Compose:

```bash
docker compose version
```

Docker Engine information:

```bash
docker info
```

If `docker info` cannot reach the server, Docker Desktop may be stopped or WSL integration may be disabled.

---

# 6. Validate Compose configuration

Full resolved configuration:

```bash
docker compose config
```

This parses `compose.yaml`, resolves service configuration, mounts, environment values, and build paths.

Quiet validation:

```bash
docker compose config >/dev/null \
  && echo "Compose config: OK"
```

Important shell pieces:

- `>` redirects normal output;
- `/dev/null` discards that output;
- `&&` executes the next command only if the previous command succeeds.

Expected:

```text
Compose config: OK
```

---

# 7. List Compose services

```bash
docker compose config --services
```

`--services` prints only the service names.

Current repository services include:

```text
pymupdf
docling
mineru
paddleocr
```

---

# 8. Build Docker images

Build all services:

```bash
docker compose build
```

Build only PyMuPDF:

```bash
docker compose build pymupdf
```

Build PyMuPDF without Docker layer cache:

```bash
docker compose build --no-cache pymupdf
```

`--no-cache` forces every Dockerfile build step to execute again. It is slower and should only be used when stale cached layers are suspected.

---

# 9. Understand `docker compose run --rm`

Many repository commands begin with:

```bash
docker compose run --rm
```

Meaning:

- `docker compose`: use the repository Compose definition;
- `run`: start a one-off container;
- `--rm`: delete the temporary container when the process ends.

This is ideal for batch parser jobs and diagnostics.

It is different from:

```bash
docker compose up
```

which is intended for long-running services.

---

# 10. Override a container ENTRYPOINT

Example:

```bash
docker compose run --rm \
  --entrypoint python \
  pymupdf \
  -c "print('hello')"
```

`--entrypoint python` replaces the image's normal entrypoint for this one invocation.

This pattern is used for:

- syntax checks;
- package inspection;
- API probes;
- inline Python;
- diagnostic scripts.

---

# 11. Pass environment variables into a container

Example:

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/scripts/example.py
```

`-e PYTHONPATH=/app` defines an environment variable inside the temporary container.

`PYTHONPATH=/app` lets Python resolve repository imports such as:

```python
from src.benchmark.config import get_profile
```

---

# 12. Why source code mounts are read-only

Repository code is mounted similar to:

```yaml
- ./src:/app/src:ro
```

`:ro` means **read-only**.

This prevents containers from accidentally modifying project source code.

A side effect is that this may fail:

```bash
python -m py_compile /app/src/example.py
```

because Python tries to write a `__pycache__` directory next to the source file.

---

# 13. Syntax-check a read-only Python file

Use:

```bash
docker compose run --rm \
  --entrypoint python \
  pymupdf \
  -c "import py_compile; py_compile.compile('/app/src/example.py', cfile='/tmp/example.pyc', doraise=True); print('syntax: OK')"
```

Important arguments:

- `cfile='/tmp/example.pyc'`: write bytecode to writable `/tmp`;
- `doraise=True`: raise an exception on syntax failure.

---

# 14. Local Python syntax validation

When container-only dependencies are not needed:

```bash
python3 -m py_compile \
  src/benchmark/normalizer.py
```

No output means success.

---

# 15. Validate JSON configuration

```bash
python3 -m json.tool \
  config/benchmark_profiles.json \
  >/dev/null
```

`python3 -m json.tool` parses the JSON using Python's standard library.

Invalid JSON produces an error. Valid formatted output is discarded with `/dev/null`.

---

# 16. Show the benchmark plan

Primary OCR suite:

```bash
python3 scripts/show_benchmark_plan.py \
  --suite ocr_primary
```

Arguments:

- `--suite`: select a configured benchmark suite;
- `ocr_primary`: primary OCR-oriented comparison suite.

Current conceptual profiles include:

```text
pymupdf    ocr_auto_rapidtess
docling    ocr_auto_visual
mineru     auto
paddleocr  ocr_structured_visual
```

This command does **not** parse PDFs. It only resolves and prints the execution plan.

---

# 17. Show part of the benchmark plan

```bash
python3 scripts/show_benchmark_plan.py \
  --suite ocr_primary \
  | sed -n '17,28p'
```

Explanation:

- `|`: send command output into `sed`;
- `sed -n`: do not print all input automatically;
- `'17,28p'`: print only lines 17 through 28.

Useful for quickly inspecting profile configuration.

---

# 18. Visual ablation suite

```bash
python3 scripts/show_benchmark_plan.py \
  --suite visual_ablation
```

This suite is intended to isolate the cost and benefit of visual enrichment.

Examples:

```text
Docling OCR
vs.
Docling OCR + local picture description

Paddle structured extraction
vs.
Paddle structured extraction + chart recognition
```

---

# 19. Build Source Inventory for one PDF

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/scripts/build_source_inventory.py \
  --input-dir /data/raw \
  --output-dir /outputs/_source_inventory \
  --only benchmark_01_simple_18.pdf
```

Detailed argument explanation:

- `docker compose run --rm`: temporary container;
- `-e PYTHONPATH=/app`: repository imports available;
- `--entrypoint python`: run Python directly;
- `pymupdf`: use the PyMuPDF service environment;
- `/app/scripts/build_source_inventory.py`: inventory script;
- `--input-dir /data/raw`: source-PDF directory inside the container;
- `--output-dir /outputs/_source_inventory`: inventory JSON destination;
- `--only ...pdf`: restrict execution to exactly one PDF.

Without `--only`, the script may discover all PDFs in the configured directory.

---

# 20. Inspect a Source Inventory JSON

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path(
    "outputs/_source_inventory/"
    "benchmark_01_simple_18.json"
)

data = json.loads(
    path.read_text(
        encoding="utf-8"
    )
)

data.pop(
    "per_page",
    None,
)

print(
    json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    )
)
PY
```

Important concepts:

- `python3 -`: read Python code from standard input;
- `<<'PY'`: Bash here-document;
- `Path`: filesystem path abstraction;
- `json.loads`: parse JSON text;
- `data.pop("per_page", None)`: remove the large per-page section from the printed in-memory copy only;
- `ensure_ascii=False`: preserve Unicode characters.

---

# 21. Validate Source Inventory per-page records

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path(
    "outputs/_source_inventory/"
    "benchmark_01_simple_18.json"
)

data = json.loads(
    path.read_text(
        encoding="utf-8"
    )
)

pages = data["per_page"]

print("Per-page records:", len(pages))
print("First page:")
print(
    json.dumps(
        pages[0],
        indent=2,
    )
)

assert len(pages) == 18
assert pages[0]["page_number"] == 1
assert pages[-1]["page_number"] == 18

print("Source inventory per-page validation: OK")
PY
```

`assert` converts an expectation into an executable check.

If the expression is false, Python stops with an exception.

---

# 22. PyMuPDF package versions

```bash
docker compose run --rm \
  --entrypoint python \
  pymupdf \
  -c "import importlib.metadata as m; \
print('PyMuPDF4LLM:', m.version('pymupdf4llm')); \
print('PyMuPDF:', m.version('pymupdf')); \
print('PyMuPDF Layout:', m.version('pymupdf-layout')); \
print('RapidOCR:', m.version('rapidocr')); \
print('ONNX Runtime:', m.version('onnxruntime'))"
```

Validated versions:

```text
PyMuPDF4LLM:   1.28.2
PyMuPDF:       1.28.2
PyMuPDF Layout:1.28.2
RapidOCR:      3.9.2
ONNX Runtime:  1.28.0
```

`importlib.metadata.version()` checks what is actually installed, rather than merely trusting a requirements file.

---

# 23. Tesseract version

```bash
docker compose run --rm \
  --entrypoint tesseract \
  pymupdf \
  --version
```

Validated:

```text
tesseract 5.5.0
```

---

# 24. Tesseract languages

```bash
docker compose run --rm \
  --entrypoint tesseract \
  pymupdf \
  --list-langs
```

Validated languages:

```text
eng
osd
por
```

The formal PyMuPDF benchmark profile uses:

```text
por
```

---

# 25. RapidTess plugin import test

```bash
docker compose run --rm \
  --entrypoint python \
  pymupdf \
  -c "from pymupdf4llm.ocr import rapidtess_api; print('rapidtess_api import: OK'); print('exec_ocr callable:', callable(rapidtess_api.exec_ocr))"
```

`callable(...)` verifies that `exec_ocr` can be invoked like a function.

---

# 26. Inspect RapidTess callback signature

```bash
docker compose run --rm \
  --entrypoint python \
  pymupdf \
  -c "import inspect; from pymupdf4llm.ocr import rapidtess_api; print(inspect.signature(rapidtess_api.exec_ocr))"
```

Observed signature:

```text
(page, dpi=150, pixmap=None, language='eng', keep_ocr_text=False)
```

This command is important after library upgrades because callback signatures may change.

---

# 27. Structural probe syntax check

```bash
docker compose run --rm \
  --entrypoint python \
  pymupdf \
  -c "import py_compile; py_compile.compile('/app/scripts/probe_pymupdf_structure.py', cfile='/tmp/probe_pymupdf_structure.pyc', doraise=True); print('probe syntax: OK')"
```

---

# 28. Structural probe — simple PDF

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/scripts/probe_pymupdf_structure.py \
  --input /data/raw/benchmark_01_simple_18.pdf
```

The probe is diagnostic, not part of formal benchmark timing.

Validated structural contract:

```text
Chunk keys:
metadata
page_boxes
text
toc_items
```

Observed classes included:

```text
list-item
page-footer
page-header
picture
section-header
table
text
```

---

# 29. Structural probe — mixed PDF

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/scripts/probe_pymupdf_structure.py \
  --input /data/raw/benchmark_02_mixed_25.pdf
```

Observed additional classes included:

```text
caption
formula
picture
table
```

The probe established that the adapter must use:

```text
page_boxes[].class
```

rather than assuming `tables`, `images`, or `graphics` keys exist in Layout mode.

---

# 30. Automatic OCR analysis — diagnostic only

```bash
docker compose run --rm -T \
  --entrypoint python \
  pymupdf - <<'PY'
from collections import Counter

import pymupdf

from pymupdf4llm.helpers.utils import (
    analyze_page,
)

path = (
    "/data/raw/"
    "benchmark_02_mixed_25.pdf"
)

doc = pymupdf.open(path)

requested_pages = []
reasons = Counter()

try:
    for page_number, page in enumerate(
        doc,
        start=1,
    ):
        analysis = analyze_page(
            page
        )

        if analysis.get(
            "needs_ocr",
            False,
        ):
            requested_pages.append(
                page_number
            )

            reason = (
                analysis.get("reason")
                or "<unknown>"
            )

            reasons[reason] += 1

finally:
    doc.close()

print("=" * 64)
print("PYMUPDF AUTO-OCR ANALYSIS")
print("=" * 64)
print("Pages recommended:", len(requested_pages))
print("Page numbers:", requested_pages)
print("Reasons:", dict(reasons))
print("=" * 64)
PY
```

`-T` disables pseudo-terminal allocation, which is appropriate when piping Python code through standard input.

Validated result:

```text
Pages recommended: 13
Page numbers: [1, 3, 4, 5, 6, 7, 8, 9, 10, 13, 15, 17, 18]
Reasons: {'img_text': 13}
```

This command is diagnostic only. Do not add its runtime to formal extraction time.

---

# 31. PyMuPDF v2 adapter syntax check

Host:

```bash
python3 -m py_compile \
  src/parsers/pymupdf_v2.py
```

Container:

```bash
docker compose run --rm \
  --entrypoint python \
  pymupdf \
  -c "import py_compile; py_compile.compile('/app/src/parsers/pymupdf_v2.py', cfile='/tmp/pymupdf_v2.pyc', doraise=True); print('pymupdf_v2.py syntax: OK')"
```

---

# 32. PyMuPDF v2 import check

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  -c "import src.parsers.pymupdf_v2; print('PyMuPDF adapter v2 imports: OK')"
```

This checks actual imports, not just syntax.

It can detect missing:

- parser libraries;
- OCR libraries;
- Common Core modules.

---

# 33. Formal PyMuPDF v2 — Simple 18

Optional removal of only the generated profile:

```bash
rm -rf \
  outputs/pymupdf/benchmark_01_simple_18/ocr_auto_rapidtess
```

`rm -rf` is destructive.

Arguments:

- `rm`: remove;
- `-r`: recursive;
- `-f`: force.

Always verify the path before executing.

Formal run:

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/src/parsers/pymupdf_v2.py \
  --input /data/raw/benchmark_01_simple_18.pdf \
  --output-root /outputs \
  --profile ocr_auto_rapidtess
```

Important adapter arguments:

### `--input`

Input PDF path inside the container.

### `--output-root`

Base benchmark output directory.

### `--profile`

Select a configuration from `config/benchmark_profiles.json`.

Current formal PyMuPDF profile:

```text
ocr_auto_rapidtess
```

Validated result:

```text
Pages:                 18/18
OCR pages:             0
Tables detected:       4
Pictures detected:     1
Headings detected:     47
Lists detected:        42
Raw tokens:            5886
Clean tokens:          5670
Token reduction:       3.670%
```

---

# 34. Formal PyMuPDF v2 — Mixed 25

Optional cleanup:

```bash
rm -rf \
  outputs/pymupdf/benchmark_02_mixed_25/ocr_auto_rapidtess
```

Run:

```bash
docker compose run --rm \
  -e PYTHONPATH=/app \
  --entrypoint python \
  pymupdf \
  /app/src/parsers/pymupdf_v2.py \
  --input /data/raw/benchmark_02_mixed_25.pdf \
  --output-root /outputs \
  --profile ocr_auto_rapidtess
```

Validated Portuguese-profile result:

```text
Pages:                 25/25
OCR pages:             13
OCR page numbers:      [1, 3, 4, 5, 6, 7, 8, 9, 10, 13, 15, 17, 18]
Tables detected:       4
Pictures detected:     33
Headings detected:     48
Lists detected:        115
Raw tokens:            8867
Clean tokens:          8635
Token reduction:       2.616%
Removed records:       35
```

---

# 35. Audit removed content — Simple 18

```bash
python3 - <<'PY'
import json
from collections import Counter
from pathlib import Path

path = Path(
    "outputs/pymupdf/"
    "benchmark_01_simple_18/"
    "ocr_auto_rapidtess/"
    "removed_content.jsonl"
)

records = [
    json.loads(line)
    for line in path.read_text(
        encoding="utf-8"
    ).splitlines()
    if line.strip()
]

print("Records:", len(records))

print(
    "Types:",
    dict(
        Counter(
            record["type"]
            for record in records
        )
    ),
)

for key, count in Counter(
    record["normalized_key"]
    for record in records
).most_common():
    print(
        f"{count:>4}x | {key}"
    )
PY
```

Validated removal:

```text
18x | markitdown on windows | setup and pdf test manual
```

All were headers.

---

# 36. Audit removed content — Mixed 25

```bash
python3 - <<'PY'
import json
from collections import Counter
from pathlib import Path

p = Path(
    "outputs/pymupdf/"
    "benchmark_02_mixed_25/"
    "ocr_auto_rapidtess/"
    "removed_content.jsonl"
)

records = [
    json.loads(line)
    for line in p.read_text(
        encoding="utf-8"
    ).splitlines()
    if line.strip()
]

print("Removed:", len(records))

print(
    "Types:",
    dict(
        Counter(
            r["type"]
            for r in records
        )
    ),
)

print()
print("Top removed patterns:")

for value, count in Counter(
    r["normalized_key"]
    for r in records
).most_common(15):
    print(
        f"{count:>3}x | {value}"
    )
PY
```

Validated result:

```text
Removed: 35
Types: {'header': 11, 'footer': 24}

24x | <page-number>
11x | **guia rápido de instalação e configuração**
```

---

# 37. Inspect parser logs

```bash
grep -Ei \
  'OCR on page|warning|error' \
  outputs/pymupdf/benchmark_02_mixed_25/ocr_auto_rapidtess/run.log \
  || true
```

Arguments:

- `grep`: search text;
- `-E`: extended regular expressions;
- `-i`: case-insensitive;
- `|` inside the pattern: OR;
- `|| true`: do not treat “no matches” as a shell failure.

---

# 38. Expected Benchmark v2 output hierarchy

```text
outputs/
└── <parser>/
    └── <document>/
        └── <profile>/
            ├── raw.md
            ├── document.md
            ├── document.jsonl
            ├── metrics.json
            ├── removed_content.jsonl
            └── run.log
```

Example:

```text
outputs/
└── pymupdf/
    └── benchmark_02_mixed_25/
        └── ocr_auto_rapidtess/
            ├── raw.md
            ├── document.md
            ├── document.jsonl
            ├── metrics.json
            ├── removed_content.jsonl
            └── run.log
```

---

# 39. Meaning of output files

## `raw.md`

Parser output before common normalization.

## `document.md`

Clean Markdown after common normalization.

## `document.jsonl`

Canonical per-page structured output.

## `metrics.json`

Machine-readable benchmark metrics.

## `removed_content.jsonl`

Audit trail for normalization removals.

## `run.log`

Parser/runtime diagnostic messages.

---

# 40. Git status

Full:

```bash
git status
```

Compact:

```bash
git status --short
```

Use before and after every checkpoint.

---

# 41. Check whether Git ignores a file

```bash
git check-ignore -v \
  path/to/file \
  || true
```

`-v` shows the exact ignore rule.

Useful for:

```text
outputs/
models/
*.log
*.pdf
.env
```

---

# 42. Stage source code explicitly

Recommended checkpoint pattern:

```bash
git add \
  .gitignore \
  .dockerignore \
  compose.yaml \
  config \
  docker/pymupdf \
  docs \
  scripts \
  src
```

Explicit staging is safer than:

```bash
git add .
```

because generated data is less likely to be staged accidentally.

---

# 43. Inspect staged filenames

```bash
git diff --cached --name-only
```

`--cached` means staged changes.

`--name-only` shows filenames without full diff content.

---

# 44. Git staging safety check

```bash
git diff --cached --name-only \
  | grep -Ei \
  '(\.pdf$|\.log$|\.env$|/models/|/outputs/)' \
  && echo "WARNING: unwanted files staged" \
  || echo "Git staging safety check: OK"
```

This searches staged paths for files that normally should not enter Git.

Expected:

```text
Git staging safety check: OK
```

---

# 45. Review staged content

```bash
git diff --cached
```

Use before committing meaningful benchmark changes.

---

# 46. Commit current Benchmark v2 + PyMuPDF work

```bash
git commit -m \
  "feat: add benchmark v2 core and PyMuPDF OCR adapter"
```

Arguments:

- `git commit`: create commit from staged changes;
- `-m`: provide commit message directly.

`feat:` follows conventional-commit style and indicates a new feature/capability.

---

# 47. Push to GitHub

```bash
git push
```

Afterwards:

```bash
git status
```

Ideal output:

```text
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

---

# 48. Inspect recent Git history

```bash
git log --oneline -10
```

Arguments:

- `--oneline`: compact commit format;
- `-10`: last ten commits.

---

# 49. Docker resource inspection

Docker disk usage:

```bash
docker system df
```

Docker images:

```bash
docker images
```

Filter project images:

```bash
docker images \
  | grep document-ai-benchmark
```

Running containers:

```bash
docker ps
```

All containers:

```bash
docker ps -a
```

---

# 50. Stop long-running Compose services

```bash
docker compose down
```

This stops/removes Compose containers and its network.

Do **not** add `-v` unless named-volume deletion is intentional.

---

# 51. Shell operators used in this repository

## Backslash `\`

```bash
docker compose run --rm \
  --entrypoint python \
  pymupdf
```

A trailing backslash means the same shell command continues on the next line.

---

## Pipe `|`

```bash
command_a | command_b
```

Output from `command_a` becomes input to `command_b`.

---

## Redirect `>`

```bash
command > file.txt
```

Overwrite a file with standard output.

---

## Append `>>`

```bash
command >> file.txt
```

Append instead of overwrite.

---

## `&&`

```bash
command_a && command_b
```

Run `command_b` only if `command_a` succeeds.

---

## `||`

```bash
grep pattern file || true
```

Run the right-hand side if the left command fails.

---

## Here-document

```bash
python3 - <<'PY'
print("hello")
PY
```

Pass a multiline block to a command.

Using `'PY'` prevents shell variable expansion inside the block.

---

# 52. Exit codes

Linux convention:

```text
0        success
non-zero failure or special condition
```

Docker Compose propagates the process exit code.

The future unattended runner should use exit codes plus artifact/schema validation to determine whether a benchmark job succeeded.

---

# 53. Commands requiring caution

Recursive deletion:

```bash
rm -rf <path>
```

Always verify the path first.

Docker cleanup commands such as:

```text
docker system prune
docker volume prune
docker image prune
```

can delete valuable resources and are intentionally not part of the normal workflow.

---

# 54. Files that normally should not be committed

```text
data/raw/
outputs/
models/
*.pdf
*.log
.env
```

Also avoid committing:

- credentials;
- downloaded model binaries;
- large parser caches;
- temporary benchmark artifacts.

---

# 55. Files that normally should be committed

```text
README.md
docs/
config/
compose.yaml
docker/
scripts/
src/
tests/
.env.example
.gitignore
.dockerignore
```

---

# 56. Current formal PyMuPDF profile

```text
profile              = ocr_auto_rapidtess
layout_module        = true
ocr_enabled          = true
ocr_mode             = auto
ocr_engine           = rapidtess
ocr_language         = por
ocr_dpi              = 300
parser_header        = true
parser_footer        = true
force_text           = true
write_images         = false
embed_images         = false
page_separators      = false
reference tokenizer  = o200k_base
```

This is currently frozen as the first Benchmark v2 reference implementation.

---

# 57. Why there is no final Docling v2 command here yet

Docling v2 is the next migration target.

Generic image build is valid:

```bash
docker compose build docling
```

However, the final parser command is deliberately not documented as canonical yet.

Required sequence:

```text
1. inspect installed API
2. confirm OCR options
3. confirm picture-description behavior
4. write adapter
5. syntax/import validation
6. Simple-18
7. Mixed-25
8. audit artifacts
9. freeze command
```

This prevents documentation from becoming a source of guessed commands.

---

# 58. Why there is no final MinerU v2 command here yet

Generic image build:

```bash
docker compose build mineru
```

The legacy/native baseline is not yet equivalent to the Common Core v2 contract.

The final command should only be added after:

```text
actual-output probe
Common Core integration
process_tree_v2 integration
Simple-18
Mixed-25
adapter freeze
```

---

# 59. Why there is no final PaddleOCR v2 command here yet

Generic image build:

```bash
docker compose build paddleocr
```

PP-StructureV3 still requires:

```text
output probe
structured-result mapping
table/formula/chart mapping
Common Core integration
Simple-18
Mixed-25
adapter freeze
```

Only after that should a canonical Paddle v2 execution command be added.

---

# 60. Current benchmark corpus

```text
benchmark_01_simple_18.pdf
benchmark_02_mixed_25.pdf
benchmark_03_medium_268.pdf
benchmark_04_medhigh_532.pdf
benchmark_05_large_1109.pdf
```

Simple 18 and Mixed 25 are engineering smoke-test documents.

The larger PDFs should be reserved for stable adapters.

---

# 61. Formal execution should be sequential

Do not run formal parser benchmarks concurrently.

Parallel execution contaminates:

```text
CPU
RAM
disk I/O
caching
thermal behavior
scheduler behavior
```

Formal rule:

```text
one parser
one profile
one document
one job at a time
```

---

# 62. Model download and benchmark timing

Model downloads must not be included in extraction timing.

Separate:

```text
environment setup
model download
model warm-up
document extraction
normalization
artifact writing
```

A cold first-time download is not comparable to another parser's warm-cache extraction.

---

# 63. CPU interpretation

`process_tree_v2` tracks the root process and child processes.

Raw process-tree CPU can exceed 100%.

Example:

```text
400%
```

approximately represents four fully utilized cores.

Normalized system-capacity percentage divides by logical CPU count.

On 20 logical CPUs:

```text
1900% raw
≈
95% normalized total machine capacity
```

---

# 64. OCR cost interpretation

Validated PyMuPDF examples:

```text
Simple:
18 pages
0 OCR pages
~1.9 seconds extraction

Mixed:
25 pages
13 OCR pages
~39.3 seconds extraction
```

This is why selective OCR is a central benchmark concern.

---

# 65. Recommended development sequence

For every parser adapter:

```text
1. enter repository
2. git status
3. edit code/config
4. validate JSON
5. syntax-check Python
6. import-check inside container
7. API/structure probe
8. Simple-18
9. validate metrics
10. audit removed content
11. Mixed-25
12. validate OCR/visual behavior
13. validate metrics
14. inspect git diff
15. stage explicit files
16. staging safety check
17. commit
18. push
```

---

# 66. Definition of a canonical repository command

A parser command should only be considered canonical when:

```text
1. the corresponding code exists;
2. dependencies are pinned;
3. the installed API has been inspected;
4. the command has run successfully;
5. output structure has been validated;
6. required smoke tests pass;
7. behavior is stable for the current benchmark schema.
```

This is why PyMuPDF v2 is documented fully while future parser v2 commands remain intentionally incomplete.

---

# 67. Current Benchmark v2 readiness

## PyMuPDF4LLM

```text
Benchmark v2 adapter: READY
```

Validated:

```text
✓ container
✓ pinned versions
✓ Layout
✓ RapidTess
✓ Portuguese OCR
✓ automatic OCR
✓ Source Inventory
✓ Common Core v2
✓ process_tree_v2
✓ Simple-18
✓ Mixed-25
✓ normalization audit
✓ metrics schema v2
```

## Docling

```text
Benchmark v2 adapter: NEXT
```

## MinerU

```text
Benchmark v2 adapter: PENDING MIGRATION
```

## PaddleOCR

```text
Benchmark v2 adapter: PENDING MIGRATION
```

---

# 68. Final operational principle

A command in this repository can change:

```text
parser behavior
OCR behavior
language
resource consumption
output structure
token count
benchmark comparability
```

Therefore:

> **Important parser options must be explicit, versioned, documented, and reproducible.**

The goal is not only to make the code run.

The goal is to make it possible to explain **exactly why a result was produced**, reproduce it later, and compare it fairly with other Document AI parsers.

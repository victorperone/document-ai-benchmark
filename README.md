# Document AI Benchmark

Local benchmark environment for evaluating document processing and retrieval solutions for large PDF documents.

## Objective

Evaluate different local document intelligence pipelines capable of converting large PDFs into lightweight structured representations suitable for retrieval and cloud LLM consumption.

The project focuses on minimizing the amount of information sent to cloud LLMs while preserving relevant information contained in:

- native PDF text
- tables
- scanned content
- images
- diagrams
- complex document layouts

## Candidate Solutions

Document parsers:

1. PyMuPDF4LLM
2. Docling
3. MinerU
4. PaddleOCR PP-StructureV3

Visual retrieval:

5. ColQwen / ColPali

## Architecture

PDF

→ Local parser / OCR / document intelligence

→ Structured JSONL

→ Chunking

→ Local embeddings and retrieval

→ Top K relevant context

→ Temporary Markdown context

→ Cloud LLM

Images remain local and are not sent directly to the cloud LLM.

## Environment

Development:

- Windows 11
- WSL2
- Ubuntu 22.04
- Docker Desktop
- NVIDIA GPU optional

Target server:

- Linux VM
- Docker Engine
- CPU required
- NVIDIA GPU optional

The application is designed to support automatic fallback between GPU and CPU.

## Current Status

Completed native CPU baselines:

- PyMuPDF4LLM
- Docling

Current benchmark corpus contains five documents ranging from 18 to 1109 pages.

Current benchmark profiles use OCR disabled in order to isolate parser and document-layout processing costs.

OCR-enabled benchmarks are required for the final production comparison and will be executed separately.

See:

- `data/benchmark_manifest.md`
- `metrics/pymupdf_summary.md`
- `metrics/docling_summary.md`
- `metrics/parser_comparison.md`

## Native CPU Benchmark

The initial native-text CPU benchmark has been completed for:

- PyMuPDF4LLM
- Docling
- MinerU

The current native benchmark intentionally disables OCR in order to isolate
parser, layout, table, and document-structure processing costs.

This is not the final production benchmark.

The production-oriented comparison will include OCR-enabled processing for all
applicable solutions using a common resource-monitoring implementation.

Current reports:

- `metrics/pymupdf_summary.md`
- `metrics/docling_summary.md`
- `metrics/mineru_summary.md`
- `metrics/native_parser_comparison.md`

### Important interpretation note

Structural element counts are parser-specific. For example, one parser may
classify a visual element as a picture while another may classify it as a
chart. These counts are therefore diagnostic measurements and are not direct
quality scores.






# PyMuPDF4LLM v2 — Local PDF Parsing, Layout Analysis and Selective OCR

## Status

**Implementation status: completed and validated for the benchmark v2 adapter.**

The PyMuPDF4LLM integration is the first parser in this project to be fully migrated to the Benchmark v2 architecture.

The implementation currently provides:

- local PDF processing;
- native PDF text extraction;
- document layout analysis;
- table, picture, heading, list and formula-region detection;
- automatic selective OCR;
- OCR in Portuguese using Tesseract language code `por`;
- RapidOCR-based text-region detection combined with Tesseract recognition;
- per-page structured output;
- raw and normalized Markdown;
- JSONL output for downstream chunking and retrieval;
- source-PDF inventory;
- CPU and memory monitoring;
- token counting;
- noise measurement;
- header/footer cleanup;
- complete audit trail of removed content;
- explicit parser/profile configuration;
- reproducible output directories;
- robustness metrics;
- processing-time metrics.

PyMuPDF4LLM is used in this project as one candidate for the local parsing layer of a Document AI / RAG ingestion pipeline.

---

## 1. Why PyMuPDF4LLM is part of this benchmark

The purpose of this project is **not simply to extract text from a PDF**.

The larger objective is to build a local Document AI ingestion pipeline capable of processing very large corporate documents while minimizing the amount of information eventually sent to a cloud LLM.

The intended production architecture is:

```text
                         LOCAL ENVIRONMENT

                             PDF
                              │
                              ▼
                   Document Parser / OCR
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼
        Native text        Tables        Visual regions
             │                │                │
             └────────────────┼────────────────┘
                              ▼
                     Structured document
                              │
                     document.jsonl
                              │
                              ▼
                         Chunking
                              │
                              ▼
                        Embeddings
                              │
                              ▼
                     Local vector index
                              │
                              ▼
                     Query + Retrieval
                              │
                              ▼
                   Small temporary context
                              │
                              ▼

                          CLOUD LLM
                     only relevant text
```

The main idea is that a 1,000-page PDF should **not** be sent directly to a cloud model.

Instead, the document is parsed once locally, transformed into searchable structured content, indexed locally, and only a small number of relevant chunks are eventually sent to the cloud.

PyMuPDF4LLM is one candidate for the **local parsing layer**.

---

## 2. Role of PyMuPDF4LLM in the benchmark

The PyMuPDF adapter performs four logically separate jobs:

```text
PDF
 │
 ├── Objective source inspection
 │
 │      └── Source Inventory
 │
 ▼
PyMuPDF4LLM
 │
 ├── Layout analysis
 ├── Native text extraction
 ├── Table detection
 ├── Picture-region detection
 ├── Heading detection
 ├── List detection
 └── Selective OCR
 │
 ▼
Raw page Markdown
 │
 ▼
Common Benchmark Core
 │
 ├── Header/footer normalization
 ├── Noise analysis
 ├── Token analysis
 ├── Markdown structure analysis
 ├── Resource accounting
 └── Audit trail
 │
 ▼
Final artifacts
```

It is important that these responsibilities remain separated.

For example:

> “The original PDF contains zero embedded raster images”

and:

> “PyMuPDF Layout detected one `picture` region”

are **not contradictory statements**.

A `picture` produced by the Layout model is a semantic/layout classification of an area of a page. That region may involve vectors, text, graphics or raster content.

An embedded-image count from the Source Inventory, on the other hand, describes an objective object found inside the PDF.

These metrics must never be treated as the same thing.

---

## 3. Software stack used by the PyMuPDF profile

The validated container currently contains:

| Component | Version | Purpose |
|---|---:|---|
| PyMuPDF4LLM | 1.28.2 | High-level document-to-Markdown / structured extraction |
| PyMuPDF | 1.28.2 | Core PDF processing engine |
| PyMuPDF Layout | 1.28.2 | Layout and semantic page-region analysis |
| RapidOCR | 3.9.2 | OCR text-region detection |
| ONNX Runtime | 1.28.0 | Runtime used by RapidOCR |
| Tesseract | 5.5.0 | OCR text recognition |
| Tesseract language | `por` | Portuguese OCR |
| tiktoken | 0.13.0 | Reference token counting |
| psutil | 7.2.2 | CPU, process and memory monitoring |

---

## 4. Official PyMuPDF benchmark profile

The primary profile implemented by this project is:

```text
ocr_auto_rapidtess
```

Its effective behavior is:

| Setting | Value | Reason |
|---|---|---|
| Layout analysis | Enabled | Preserve document structure and reading order |
| OCR | Enabled | Required for mixed/scanned content |
| OCR mode | Automatic | Avoid OCR when native text is already usable |
| OCR engine | RapidTess | RapidOCR detection + Tesseract recognition |
| OCR language | `por` | Portuguese-language recognition |
| OCR DPI | 300 | Quality-oriented default for formal profile |
| Parser header extraction | Enabled | Common normalizer handles removal |
| Parser footer extraction | Enabled | Common normalizer handles removal |
| `force_text` | Enabled | Preserve text even around visual/layout regions |
| Write images | Disabled | Images are not needed in cloud context |
| Embed images | Disabled | Prevent base64/image inflation of Markdown |
| Page separators | Disabled | Avoid benchmark-generated token overhead |
| Reference tokenizer | `o200k_base` | Stable tokenizer for cross-parser comparison |

---

## 5. Why OCR is automatic instead of forced

A key decision in this project is:

```text
use_ocr = true

but

force_ocr = false
```

This difference matters.

A normal digital PDF may already contain an accurate text layer.

Running OCR over perfectly good text can:

- waste CPU;
- waste memory;
- make processing much slower;
- introduce recognition errors that did not exist in the native PDF.

The selected strategy therefore uses OCR selectively only when the parser determines that OCR is useful.

This behavior was directly observed in this project.

### Simple digital PDF

```text
Pages:       18
OCR pages:    0
```

### Mixed-content PDF

```text
Pages:       25
OCR pages:   13
```

The exact OCR pages in the mixed document were:

```text
1, 3, 4, 5, 6, 7, 8, 9, 10, 13, 15, 17, 18
```

This is exactly the behavior the architecture is intended to achieve:

```text
clean digital page
        │
        └── native extraction

page with text inside image
        │
        └── OCR

clean digital page
        │
        └── native extraction
```

rather than:

```text
every page
    │
    └── expensive OCR
```

---

## 6. RapidTess OCR

The selected OCR adapter is called **RapidTess**.

Conceptually:

```text
Page / visual region
        │
        ▼
RapidOCR
        │
        └── finds text regions / bounding boxes
        │
        ▼
Tesseract
        │
        └── recognizes the characters
        │
        ▼
PyMuPDF4LLM
        │
        └── incorporates the OCR information
        ▼
Structured output
```

This combination was chosen because document images may contain text in complex visual regions where separating **where text exists** from **what the characters say** is useful.

---

## 7. Portuguese OCR

The formal benchmark profile uses:

```text
ocr_language = por
```

The container contains the Tesseract language packages:

```text
eng
osd
por
```

Therefore `por` is the explicit OCR language used by the current formal PyMuPDF profile.

The project intentionally does **not** silently enable `por+eng`.

A bilingual profile may be useful later for real Brazilian corporate documents containing Portuguese plus English technical terminology, but that would introduce another experimental variable.

If such a profile is evaluated later, it should be represented as a separate benchmark profile instead of silently changing the current one.

---

## 8. `keep_ocr_text` and the OCR callback

During development, the actual PyMuPDF4LLM 1.28.2 callback contract was inspected.

The installed RapidTess function exposed:

```text
(page, dpi=150, pixmap=None, language='eng', keep_ocr_text=False)
```

The Layout pipeline passed the additional parameter:

```text
keep_ocr_text
```

to the OCR callback.

The first version of the benchmark wrapper did not accept this argument, which caused the mixed-document test to fail.

The wrapper was therefore redesigned to:

1. inspect the real installed OCR plugin signature;
2. accept additional keyword arguments from PyMuPDF4LLM;
3. record which additional arguments were observed;
4. forward only arguments supported by the installed plugin;
5. record requested OCR pages;
6. record successfully processed OCR pages;
7. record failed OCR pages.

This produced:

```text
callback_extra_kwargs_observed:
    keep_ocr_text
```

The project deliberately **does not override `keep_ocr_text`**.

It is treated as part of PyMuPDF4LLM's internal OCR contract.

This is safer than changing an internal parameter based only on its name.

---

## 9. OCR selection was independently validated

The benchmark did not simply trust the number reported by the adapter.

A diagnostic pass first asked PyMuPDF4LLM which pages of the mixed 25-page PDF it considered candidates for OCR.

The diagnostic analysis selected:

```text
[1, 3, 4, 5, 6, 7, 8, 9, 10, 13, 15, 17, 18]
```

All 13 selections had the reason:

```text
img_text
```

The formal adapter was then executed independently.

The adapter actually invoked OCR on:

```text
[1, 3, 4, 5, 6, 7, 8, 9, 10, 13, 15, 17, 18]
```

Comparison:

```text
Diagnostic count:  13
Executed count:    13

Only diagnostic:   []
Only execution:    []

Exact match:       True
Failed OCR:        0
```

This is a strong engineering validation that the OCR-tracking wrapper is observing the real parser behavior rather than manufacturing an unrelated metric.

---

## 10. Layout mode

PyMuPDF Layout is enabled in the primary benchmark profile.

With Layout enabled, the actual output observed from:

```text
page_chunks = true
```

contained:

```text
metadata
page_boxes
text
toc_items
```

Each layout box includes information conceptually equivalent to:

```text
index
class
bbox
pos
```

where:

- `index` represents its reading-order index;
- `class` represents its semantic layout class;
- `bbox` represents its page coordinates;
- `pos` links the box back to a range in the generated page text.

Observed classes included:

```text
text
picture
table
caption
section-header
page-header
page-footer
list-item
formula
```

---

## 11. Why the adapter uses `page_boxes`

An early implementation assumed that parser results would expose:

```text
tables
images
graphics
```

directly in every chunk.

A structural probe showed that this assumption was incorrect for the selected configuration.

With Layout enabled, the actual chunks were:

```text
metadata
page_boxes
text
toc_items
```

Therefore the v2 adapter derives semantic parser counts from:

```text
page_boxes[].class
```

rather than from legacy/non-Layout fields.

This is an important design principle for every parser in this project:

> **Adapters must be written against the structure actually returned by the pinned version, not against assumptions or examples from another version.**

---

## 12. Structural probe results

Before the formal adapter was implemented, a dedicated structural probe was run.

### Simple 18-page PDF

```text
Chunks:                  18
page_boxes pages:        18 / 18
Total layout boxes:      362

Layout classes:

list-item                 42
page-footer               19
page-header               18
picture                    1
section-header            47
table                      4
text                     231
```

### Mixed 25-page PDF — probe before OCR

```text
Chunks:                  25
page_boxes pages:        25 / 25
Total layout boxes:      357

Layout classes:

caption                   31
formula                    2
list-item                126
page-footer               24
page-header               27
picture                   35
section-header            47
table                      4
text                      61
```

These numbers are **parser diagnostics**, not ground truth.

For example:

```text
table = 4
```

means:

> PyMuPDF Layout classified four regions as tables.

It does **not** mean:

> The document objectively contains exactly four tables.

Actual table-preservation quality will later be measured against a human-created Gold Standard.

---

## 13. Source Inventory

Before a parser result is evaluated, the project creates an objective inventory of the source PDF.

This inventory intentionally avoids semantic statements such as:

```text
tables = 10
charts = 5
headings = 80
```

because those would themselves require another parser or human interpretation.

Instead, the Source Inventory records observable PDF properties such as:

```text
SHA-256
file size
page count
native text characters
native text blocks
pages with native text
pages without native text
embedded image objects
unique image references
vector drawing groups
per-page properties
```

This gives every parser the **same source reference**.

The inventory is created once and can be reused when the SHA-256 still matches the PDF.

If a PDF is silently replaced while keeping the same filename, the SHA-256 changes and the cached inventory should no longer be trusted.

---

## 14. Example: why Source Inventory and parser semantics must stay separate

For the simple 18-page PDF, Source Inventory measured:

```text
Pages:                         18
Native text characters:        23,021
Native text blocks:            387
Pages with native text:        18
Pages without native text:      0
Embedded image occurrences:     0
Unique embedded image xrefs:    0
Vector drawing groups:         290
```

PyMuPDF Layout later reported:

```text
picture regions: 1
```

This does **not** indicate an inconsistency.

It means:

```text
Source Inventory
    │
    └── PDF contains zero embedded raster image objects

PyMuPDF Layout
    │
    └── one page region looks semantically like a picture
```

The distinction is deliberately preserved in `metrics.json`.

---

## 15. Raw output must be preserved

The parser output is not immediately cleaned.

The pipeline first preserves:

```text
raw.md
```

Only after that does the common normalizer create:

```text
document.md
```

This distinction is essential.

If cleanup modifies content incorrectly, `raw.md` remains available for:

- debugging;
- quality comparisons;
- regression analysis;
- reproducing token calculations;
- auditing the normalization algorithm.

The project therefore follows:

```text
parser
  │
  ▼
raw.md              ← immutable parser-level representation
  │
  ▼
normalizer
  │
  ├── removed_content.jsonl
  │
  ▼
document.md         ← cleaned representation
```

---

## 16. Why headers and footers remain enabled in the parser

For this benchmark, both remain enabled:

```text
parser_header = true
parser_footer = true
```

This is intentional.

If each parser performs a different internal cleanup:

```text
PyMuPDF removes headers
Docling preserves them
MinerU partially removes them
Paddle removes something else
```

then downstream token comparisons become less meaningful.

Instead, all parsers should preferably expose as much raw content as reasonably possible and then pass through the **same common normalization layer**.

That makes the comparison closer to:

```text
Parser A raw
      │
Common normalizer
      ▼
Parser A clean

Parser B raw
      │
Common normalizer
      ▼
Parser B clean
```

rather than comparing different parser-specific cleanup policies.

---

## 17. Conservative header/footer normalization

The common normalizer is designed to be conservative.

It does **not** remove text simply because it appears near the top or bottom of the page.

Conceptually, removal requires:

```text
page-edge position
        +
repetition across multiple pages
        +
minimum occurrence threshold
```

The current configuration includes:

```text
minimum repeated page fraction: 30%
minimum repeated page count:    3

header candidate lines:         first 3 non-empty lines
footer candidate lines:         last 3 non-empty lines
```

Page-number formats may also be normalized into a common key such as:

```text
<page-number>
```

so that repeated page-number patterns can be recognized as the same type of noise.

---

## 18. Normalizer audit — simple document

The simple 18-page benchmark removed exactly:

```text
18 records
```

All were:

```text
header
```

The repeated content was:

```text
MarkItDown on Windows | Setup and PDF Test Manual
```

It appeared on all 18 pages.

No technical body content was observed in the removed-content audit.

This is an ideal normalization case:

```text
same text
+
same page-edge role
+
100% page repetition
=
safe repetitive header candidate
```

---

## 19. Normalizer audit — mixed document

The mixed 25-page document removed:

```text
35 records
```

Classification:

```text
11 headers
24 footers
```

The two detected repeated patterns were:

```text
24x  <page-number>

11x  **guia rápido de instalação e configuração**
```

Again, the audit output makes every removal inspectable.

Nothing is silently discarded.

---

## 20. Removed-content audit

Every normalization removal is written to:

```text
removed_content.jsonl
```

A record includes information such as:

```text
page number
line index
classification
original text
normalized comparison key
reason for removal
number of pages where it occurred
fraction of pages where it occurred
```

This is important because token reduction is useful only if relevant technical information is preserved.

The benchmark therefore treats:

```text
fewer tokens
```

as a positive result only when paired with:

```text
content preservation
```

---

## 21. Token measurement

Token usage is calculated using a fixed **reference tokenizer**:

```text
o200k_base
```

This tokenizer is not being claimed as the eventual production-model tokenizer.

It exists to provide a stable unit of comparison across parsers.

The benchmark records:

```text
raw Markdown tokens
clean Markdown tokens
tokens removed
token reduction percentage
tokens per page
```

Later, after a cloud LLM is selected, the pipeline may additionally record the model-specific tokenizer.

The reference tokenizer should remain stable so historic parser comparisons do not change whenever the cloud model changes.

---

## 22. Why token attribution is labelled as estimated

The exact difference:

```text
raw_tokens - clean_tokens
```

is a valid measurement for the reference tokenizer.

However, tokenizing each removed header independently is not mathematically equivalent to subtracting its token contribution inside the original document because BPE tokenization depends on surrounding context.

For this reason, per-category token attribution is explicitly treated as an estimate.

The benchmark distinguishes between:

```text
exact total token reduction
```

and:

```text
estimated contribution of removed records
```

This avoids presenting approximate attribution as an exact measurement.

---

## 23. Noise metrics

Both raw and cleaned Markdown are analyzed for noise.

The Common Core currently measures features such as:

```text
whitespace ratio
non-alphanumeric ratio
empty lines
empty pages
replacement-character ratio
control-character ratio
duplicate-line ratio
repeated-line ratio
number of repeated unique lines
short-line ratio
line-ending hyphenation count
```

These metrics help distinguish two outputs that may have similar token counts but very different quality.

For example:

```text
Parser A
10,000 tokens
clean paragraphs

Parser B
10,000 tokens
many duplicated lines and broken OCR fragments
```

Token count alone would make them look equal.

Noise metrics expose that difference.

---

## 24. Markdown structure metrics

The Common Core also analyzes the generated Markdown independently from parser-internal diagnostics.

It currently counts structures such as:

```text
Markdown headings
Markdown list items
Markdown tables
image references
image placeholders
code blocks
```

This gives us two different perspectives:

```text
parser_output
```

means:

> What the parser internally classified.

while:

```text
clean_markdown
```

means:

> What structures actually survived into the textual representation.

Neither is treated as ground truth.

---

## 25. Resource monitoring

The original benchmark monitor was replaced with:

```text
process_tree_v2
```

The monitor follows the root process and its child processes.

This is important because Document AI libraries often launch additional processes or runtimes.

Only measuring the top Python PID can therefore severely under-report resource consumption.

The monitor records:

```text
wall-clock time
process CPU time
raw process-tree CPU percentage
normalized system-capacity CPU percentage
average resident memory
peak resident memory
disk read volume
disk write volume
number of observed processes
```

CPU is reported in two useful forms.

### Raw process-tree CPU

This can exceed 100%.

For example:

```text
1 fully utilized core ≈ 100%
10 fully utilized cores ≈ 1000%
```

### System-capacity normalized CPU

The raw number is divided by the number of logical CPUs.

This allows a result such as:

```text
95%
```

to mean approximately:

> 95% of the machine's available logical CPU capacity was used on average.

---

## 26. Timing separation

Runtime is not represented by one ambiguous number.

The v2 schema separates:

```text
initialization
extraction
normalization
common metric calculation
artifact writing
complete pipeline
```

This matters because:

```text
parser extraction speed
```

is not the same thing as:

```text
complete ingestion-pipeline speed
```

Later, model loading/warm-up costs can also be discussed separately from steady-state extraction.

---

## 27. Output structure

Each parser/profile/document combination gets its own directory:

```text
outputs/
└── pymupdf/
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

The profile level is essential.

Without it:

```text
native
OCR auto
forced OCR
```

would overwrite one another.

---

## 28. Purpose of each output file

### `raw.md`

The page content produced by the parser before common cleanup.

Used for:

- parser-quality inspection;
- debugging;
- token comparison;
- regression analysis.

### `document.md`

The normalized Markdown representation.

This is the cleaner textual representation intended for later:

```text
chunking
embedding
retrieval
```

The full Markdown file is still intended to remain local.

It should not be sent wholesale to a cloud LLM.

### `document.jsonl`

Canonical per-page structured representation.

Each line contains information such as:

```text
document identity
source filename
parser
profile
page number
raw page Markdown
clean page Markdown
parser element counts
parser-native layout information
```

This will eventually become the bridge between:

```text
document parsing
```

and:

```text
chunking / retrieval
```

### `metrics.json`

Machine-readable benchmark result.

It includes:

```text
benchmark schema
timestamp
parser/profile
dependency versions
resolved configuration
source-document identity
source inventory
timings
OCR behavior
resource utilization
parser structural counts
Markdown structural counts
noise metrics
token metrics
normalization metrics
output file sizes
```

### `removed_content.jsonl`

Complete normalization audit.

Nothing removed by the common cleaner should disappear without being traceable here.

### `run.log`

Parser/runtime diagnostic messages.

This is useful for debugging but is not intended to be committed to Git.

---

## 29. PyMuPDF v2 — simple 18-page result

Formal Portuguese profile:

```text
ocr_auto_rapidtess
ocr_language = por
```

| Metric | Result |
|---|---:|
| Pages | 18 / 18 |
| OCR pages | 0 |
| Extraction time | 1.915 s |
| Complete pipeline | 2.128 s |
| Tables detected | 4 |
| Picture regions detected | 1 |
| Headings detected | 47 |
| List items detected | 42 |
| Raw tokens | 5,886 |
| Clean tokens | 5,670 |
| Tokens removed | 216 |
| Token reduction | 3.670% |
| Removed normalization records | 18 |
| Average CPU capacity | 96.20% |
| Peak CPU capacity | 100.00% |
| Process CPU time | 40.42 s |
| Average RAM | 287.289 MB |
| Peak RAM | 364.484 MB |

### Interpretation

This PDF is fully digital.

Source Inventory showed:

```text
18 / 18 pages with meaningful native text
```

Therefore selective OCR correctly performed:

```text
0 OCR pages
```

The parser still performed Layout analysis and detected:

```text
4 table regions
1 picture region
47 heading/section-header regions
42 list items
```

The common normalizer removed only the repeated document header.

---

## 30. PyMuPDF v2 — mixed 25-page result

Formal Portuguese profile:

```text
ocr_auto_rapidtess
ocr_language = por
```

| Metric | Result |
|---|---:|
| Pages | 25 / 25 |
| OCR pages | 13 |
| OCR failures | 0 |
| Extraction time | 39.288 s |
| Complete pipeline | 39.525 s |
| Tables detected | 4 |
| Picture regions detected | 33 |
| Headings detected | 48 |
| List items detected | 115 |
| Raw tokens | 8,867 |
| Clean tokens | 8,635 |
| Tokens removed | 232 |
| Token reduction | 2.616% |
| Removed normalization records | 35 |
| Average CPU capacity | 64.11% |
| Peak CPU capacity | 100.00% |
| Process CPU time | 492.8 s |
| Average RAM | 1,177.002 MB |
| Peak RAM | 2,018.805 MB |

The 13 OCR pages were:

```text
1, 3, 4, 5, 6, 7, 8, 9, 10, 13, 15, 17, 18
```

---

## 31. What the mixed result tells us

The increase from:

```text
~1.9 seconds extraction
```

on the 18-page digital document to:

```text
~39.3 seconds extraction
```

on the 25-page mixed document illustrates one of the most important characteristics of Document AI:

> OCR is significantly more computationally expensive than native PDF text extraction.

The mixed document also increased peak RAM from approximately:

```text
364 MB
```

to:

```text
2,019 MB
```

This makes selective OCR important for large-document production workloads.

The benchmark should therefore evaluate not only quality, but:

```text
quality
÷
compute cost
```

---

## 32. What these results do NOT prove

The current results do **not** prove that:

- PyMuPDF4LLM is the most accurate parser;
- four detected tables means exactly four true tables;
- every OCR character was recognized correctly;
- `picture=33` means the PDF has 33 embedded images;
- fewer output tokens automatically means better extraction;
- the current OCR profile is optimal for every Portuguese document;
- 300 DPI is globally optimal;
- PyMuPDF will outperform every other parser on every PDF;
- the current Markdown is sufficient for every future RAG question.

Those claims require later quality evaluation.

---

## 33. What has been proven

The current implementation **has** established that:

```text
✓ containerized PyMuPDF stack works
✓ versions are pinned
✓ Layout works
✓ page_chunks structure is understood
✓ OCR runtime works
✓ RapidTess works
✓ Tesseract Portuguese data is available
✓ automatic OCR selection works
✓ OCR callback tracking works
✓ 13 diagnostic OCR pages == 13 executed OCR pages
✓ zero OCR failures on the mixed smoke test
✓ source inventory works
✓ per-page mapping works
✓ Common Core v2 works
✓ normalizer is auditable
✓ reference token accounting works
✓ CPU monitoring works
✓ RAM monitoring works
✓ output schema v2 works
✓ artifacts are isolated by document/profile
```

That is enough to freeze this adapter as the **first Benchmark v2 reference implementation**.

Quality/Gold-Standard validation remains a later benchmark phase.

---

## 34. Known limitation: OCR quality is not yet Gold-Standard validated

OCR execution and OCR page selection have been validated.

OCR **recognition accuracy** has not yet been formally measured against a manually verified transcript.

For example, the synthetic OCR smoke test successfully recovered:

```text
DOCUMENT AI BENCHMARK OCR TEST 2026
```

but produced a small recognition variation:

```text
AI → Al
```

This is precisely why the final benchmark will need quality metrics.

Operational success:

```text
OCR executed without error
```

is different from quality:

```text
OCR reproduced the source correctly
```

The Gold Standard stage will measure that distinction.

---

## 35. Future quality metrics

Later benchmark phases should add human-validated reference data for representative pages.

Expected dimensions include:

```text
Text quality
├── character similarity
├── normalized edit distance
├── missing-text rate
└── duplicated-text rate

Table quality
├── table detection precision
├── table detection recall
├── table F1
├── row/column preservation
└── cell-content preservation

OCR quality
├── character error rate
├── word error rate
└── accented-character preservation

Retrieval quality
├── Recall@5
├── Recall@10
└── MRR

Answer quality
├── factual correctness
├── evidence support
├── correct-page retrieval
└── hallucination rate
```

Only after these measurements should parser quality be ranked formally.

---

## 36. Licensing note

This must be reviewed before corporate production deployment.

PyMuPDF/PyMuPDF4LLM use an AGPL/commercial dual-licensing model.

Therefore:

```text
technical benchmark approval
        ≠
legal production approval
```

Licensing should remain an explicit deployment decision.

---

# Future Steps — Migrating the Remaining Parsers to Benchmark v2

PyMuPDF is now the **reference implementation for the adapter contract**.

The next parsers should not reinvent the benchmark infrastructure.

They should only implement their parser-specific extraction layer and feed their results into the same Common Core.

The target design is:

```text
                  Common Benchmark Core v2

                         ┌─────────────┐
PyMuPDF adapter ────────►│             │
                         │             │
Docling adapter ─────────►│ normalize   │
                         │ tokens      │
MinerU adapter ──────────►│ noise       │
                         │ artifacts   │
PaddleOCR adapter ───────►│ metrics     │
                         │ resources   │
                         └─────────────┘
```

---

## 37. Standard migration procedure for every remaining parser

Every parser should go through the following sequence.

### Step 1 — Freeze the parser version

Before adapter development begins, record the exact package/model/runtime versions.

Do not develop against “latest”.

The benchmark must always be able to answer:

> Which exact parser produced this result?

### Step 2 — Define explicit profiles

Every meaningful configuration should have a profile name.

For example:

```text
native
ocr_auto
ocr_visual
forced_ocr
```

A profile must describe what actually happened, not hide behavior behind defaults.

### Step 3 — Separate model download/warm-up from benchmark runtime

Model downloading must not be counted as extraction time.

First-run initialization and normal steady-state parsing are different costs.

Model caches should therefore be prepared before formal measurements.

### Step 4 — Probe the installed API before writing the adapter

Do not assume output structures.

Create a small diagnostic script that asks the **installed version**:

```text
What classes exist?
What options exist?
What fields are returned?
Where are page numbers stored?
Where are tables stored?
Where are pictures stored?
Where are OCR diagnostics stored?
```

PyMuPDF already demonstrated why this matters.

The initial assumption that Layout chunks would contain:

```text
tables
images
graphics
```

was wrong.

The probe revealed the real contract:

```text
page_boxes
```

and prevented incorrect metrics.

Every other parser must receive the same treatment.

### Step 5 — Validate parser runtime independently

Before integrating the Common Core, confirm that the parser itself works.

For OCR-capable profiles, validate:

```text
runtime loads
models load
OCR engine loads
language configuration works
a real OCR operation completes
```

This separates:

```text
parser failure
```

from:

```text
benchmark integration failure
```

### Step 6 — Map parser-native output to the canonical contract

Each adapter should produce, at minimum:

```text
page number
page Markdown/text
parser-native structure metadata
parser semantic element counts
```

The adapter should not perform common normalization itself.

### Step 7 — Preserve parser-native information

Parser-specific information should remain available inside:

```text
parser_native
```

in `document.jsonl`.

This allows later debugging without forcing all parsers into an artificially identical internal schema.

### Step 8 — Pass page text through the same `finalize_artifacts()` path

The Common Core should generate:

```text
raw.md
document.md
document.jsonl
removed_content.jsonl
common token metrics
noise metrics
Markdown structure metrics
```

This is important for fair comparison.

### Step 9 — Use the same `ResourceMonitor v2`

All parser comparisons must use:

```text
process_tree_v2
```

Do not compare new CPU measurements against the older monitor implementation.

### Step 10 — Run the simple 18-page smoke test

Purpose:

```text
verify basic extraction
verify page alignment
verify schema
verify output files
verify normalizer
verify token accounting
verify resource monitoring
```

This is not the quality benchmark.

It is the engineering smoke test.

### Step 11 — Run the mixed 25-page smoke test

Purpose:

```text
exercise OCR
exercise images
exercise tables
exercise layout
exercise visual regions
exercise more complicated Markdown
```

This is where OCR-specific problems should become visible.

### Step 12 — Audit removed content

Before accepting any parser integration, inspect:

```text
removed_content.jsonl
```

If technical content is removed, fix normalization before proceeding.

### Step 13 — Validate robustness fields

Check:

```text
pages_total
pages_processed
failed_pages
empty_output_pages
OCR pages
OCR failures
warnings
errors
retries
```

Unavailable information must be:

```text
null
```

rather than a fake:

```text
0
```

### Step 14 — Freeze the adapter

After simple + mixed validation:

```text
commit
tag conceptually as benchmark-v2-compatible
do not casually change behavior
```

Later behavioral changes should become new profiles or new schema versions.

### Step 15 — Only then run the full corpus

The large PDFs should not be used to debug adapter plumbing.

Once all four parsers satisfy the same contract, the full corpus can run sequentially and reproducibly.

---

## 38. Future Step — Docling v2

Docling is the next parser to migrate.

The current planned production-oriented profile is:

```text
ocr_auto_visual
```

Conceptually:

```text
Docling
├── OCR                    ON
├── table structure        ON
├── picture description    ON
├── local VLM              ON
├── remote services        OFF
└── Common Core v2         ON
```

### Docling implementation sequence

1. Confirm the exact installed Docling version.
2. Probe `PdfPipelineOptions`.
3. Probe the OCR option classes actually available.
4. Resolve the OCR engine explicitly.
5. Avoid leaving the effective OCR engine ambiguous.
6. Confirm CPU configuration.
7. Confirm table-structure options.
8. Confirm picture-description options.
9. Validate the configured local picture-description model.
10. Keep remote services disabled.
11. Confirm whether picture descriptions automatically appear in Markdown.
12. If they do not, explicitly serialize them into the local textual representation.
13. Preserve Docling-native document objects/metadata in `parser_native`.
14. Map tables, pictures, headings and formulas into diagnostic parser counts.
15. Pass page text to `finalize_artifacts()`.
16. Run Simple 18.
17. Run Mixed 25.
18. Audit OCR pages and visual descriptions.
19. Audit normalized content.
20. Freeze the Docling v2 adapter.

---

## 39. Future Step — Docling visual-description ablation

Picture description should not be mixed invisibly into the standard OCR result.

The benchmark should preserve two profiles:

```text
ocr_auto
```

and:

```text
ocr_auto_visual
```

This allows measurement of:

```text
additional tokens
additional runtime
additional RAM
additional model storage
additional semantic information
```

caused specifically by local visual description.

This is important because image-to-text enrichment may improve RAG quality while also increasing local compute cost and final token count.

---

## 40. Future Step — MinerU v2

MinerU will be migrated after Docling.

The benchmark currently distinguishes:

```text
txt
```

from:

```text
auto
```

and from a diagnostic forced-OCR mode.

### MinerU migration sequence

1. Keep the already validated pinned MinerU environment.
2. Preserve model cache outside formal benchmark timing.
3. Keep CPU as the mandatory baseline.
4. Probe the actual generated output structure.
5. Identify page-level text/Markdown.
6. Identify table objects.
7. Identify picture/image objects.
8. Identify formula objects.
9. Identify chart objects where exposed.
10. Determine which fields are parser diagnostics versus true textual output.
11. Map the output into canonical page records.
12. Preserve MinerU's own structured output as parser-native metadata.
13. Feed page text into the Common Core.
14. Replace any legacy resource measurements with `process_tree_v2`.
15. Run Simple 18.
16. Run Mixed 25.
17. Confirm `method=auto` OCR behavior.
18. Audit failed/fallback pages.
19. Audit memory consumption carefully.
20. Freeze MinerU v2.

---

## 41. Future Step — PaddleOCR / PP-StructureV3 v2

PaddleOCR is not treated as merely another plain-text OCR engine.

The planned integration uses **PP-StructureV3** as a structured document parsing pipeline.

The primary planned structured profile is:

```text
ocr_structured_visual
```

Conceptually:

```text
PaddleOCR / PP-StructureV3
├── OCR                 ON
├── table recognition   ON
├── formula recognition ON
├── chart processing    ON
├── orientation         controlled by profile
├── unwarping           controlled by profile
└── Common Core v2      ON
```

### PaddleOCR migration sequence

1. Freeze PaddleOCR and PaddlePaddle versions.
2. Freeze/download required models before timing.
3. Probe PP-StructureV3's real output objects.
4. Determine page-level reading order.
5. Determine text blocks.
6. Determine headings/titles.
7. Determine table results.
8. Determine formula results.
9. Determine chart results.
10. Determine image/figure regions.
11. Verify how Markdown export represents these structures.
12. Map parser diagnostics into the common schema.
13. Preserve native Paddle result objects.
14. Pass final page text through `finalize_artifacts()`.
15. Validate Simple 18.
16. Validate Mixed 25.
17. Compare lightweight and structured-visual profiles.
18. Measure model-cache size separately.
19. Measure the effect of chart recognition separately.
20. Freeze the Paddle v2 adapter.

---

## 42. Planned cross-parser profiles

The benchmark should ultimately distinguish between:

```text
Native / low-cost extraction
```

and:

```text
OCR-capable extraction
```

and:

```text
Visual enrichment
```

A conceptual comparison matrix is:

| Parser | Native / Text | OCR | Tables | Visual enrichment |
|---|---|---|---|---|
| PyMuPDF4LLM | Yes | RapidTess auto | Layout tables | Layout picture regions |
| Docling | Yes | Auto/configured OCR | Table structure | Local picture-description VLM |
| MinerU | `txt` | `auto` | Yes | Image/chart-aware parsing |
| PaddleOCR | N/A as pure native baseline | Yes | PP-StructureV3 | Formula/chart structured processing |

This prevents comparing radically different workloads without labeling them.

---

## 43. Full-corpus benchmark

Only after all four adapters conform to Benchmark v2 should the full corpus be executed.

Current corpus:

```text
benchmark_01_simple_18.pdf
benchmark_02_mixed_25.pdf
benchmark_03_medium_268.pdf
benchmark_04_medhigh_532.pdf
benchmark_05_large_1109.pdf
```

The final runner should automatically discover:

```text
data/raw/*.pdf
```

rather than hardcoding filenames.

---

## 44. Sequential execution

Formal parser jobs should run sequentially.

Running several parser/model containers at the same time would contaminate:

```text
CPU utilization
RAM utilization
disk IO
runtime
model contention
thermal behavior
```

and would make comparisons less reliable.

Therefore:

```text
one document
one parser/profile
one job at a time
```

is the intended formal benchmark behavior.

---

## 45. Resumable benchmark runner

The future unattended runner should support:

```text
automatic PDF discovery
suite selection
profile selection
sequential execution
skip valid completed jobs
retry/continue policy
failure logging
result validation
summary generation
resume after interruption
```

A job should only be considered complete if its expected artifact set exists and its `metrics.json` passes basic schema validation.

A partially created output directory must not automatically count as success.

---

## 46. Final benchmark philosophy

The project should not choose a parser based on one number.

The final decision needs to consider at least:

```text
Extraction quality
        │
        ├── text
        ├── tables
        ├── OCR
        ├── layout
        └── visual information

Operational cost
        │
        ├── CPU
        ├── RAM
        ├── storage
        └── runtime

RAG efficiency
        │
        ├── clean token count
        ├── retrieval quality
        └── cloud context size

Production constraints
        │
        ├── licensing
        ├── CPU/GPU requirement
        ├── model size
        ├── deployment complexity
        └── offline capability
```

The goal is therefore **not**:

```text
Which parser extracts the most text?
```

It is:

```text
Which local parsing architecture preserves enough useful
information to answer business questions accurately while
minimizing local compute and cloud-token cost?
```

---

## 47. Planned final visualization

Once Gold Standard quality metrics exist, a useful high-level comparison will be:

```text
Tokens vs Table Preservation vs Operational Cost
```

For example:

```text
X axis:
cleaned reference tokens
(lower is generally better)

Y axis:
table preservation F1
(higher is better)

Bubble size:
runtime / computational cost
(smaller is better)

Additional dimension:
peak RAM

Marker:
parser + profile
```

Critically:

```text
parser-detected table count
```

must **not** be used as table-preservation score.

Table preservation requires comparison against a human-verified Gold Standard.

---

## 48. Definition of Done for a Benchmark v2 parser

A parser should only be marked `Benchmark v2 ready` when all of the following are true:

```text
[ ] Exact dependency versions recorded
[ ] Container builds successfully
[ ] Models/runtime available locally
[ ] Profile configuration is explicit
[ ] Actual installed API has been probed
[ ] Parser-specific output structure understood
[ ] OCR runtime validated, when applicable
[ ] Page mapping validated
[ ] Parser-native metadata preserved
[ ] Common Core integration complete
[ ] raw.md generated
[ ] document.md generated
[ ] document.jsonl generated
[ ] removed_content.jsonl generated
[ ] metrics.json schema v2 generated
[ ] ResourceMonitor process_tree_v2 used
[ ] Token metrics generated
[ ] Noise metrics generated
[ ] Normalization audit performed
[ ] Simple 18-page smoke test passed
[ ] Mixed 25-page smoke test passed
[ ] No unexplained failed pages
[ ] No unexplained OCR failures
[ ] Adapter behavior frozen before full-corpus execution
```

PyMuPDF4LLM currently satisfies this engineering checklist.

Quality/Gold-Standard validation remains a later benchmark phase.

---

## Recommended GitHub checkpoint

With the current validation results, this is an appropriate point for a GitHub checkpoint.

Suggested commit message:

```text
feat: add benchmark v2 core and PyMuPDF OCR adapter
```

Keep generated/runtime data out of Git:

```text
data/raw/
outputs/
models/
*.pdf
*.log
.env
```

The formal PyMuPDF profile documented by the project is the Portuguese version:

```text
ocr_auto_rapidtess
ocr_language = por
```

The previous English run should remain only as local development evidence and should not be treated as the formal benchmark result.

---

## Next milestone

The next implementation target is:

```text
Docling v2
    │
    ├── installed API probe
    ├── explicit OCR configuration
    ├── table structure
    ├── local picture description
    ├── Common Core integration
    ├── Simple 18 smoke test
    ├── Mixed 25 smoke test
    └── adapter freeze
```

After Docling, the same migration contract will be applied to MinerU and PaddleOCR before the complete benchmark corpus is executed.

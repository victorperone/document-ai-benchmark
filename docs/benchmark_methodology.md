# Document AI Benchmark Methodology

## 1. Purpose

This benchmark evaluates local document intelligence pipelines for processing
large corporate PDF documents before retrieval and cloud LLM consumption.

The primary business objective is to minimize cloud tokens while preserving
information quality.

The benchmark therefore evaluates three dimensions simultaneously:

1. Extraction quality
2. Local computational cost
3. Token efficiency

No parser is considered superior based only on runtime, memory consumption,
output size, or number of detected elements.

---

## 2. Benchmark Schema

Current benchmark schema version:

    2

All benchmark executions using schema version 2 must use the same:

- corpus discovery rules
- output directory convention
- reference tokenizer
- resource-monitoring implementation
- noise metrics
- normalization rules
- quality evaluation methodology

Results produced using different benchmark schema versions must not be mixed
in the same aggregate comparison without an explicit warning.

---

## 3. Input Corpus Discovery

Benchmark inputs are discovered automatically from:

    data/raw/*.pdf

PDF filenames must not be hardcoded in benchmark scripts.

Files are processed in deterministic filename order.

Adding a new PDF to `data/raw/` automatically adds it to the next benchmark
suite execution.

Raw PDF files must never be committed to Git.

---

## 4. Output Directory Convention

Every parser execution must use:

    outputs/<parser>/<document>/<profile>/

Example:

    outputs/docling/benchmark_03_medium_268/ocr_auto/

Each execution directory must contain, where applicable:

    raw.md
    document.md
    document.jsonl
    metrics.json
    removed_content.jsonl
    run.log

### raw.md

Unmodified Markdown produced by the parser or the closest possible normalized
representation of the parser output.

### document.md

Cleaned Markdown after common normalization.

This is the candidate representation for chunking and retrieval.

### document.jsonl

Canonical page/block-level structured representation used locally.

### removed_content.jsonl

Audit trail containing content removed by the common normalization pipeline.

### run.log

Parser-specific execution log.

---

## 5. Profiles

A parser can expose multiple processing profiles.

Profiles must be configured centrally and must not be represented by
unexplained hardcoded booleans inside benchmark metrics.

Examples:

    native
    ocr_auto
    ocr_force
    lightweight
    default
    full

Every `metrics.json` must record the fully resolved configuration that was
actually executed.

A value of `false`, `0`, and `null` have different meanings.

Examples:

    false = explicitly disabled
    0     = measured and found to be zero
    null  = unavailable or not exposed by the parser

Unavailable measurements must never be represented as zero.

---

## 6. Source Inventory

The source PDF inventory contains only objectively observable PDF properties.

Examples:

- pages
- file size
- SHA-256
- native text blocks
- embedded images
- vector objects
- pages without native text

Semantic objects such as tables, headings, lists, and charts must not be
treated as source ground truth merely because a parser detected them.

A parser must never define its own ground truth.

---

## 7. Content Elements

Content elements are measured separately at three stages.

### 7.1 Source PDF inventory

Objective PDF-level properties only.

Example:

    source_pdf:
        native_text_blocks
        embedded_images
        vector_objects
        pages_without_native_text

### 7.2 Parser output

Semantic structures reported by the parser.

Examples:

    tables_detected
    images_detected
    charts_detected
    headings_detected
    lists_detected
    formulas_detected

### 7.3 Markdown output

Structures actually preserved in the Markdown representation.

Examples:

    tables
    image_references
    headings
    lists
    code_blocks

Parser element counts are diagnostic measurements.

They are not quality scores.

---

## 8. Gold Standard

Extraction preservation is evaluated against a manually reviewed Gold
Standard.

The Gold Standard should contain representative pages and questions covering:

- native text
- scanned text
- simple tables
- complex tables
- images containing text
- charts
- diagrams
- formulas
- headings
- lists
- multi-column layouts
- cross-page information
- cross-page tables

The full multi-thousand-page corpus does not require complete manual
annotation.

A smaller representative Gold Standard should be used.

---

## 9. Noise Heuristics

Noise metrics must be calculated for both:

    raw parser output
    cleaned Markdown output

Required metrics:

### whitespace_ratio

    whitespace characters / total characters

### non_alphanumeric_ratio

    characters that are neither alphanumeric nor whitespace
    --------------------------------------------------------
                    total characters

### empty_lines

Number of lines containing only whitespace.

### empty_pages

Number of pages producing no meaningful textual content.

### replacement_character_ratio

Occurrences of Unicode replacement character U+FFFD divided by total
characters.

This is useful for detecting encoding or OCR corruption.

### control_character_ratio

Unexpected control characters divided by total characters.

### duplicate_line_ratio

Fraction of normalized lines duplicated within the document.

### repeated_line_ratio

Fraction of normalized lines appearing repeatedly across multiple pages.

This is particularly useful for header/footer detection.

### short_line_ratio

Fraction of non-empty lines below the configured minimum character threshold.

### line_end_hyphenation_count

Number of lines ending with a likely word-breaking hyphen.

---

## 10. Header and Footer Normalization

Repeated headers and footers are considered potential token waste.

They must not be destructively removed from the raw parser output.

Processing is:

    parser
      |
      v
    raw.md
      |
      v
    common normalizer
      |
      +--> removed_content.jsonl
      |
      v
    document.md

Header/footer removal must consider:

1. page position when available
2. cross-page repetition
3. normalized textual similarity

Position alone must never be sufficient for deletion.

Removed content must remain auditable.

---

## 11. Token Metrics

The benchmark reference tokenizer is:

    o200k_base

The reference tokenizer must remain stable across benchmark runs so historical
results remain comparable.

The benchmark must separately support a deployment tokenizer when a specific
cloud model is selected.

Required metrics:

    raw_markdown_tokens
    clean_markdown_tokens
    tokens_removed
    token_reduction_percent
    header_footer_tokens_removed
    tokens_per_page

The reference tokenizer is a comparison instrument and must not be selected
simply because it produces the fewest tokens.

---

## 12. Processing Robustness

Required processing metrics include:

    pages_total
    pages_processed
    failed_pages
    partial_pages
    empty_output_pages
    warnings_count
    errors_count
    retry_count

OCR-specific metrics should include, when exposed by the parser:

    pages_requested
    pages_processed
    fallback_ocr_pages
    failed_ocr_pages

If a parser does not expose one of these values, record `null`.

Do not infer zero.

---

## 13. Resource Metrics

All schema-v2 parsers must use the same common resource monitor.

Required CPU metrics:

    wall_time_seconds
    process_cpu_time_seconds
    average_cpu_percent
    peak_cpu_percent
    average_cpu_system_capacity_percent
    peak_cpu_system_capacity_percent

Required memory metrics:

    average_rss_mb
    peak_rss_mb

Where reliable:

    disk_read_mb
    disk_write_mb

For GPU profiles:

    device_name
    average_gpu_utilization_percent
    peak_gpu_utilization_percent
    average_vram_mb
    peak_vram_mb

Resource-monitor version must be recorded in `metrics.json`.

---

## 14. Runtime Measurement

Parser initialization, document extraction, normalization, and total pipeline
time must be measured separately whenever possible.

Example:

    initialization_seconds
    extraction_seconds
    normalization_seconds
    pipeline_seconds

Warm-up and model download time must not be mixed with formal benchmark
runtime.

Model cache policy must be documented.

---

## 15. Execution Policy

Formal parser/profile comparisons must execute sequentially.

Parsers must not run concurrently during formal performance measurement.

Concurrent execution would introduce CPU, RAM, disk, and GPU contention and
invalidate direct runtime comparison.

The benchmark runner may continue to the next job after a failure.

Failures must be recorded and never silently skipped.

---

## 16. Resume Policy

The full benchmark runner must support resumable execution.

A completed execution is skipped only when its result passes validation.

Required behavior:

    completed -> skip
    missing   -> run
    failed    -> retry or record according to runner configuration
    invalid   -> rerun

---

## 17. Primary OCR Profiles

The initial production-oriented OCR comparison will use economical or
automatic OCR modes rather than forced full-page OCR wherever possible.

Primary profiles:

### PyMuPDF4LLM

    ocr_auto_rapidtess

### Docling

    ocr_auto

### MinerU

    auto

### PaddleOCR / PP-StructureV3

    default

Forced OCR and expensive enrichment profiles are diagnostic profiles and
should not automatically run over the entire large-document corpus.

---

## 18. Diagnostic Profiles

Examples:

### PyMuPDF4LLM

    ocr_force_rapidtess

### MinerU

    ocr

### PaddleOCR

    full

These profiles are primarily intended for scanned or difficult Gold Standard
documents unless explicitly included in another suite.

---

## 19. Performance vs Quality

More detected objects do not automatically imply better extraction.

Example:

One parser may classify the same visual object as a picture while another
classifies it as a chart.

Therefore:

    detected element count != preservation quality

Preservation must be measured against the Gold Standard.

---

## 20. Quality Metrics

Planned quality metrics include:

### Text

- character accuracy
- normalized edit similarity
- answerability

### Tables

- table recall
- table precision
- table F1
- structural preservation
- cell-content preservation

### Retrieval

- Recall@K
- MRR
- page correctness
- evidence correctness

### Answer generation

- answer accuracy
- hallucination rate
- evidence support rate

---

## 21. Executive Efficiency Visualization

The primary executive visualization will be a bubble scatter plot.

Axes:

    X = cleaned Markdown tokens
    Y = table preservation F1

Additional dimensions:

    bubble size = operational runtime or estimated compute cost
    color       = peak memory
    marker      = parser/profile

The preferred region is:

    fewer tokens
    higher preservation
    lower runtime
    lower memory

Table preservation must come from the Gold Standard, never from the parser's
own table count.

---

## 22. Cloud Cost

Cloud token cost must be measured only after retrieval.

The complete extracted Markdown is not intended to be sent to a cloud LLM.

Architecture:

    local parsing
        ->
    local structured storage
        ->
    local chunking
        ->
    local retrieval
        ->
    Top K context
        ->
    temporary Markdown
        ->
    cloud LLM

Final business efficiency will consider:

    extraction quality
    local compute cost
    retrieval quality
    cloud tokens
    cloud monetary cost
    response quality

---

## 23. Benchmark Integrity Rules

The following rules are mandatory:

1. Never use parser output as that parser's own ground truth.
2. Never represent unavailable measurements as zero.
3. Never compare results generated under different methodologies without
   explicitly identifying the difference.
4. Never overwrite raw parser output with cleaned output.
5. Never delete removed content without retaining an audit trail.
6. Never change the reference tokenizer inside a benchmark series.
7. Never run formal performance comparisons concurrently.
8. Never include model download time in steady-state extraction runtime.
9. Never treat output token count alone as extraction quality.
10. Never select a production parser before quality evaluation.

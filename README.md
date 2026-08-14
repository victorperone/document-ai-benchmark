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

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

PyMuPDF4LLM CPU baseline implemented.

Current benchmark corpus contains documents ranging from 18 to 1109 pages.

See:

- `data/benchmark_manifest.md`
- `metrics/pymupdf_summary.md`

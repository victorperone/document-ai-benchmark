# Benchmark Document Corpus

The PDF files used for benchmarking are intentionally excluded from Git.

| ID | File | Pages | Profile |
|---|---|---:|---|
| 01 | benchmark_01_simple_18.pdf | 18 | Simple digital document without images |
| 02 | benchmark_02_mixed_25.pdf | 25 | Mixed manual with text, tables and images |
| 03 | benchmark_03_medium_268.pdf | 268 | Medium document with text, tables and images |
| 04 | benchmark_04_medhigh_532.pdf | 532 | Medium large document with text, tables and images |
| 05 | benchmark_05_large_1109.pdf | 1109 | Large document with text, tables and images |

## Benchmark goals

The corpus is intended to measure:

- document processing time
- pages processed per second
- CPU utilization
- memory utilization
- GPU and VRAM utilization when applicable
- output size
- token count
- extraction quality
- table preservation
- image information preservation
- OCR quality
- retrieval quality
- cloud context token reduction

Additional document classes may be added later, including scanned documents and documents with particularly complex layouts.

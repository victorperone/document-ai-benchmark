# Native Parser Comparison

CPU benchmark with OCR disabled.

> CPU utilization is intentionally omitted from cross-parser comparison because MinerU uses the corrected process-tree monitor v2 while the earlier PyMuPDF4LLM and Docling native runs used monitor v1.

> Table, picture, image, and chart counts are parser-specific classifications and must not be interpreted as directly equivalent quality metrics.

## Performance

| Document | Pages | PyMuPDF s | Docling s | MinerU s | Docling / PyMuPDF | MinerU / PyMuPDF | MinerU / Docling |
|---|---:|---:|---:|---:|---:|---:|---:|
| benchmark_01_simple_18.pdf | 18 | 1.915 | 12.592 | 45.68 | 6.58x | 23.85x | 3.63x |
| benchmark_02_mixed_25.pdf | 25 | 3.638 | 16.851 | 50.811 | 4.63x | 13.97x | 3.02x |
| benchmark_03_medium_268.pdf | 268 | 21.841 | 128.134 | 540.489 | 5.87x | 24.75x | 4.22x |
| benchmark_04_medhigh_532.pdf | 532 | 67.044 | 338.175 | 1006.218 | 5.04x | 15.01x | 2.98x |
| benchmark_05_large_1109.pdf | 1109 | 111.688 | 564.487 | 2265.978 | 5.05x | 20.29x | 4.01x |

## Peak Memory

| Document | PyMuPDF MB | Docling MB | MinerU MB |
|---|---:|---:|---:|
| benchmark_01_simple_18.pdf | 409.836 | 2173.285 | 3240.195 |
| benchmark_02_mixed_25.pdf | 465.883 | 2528.938 | 4081.547 |
| benchmark_03_medium_268.pdf | 487.246 | 3136.793 | 8050.176 |
| benchmark_04_medhigh_532.pdf | 766.543 | 2989.105 | 7769.98 |
| benchmark_05_large_1109.pdf | 882.0 | 3425.934 | 9631.008 |

## Markdown Tokens

| Document | PyMuPDF | Docling | MinerU |
|---|---:|---:|---:|
| benchmark_01_simple_18.pdf | 5994 | 5571 | 5919 |
| benchmark_02_mixed_25.pdf | 7705 | 6919 | 7474 |
| benchmark_03_medium_268.pdf | 99358 | 153743 | 115721 |
| benchmark_04_medhigh_532.pdf | 224922 | 232982 | 220983 |
| benchmark_05_large_1109.pdf | 395166 | 460410 | 418475 |

## Structural Detection

| Document | Docling Tables | Docling Pictures | MinerU Tables | MinerU Pictures | MinerU Charts |
|---|---:|---:|---:|---:|---:|
| benchmark_01_simple_18.pdf | 4 | 0 | 4 | 0 | 0 |
| benchmark_02_mixed_25.pdf | 3 | 35 | 3 | 33 | 0 |
| benchmark_03_medium_268.pdf | 6 | 144 | 14 | 79 | 29 |
| benchmark_04_medhigh_532.pdf | 35 | 368 | 35 | 324 | 28 |
| benchmark_05_large_1109.pdf | 17 | 317 | 20 | 223 | 113 |

## Aggregate Runtime

- PyMuPDF4LLM: 206.126 s
- Docling: 1060.239 s
- MinerU: 3909.176 s
- Docling / PyMuPDF4LLM: 5.14x
- MinerU / PyMuPDF4LLM: 18.96x
- MinerU / Docling: 3.69x

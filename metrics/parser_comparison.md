# Parser Comparison

Native PDF baseline with OCR disabled.

| Document | Pages | PyMuPDF s | Docling s | Docling Slowdown | PyMuPDF RAM MB | Docling RAM MB | PyMuPDF Tokens | Docling Tokens | Token Delta | Tables | Pictures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| benchmark_01_simple_18.pdf | 18 | 1.915 | 12.592 | 6.58x | 409.836 | 2173.285 | 5994 | 5571 | -7.06% | 4 | 0 |
| benchmark_02_mixed_25.pdf | 25 | 3.638 | 16.851 | 4.63x | 465.883 | 2528.938 | 7705 | 6919 | -10.2% | 3 | 35 |
| benchmark_03_medium_268.pdf | 268 | 21.841 | 128.134 | 5.87x | 487.246 | 3136.793 | 99358 | 153743 | 54.74% | 6 | 144 |
| benchmark_04_medhigh_532.pdf | 532 | 67.044 | 338.175 | 5.04x | 766.543 | 2989.105 | 224922 | 232982 | 3.58% | 35 | 368 |
| benchmark_05_large_1109.pdf | 1109 | 111.688 | 564.487 | 5.05x | 882.0 | 3425.934 | 395166 | 460410 | 16.51% | 17 | 317 |

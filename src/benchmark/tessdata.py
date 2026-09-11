"""Candidate tessdata directory paths for Tesseract OCR.

``_TESSDATA_CANDIDATES`` lists the conventional installation locations on
Windows and Linux.  Callers iterate this tuple until they find an existing
directory, or raise an error if none is found.
"""

from __future__ import annotations

_TESSDATA_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/local/share/tessdata",
    "/usr/share/tessdata",
)

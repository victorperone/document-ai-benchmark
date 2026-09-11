"""Discovery helpers for optional external command-line tools.

Currently only covers Tesseract OCR, whose executable location is
non-standard on Windows and must be searched explicitly.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def resolve_tesseract_executable() -> str | None:
    """Return the absolute path to the Tesseract OCR executable, or ``None``.

    Searches ``PATH`` first.  On Windows, also checks the two conventional
    installation directories if ``PATH`` lookup fails.

    Returns:
        Absolute path string when Tesseract is found, ``None`` otherwise.
    """
    found = shutil.which("tesseract")
    if found:
        return found

    if sys.platform != "win32":
        return None

    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return None

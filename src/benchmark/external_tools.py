from __future__ import annotations

import shutil
import sys
from pathlib import Path


def resolve_tesseract_executable() -> str | None:
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

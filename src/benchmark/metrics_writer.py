from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically: write → flush → fsync → close → replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")

    try:
        with tmp.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())

        os.replace(tmp, path)

    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def write_json(
    path: Path,
    data: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    atomic_write_text(
        path,
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
    )


def write_jsonl(
    path: Path,
    records: Iterable[dict[str, Any]],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    lines = "\n".join(
        json.dumps(record, ensure_ascii=False)
        for record in records
    )
    atomic_write_text(path, lines + "\n" if lines else "")

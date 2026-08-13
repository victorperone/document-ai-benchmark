from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import psutil
import pymupdf
import pymupdf4llm
import tiktoken


TOKENIZER_NAME = "o200k_base"
MONITOR_INTERVAL_SECONDS = 0.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PyMuPDF4LLM baseline parser for the document AI benchmark."
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)

    return parser.parse_args()


def json_default(value: Any) -> Any:
    try:
        return list(value)
    except TypeError:
        return str(value)


def bytes_to_mb(value: int | float) -> float:
    return round(value / (1024 * 1024), 3)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


class ResourceMonitor:
    def __init__(self, interval: float = MONITOR_INTERVAL_SECONDS) -> None:
        self.interval = interval
        self.process = psutil.Process(os.getpid())
        self.logical_cpus = psutil.cpu_count(logical=True) or 1

        self.cpu_samples: list[float] = []
        self.memory_samples: list[int] = []

        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def _process_tree(self) -> list[psutil.Process]:
        processes = [self.process]

        try:
            processes.extend(self.process.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return processes

    def _prime_cpu_counters(self) -> None:
        for process in self._process_tree():
            try:
                process.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _sample(self) -> None:
        cpu_percent = 0.0
        rss_bytes = 0

        for process in self._process_tree():
            try:
                cpu_percent += process.cpu_percent(interval=None)
                rss_bytes += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        self.cpu_samples.append(cpu_percent)
        self.memory_samples.append(rss_bytes)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            self._sample()

    def start(self) -> None:
        self._prime_cpu_counters()

        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> dict[str, float]:
        self.stop_event.set()

        if self.thread is not None:
            self.thread.join()

        self._sample()

        average_cpu = (
            statistics.mean(self.cpu_samples)
            if self.cpu_samples
            else 0.0
        )

        peak_cpu = max(self.cpu_samples, default=0.0)
        peak_memory = max(self.memory_samples, default=0)

        return {
            "average_cpu_percent": round(average_cpu, 2),
            "peak_cpu_percent": round(peak_cpu, 2),
            "average_cpu_system_capacity_percent": round(
                min(average_cpu / self.logical_cpus, 100.0),
                2,
            ),
            "peak_cpu_system_capacity_percent": round(
                min(peak_cpu / self.logical_cpus, 100.0),
                2,
            ),
            "peak_rss_mb": bytes_to_mb(peak_memory),
        }


def main() -> int:
    args = parse_args()

    input_path = Path(args.input)
    base_output_dir = Path(args.output_dir)

    if not input_path.exists():
        print(
            f"ERROR: Input file does not exist: {input_path}",
            file=sys.stderr,
        )
        return 1

    if not input_path.is_file():
        print(
            f"ERROR: Input path is not a file: {input_path}",
            file=sys.stderr,
        )
        return 1

    document_id = input_path.stem
    output_dir = base_output_dir / document_id
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = output_dir / "document.md"
    jsonl_path = output_dir / "document.jsonl"
    metrics_path = output_dir / "metrics.json"

    input_bytes = input_path.stat().st_size
    input_sha256 = calculate_sha256(input_path)

    with pymupdf.open(str(input_path)) as document:
        page_count = document.page_count

    parser_version = metadata.version("pymupdf4llm")
    tokenizer = tiktoken.get_encoding(TOKENIZER_NAME)

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK")
    print("=" * 72)
    print("Parser:       PyMuPDF4LLM")
    print(f"Version:      {parser_version}")
    print(f"Input:        {input_path}")
    print(f"Pages:        {page_count}")
    print(f"Output:       {output_dir}")
    print("Mode:         CPU baseline")
    print("OCR:          disabled")
    print("Images:       not exported")
    print(f"Tokenizer:    {TOKENIZER_NAME}")
    print("=" * 72)

    monitor = ResourceMonitor()
    pipeline_start = time.perf_counter()

    monitor.start()

    extraction_start = time.perf_counter()

    page_chunks = pymupdf4llm.to_markdown(
        str(input_path),
        page_chunks=True,
        use_ocr=False,
        write_images=False,
        embed_images=False,
        force_text=True,
        show_progress=True,
    )

    extraction_seconds = time.perf_counter() - extraction_start

    if not isinstance(page_chunks, list):
        monitor.stop()
        raise RuntimeError(
            "Expected PyMuPDF4LLM page_chunks=True to return a list."
        )

    total_characters = 0
    markdown_characters = 0
    markdown_tokens = 0
    blank_pages = 0

    with (
        markdown_path.open("w", encoding="utf-8") as markdown_file,
        jsonl_path.open("w", encoding="utf-8") as jsonl_file,
    ):
        for index, chunk in enumerate(page_chunks, start=1):
            page_number = chunk.get(
                "metadata",
                {},
            ).get("page_number", index)

            text = chunk.get("text", "")

            if not text.strip():
                blank_pages += 1

            total_characters += len(text)

            page_markdown = (
                f"\n\n<!-- PAGE {page_number} -->\n\n{text}"
            )

            page_token_count = len(
                tokenizer.encode(
                    page_markdown,
                    disallowed_special=(),
                )
            )

            markdown_tokens += page_token_count
            markdown_characters += len(page_markdown)

            markdown_file.write(page_markdown)

            record = {
                "document_id": document_id,
                "source_file": input_path.name,
                "parser": "pymupdf4llm",
                "parser_version": parser_version,
                "page_number": page_number,
                "tokenizer": TOKENIZER_NAME,
                "token_count": page_token_count,
                "text": text,
                "toc_items": chunk.get("toc_items", []),
                "page_boxes": chunk.get("page_boxes", []),
                "tables": chunk.get("tables", []),
                "metadata": chunk.get("metadata", {}),
            }

            jsonl_file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    default=json_default,
                )
            )
            jsonl_file.write("\n")

    pipeline_seconds = time.perf_counter() - pipeline_start
    resource_metrics = monitor.stop()

    markdown_bytes = markdown_path.stat().st_size
    jsonl_bytes = jsonl_path.stat().st_size

    extraction_pages_per_second = (
        page_count / extraction_seconds
        if extraction_seconds > 0
        else 0
    )

    pipeline_pages_per_second = (
        page_count / pipeline_seconds
        if pipeline_seconds > 0
        else 0
    )

    file_size_ratio = (
        input_bytes / markdown_bytes
        if markdown_bytes > 0
        else 0
    )

    tokens_per_page = (
        markdown_tokens / page_count
        if page_count > 0
        else 0
    )

    characters_per_token = (
        markdown_characters / markdown_tokens
        if markdown_tokens > 0
        else 0
    )

    virtual_memory = psutil.virtual_memory()

    metrics = {
        "benchmark": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        },
        "document": {
            "id": document_id,
            "file": input_path.name,
            "sha256": input_sha256,
            "pages": page_count,
            "input_size_mb": bytes_to_mb(input_bytes),
        },
        "parser": {
            "name": "pymupdf4llm",
            "version": parser_version,
            "mode": "cpu_baseline",
            "ocr_enabled": False,
            "images_exported": False,
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "logical_cpus": psutil.cpu_count(logical=True),
            "physical_cpus": psutil.cpu_count(logical=False),
            "memory_total_mb": bytes_to_mb(virtual_memory.total),
        },
        "processing": {
            "extraction_seconds": round(
                extraction_seconds,
                3,
            ),
            "pipeline_seconds": round(
                pipeline_seconds,
                3,
            ),
            "extraction_pages_per_second": round(
                extraction_pages_per_second,
                3,
            ),
            "pipeline_pages_per_second": round(
                pipeline_pages_per_second,
                3,
            ),
            "blank_pages": blank_pages,
            "extracted_characters": total_characters,
        },
        "resources": resource_metrics,
        "tokens": {
            "tokenizer": TOKENIZER_NAME,
            "full_markdown_tokens": markdown_tokens,
            "tokens_per_page": round(tokens_per_page, 2),
            "characters_per_token": round(
                characters_per_token,
                3,
            ),
        },
        "output": {
            "markdown_size_mb": bytes_to_mb(markdown_bytes),
            "jsonl_size_mb": bytes_to_mb(jsonl_bytes),
            "input_to_markdown_size_ratio": round(
                file_size_ratio,
                3,
            ),
        },
    }

    metrics_path.write_text(
        json.dumps(
            metrics,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("RESULT")
    print("=" * 72)
    print(f"Pages processed:       {page_count}")
    print(f"Extraction time:       {extraction_seconds:.3f} s")
    print(f"Pipeline time:         {pipeline_seconds:.3f} s")
    print(
        "Extraction pages/s:    "
        f"{extraction_pages_per_second:.3f}"
    )
    print(
        "Pipeline pages/s:      "
        f"{pipeline_pages_per_second:.3f}"
    )
    print(f"Average CPU:           {resource_metrics['average_cpu_percent']:.2f}%")
    print(f"Peak CPU:              {resource_metrics['peak_cpu_percent']:.2f}%")
    print(f"Peak RAM:              {resource_metrics['peak_rss_mb']:.3f} MB")
    print(f"Blank pages:           {blank_pages}")
    print(f"Characters extracted:  {total_characters}")
    print(f"Markdown tokens:       {markdown_tokens}")
    print(f"Tokens/page:           {tokens_per_page:.2f}")
    print(f"Markdown:              {markdown_path}")
    print(f"JSONL:                 {jsonl_path}")
    print(f"Metrics:               {metrics_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


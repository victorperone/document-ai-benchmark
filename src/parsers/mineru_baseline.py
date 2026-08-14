from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import psutil
import tiktoken
import torch


TOKENIZER_NAME = "o200k_base"
MONITOR_INTERVAL_SECONDS = 0.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MinerU benchmark adapter."
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)

    parser.add_argument(
        "--method",
        choices=["txt", "auto", "ocr"],
        default="txt",
    )

    parser.add_argument(
        "--threads",
        type=int,
        default=psutil.cpu_count(logical=False)
        or psutil.cpu_count(logical=True)
        or 1,
    )

    return parser.parse_args()


def bytes_to_mb(value: int | float) -> float:
    return round(value / (1024 * 1024), 3)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


class ResourceMonitor:
    def __init__(
        self,
        interval: float = MONITOR_INTERVAL_SECONDS,
    ) -> None:
        self.interval = interval
        self.process = psutil.Process(os.getpid())
        self.logical_cpus = (
            psutil.cpu_count(logical=True) or 1
        )

        self.cpu_samples: list[float] = []
        self.memory_samples: list[int] = []

        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

        # Process.cpu_percent(interval=None) is stateful.
        # Keep the same Process objects between samples so child
        # processes are not repeatedly measured as a "first call".
        self.processes: dict[int, psutil.Process] = {
            self.process.pid: self.process
        }

        self.primed_pids: set[int] = set()

    def _discover_processes(self) -> None:
        discovered: dict[int, psutil.Process] = {
            self.process.pid: self.process
        }

        try:
            children = self.process.children(
                recursive=True
            )
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            children = []

        for child in children:
            existing = self.processes.get(
                child.pid
            )

            discovered[child.pid] = (
                existing
                if existing is not None
                else child
            )

        self.processes = discovered

    def _prime_new_processes(self) -> None:
        self._discover_processes()

        for pid, process in list(
            self.processes.items()
        ):
            if pid in self.primed_pids:
                continue

            try:
                process.cpu_percent(
                    interval=None
                )
                self.primed_pids.add(pid)
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                self.processes.pop(
                    pid,
                    None,
                )

    def _sample(self) -> None:
        self._discover_processes()

        cpu_percent = 0.0
        rss_bytes = 0

        for pid, process in list(
            self.processes.items()
        ):
            try:
                rss_bytes += (
                    process.memory_info().rss
                )

                if pid not in self.primed_pids:
                    process.cpu_percent(
                        interval=None
                    )
                    self.primed_pids.add(pid)
                    continue

                cpu_percent += (
                    process.cpu_percent(
                        interval=None
                    )
                )

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                self.processes.pop(
                    pid,
                    None,
                )
                self.primed_pids.discard(pid)

        self.cpu_samples.append(
            cpu_percent
        )

        self.memory_samples.append(
            rss_bytes
        )

    def _run(self) -> None:
        while not self.stop_event.wait(
            self.interval
        ):
            self._sample()

    def start(self) -> None:
        self._prime_new_processes()

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
            statistics.mean(
                self.cpu_samples
            )
            if self.cpu_samples
            else 0.0
        )

        peak_cpu = max(
            self.cpu_samples,
            default=0.0,
        )

        peak_memory = max(
            self.memory_samples,
            default=0,
        )

        return {
            "average_cpu_percent": round(
                average_cpu,
                2,
            ),
            "peak_cpu_percent": round(
                peak_cpu,
                2,
            ),
            "average_cpu_system_capacity_percent": round(
                min(
                    average_cpu
                    / self.logical_cpus,
                    100.0,
                ),
                2,
            ),
            "peak_cpu_system_capacity_percent": round(
                min(
                    peak_cpu
                    / self.logical_cpus,
                    100.0,
                ),
                2,
            ),
            "peak_rss_mb": bytes_to_mb(
                peak_memory
            ),
        }


def find_output_file(
    root: Path,
    exact_name: str,
) -> Path:
    matches = list(
        root.rglob(exact_name)
    )

    if not matches:
        raise FileNotFoundError(
            f"MinerU output not found: {exact_name}"
        )

    if len(matches) > 1:
        raise RuntimeError(
            f"Multiple MinerU outputs found for "
            f"{exact_name}: {matches}"
        )

    return matches[0]


def print_log_tail(
    path: Path,
    lines: int = 80,
) -> None:
    if not path.exists():
        return

    content = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    print()
    print("=" * 72)
    print("MINERU LOG TAIL")
    print("=" * 72)

    for line in content[-lines:]:
        print(line)


def main() -> int:
    args = parse_args()

    input_path = Path(args.input)
    base_output_dir = Path(args.output_dir)

    if not input_path.is_file():
        print(
            f"ERROR: Input file does not exist: "
            f"{input_path}",
            file=sys.stderr,
        )
        return 1

    document_id = input_path.stem

    output_dir = (
        base_output_dir / document_id
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_output_dir = output_dir / "_mineru_raw"

    if raw_output_dir.exists():
        shutil.rmtree(raw_output_dir)

    raw_output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    markdown_path = output_dir / "document.md"
    jsonl_path = output_dir / "document.jsonl"
    metrics_path = output_dir / "metrics.json"
    log_path = output_dir / "mineru.log"

    mineru_version = metadata.version("mineru")
    tokenizer = tiktoken.get_encoding(
        TOKENIZER_NAME
    )

    environment = os.environ.copy()

    environment["MINERU_INTRA_OP_NUM_THREADS"] = str(
        args.threads
    )

    environment["OMP_NUM_THREADS"] = str(
        args.threads
    )

    environment["MKL_NUM_THREADS"] = str(
        args.threads
    )

    command = [
        "mineru",
        "-p",
        str(input_path),
        "-o",
        str(raw_output_dir),
        "-b",
        "pipeline",
        "-m",
        args.method,
        "-f",
        "true",
        "-t",
        "true",
    ]

    ocr_policy = {
        "txt": "disabled",
        "auto": "automatic",
        "ocr": "forced",
    }[args.method]

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK")
    print("=" * 72)
    print("Parser:       MinerU")
    print(f"Version:      {mineru_version}")
    print(f"Input:        {input_path}")
    print(f"Output:       {output_dir}")
    print("Backend:      pipeline")
    print(f"Method:       {args.method}")
    print(f"OCR policy:   {ocr_policy}")
    print(f"Threads:      {args.threads}")
    print("Tables:       enabled")
    print("Formulas:     enabled")
    print("Device:       CPU")
    print(f"Tokenizer:    {TOKENIZER_NAME}")
    print("=" * 72)

    monitor = ResourceMonitor()

    pipeline_start = time.perf_counter()
    monitor.start()

    extraction_start = time.perf_counter()

    with log_path.open(
        "w",
        encoding="utf-8",
    ) as log_file:
        process = subprocess.run(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=environment,
            text=True,
            check=False,
        )

    extraction_seconds = (
        time.perf_counter() - extraction_start
    )

    if process.returncode != 0:
        resource_metrics = monitor.stop()

        print(
            f"ERROR: MinerU exited with code "
            f"{process.returncode}",
            file=sys.stderr,
        )

        print_log_tail(log_path)

        return process.returncode

    normalization_start = time.perf_counter()

    source_markdown = find_output_file(
        raw_output_dir,
        f"{document_id}.md",
    )

    content_list_path = find_output_file(
        raw_output_dir,
        f"{document_id}_content_list.json",
    )

    middle_path = find_output_file(
        raw_output_dir,
        f"{document_id}_middle.json",
    )

    markdown = source_markdown.read_text(
        encoding="utf-8",
        errors="replace",
    )

    content_list = json.loads(
        content_list_path.read_text(
            encoding="utf-8"
        )
    )

    middle = json.loads(
        middle_path.read_text(
            encoding="utf-8"
        )
    )

    page_count = len(
        middle.get("pdf_info", [])
    )

    if page_count == 0:
        page_indexes = [
            item.get("page_idx")
            for item in content_list
            if isinstance(
                item.get("page_idx"),
                int,
            )
        ]

        page_count = (
            max(page_indexes) + 1
            if page_indexes
            else 0
        )

    shutil.copyfile(
        source_markdown,
        markdown_path,
    )

    grouped_items: dict[int, list[dict]] = (
        defaultdict(list)
    )

    content_types: Counter[str] = Counter()

    for item in content_list:
        item_type = str(
            item.get("type", "unknown")
        )

        content_types[item_type] += 1

        page_idx = item.get("page_idx")

        if isinstance(page_idx, int):
            grouped_items[page_idx].append(
                item
            )

    with jsonl_path.open(
        "w",
        encoding="utf-8",
    ) as jsonl_file:
        for page_idx in range(page_count):
            record = {
                "document_id": document_id,
                "source_file": input_path.name,
                "parser": "mineru",
                "parser_version": mineru_version,
                "backend": "pipeline",
                "method": args.method,
                "page_number": page_idx + 1,
                "items": grouped_items.get(
                    page_idx,
                    [],
                ),
            }

            jsonl_file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
            )
            jsonl_file.write("\n")

    markdown_tokens = len(
        tokenizer.encode(
            markdown,
            disallowed_special=(),
        )
    )

    normalization_seconds = (
        time.perf_counter()
        - normalization_start
    )

    pipeline_seconds = (
        time.perf_counter()
        - pipeline_start
    )

    resource_metrics = monitor.stop()

    input_bytes = input_path.stat().st_size
    markdown_bytes = markdown_path.stat().st_size
    jsonl_bytes = jsonl_path.stat().st_size

    pages_per_second = (
        page_count / extraction_seconds
        if extraction_seconds > 0
        else 0
    )

    pipeline_pages_per_second = (
        page_count / pipeline_seconds
        if pipeline_seconds > 0
        else 0
    )

    tokens_per_page = (
        markdown_tokens / page_count
        if page_count > 0
        else 0
    )

    size_ratio = (
        input_bytes / markdown_bytes
        if markdown_bytes > 0
        else 0
    )

    virtual_memory = psutil.virtual_memory()

    metrics = {
        "benchmark": {
            "timestamp_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "schema_version": 1,
        },
        "document": {
            "id": document_id,
            "file": input_path.name,
            "sha256": calculate_sha256(
                input_path
            ),
            "pages": page_count,
            "input_size_mb": bytes_to_mb(
                input_bytes
            ),
        },
        "parser": {
            "name": "mineru",
            "version": mineru_version,
            "backend": "pipeline",
            "method": args.method,
            "ocr_policy": ocr_policy,
            "ocr_enabled": (
                args.method != "txt"
            ),
            "table_structure_enabled": True,
            "formula_enabled": True,
        },
        "accelerator": {
            "device_requested": "cpu",
            "device_resolved": "cpu",
            "threads": args.threads,
            "torch_version": torch.__version__,
            "cuda_available": (
                torch.cuda.is_available()
            ),
        },
        "environment": {
            "python_version": (
                platform.python_version()
            ),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "logical_cpus": psutil.cpu_count(
                logical=True
            ),
            "physical_cpus": psutil.cpu_count(
                logical=False
            ),
            "memory_total_mb": bytes_to_mb(
                virtual_memory.total
            ),
        },
        "processing": {
            "extraction_seconds": round(
                extraction_seconds,
                3,
            ),
            "normalization_seconds": round(
                normalization_seconds,
                3,
            ),
            "pipeline_seconds": round(
                pipeline_seconds,
                3,
            ),
            "extraction_pages_per_second": round(
                pages_per_second,
                3,
            ),
            "pipeline_pages_per_second": round(
                pipeline_pages_per_second,
                3,
            ),
            "extracted_characters": len(
                markdown
            ),
            "exit_code": process.returncode,
        },
        "resources": {
            "monitor": "psutil_process_tree_cached_v2",
            **resource_metrics,
        },
        "content": {
            "element_counts": dict(
                sorted(content_types.items())
            ),
            "tables_detected": int(
                content_types.get("table", 0)
            ),
            "pictures_detected": int(
                content_types.get("image", 0)
            ),
            "charts_detected": int(
                content_types.get("chart", 0)
            ),
        },
        "tokens": {
            "tokenizer": TOKENIZER_NAME,
            "full_markdown_tokens": (
                markdown_tokens
            ),
            "tokens_per_page": round(
                tokens_per_page,
                2,
            ),
        },
        "output": {
            "markdown_size_mb": bytes_to_mb(
                markdown_bytes
            ),
            "jsonl_size_mb": bytes_to_mb(
                jsonl_bytes
            ),
            "input_to_markdown_size_ratio": round(
                size_ratio,
                3,
            ),
            "raw_output_retained": True,
            "log_file": "mineru.log",
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
    print(
        f"Extraction time:       "
        f"{extraction_seconds:.3f} s"
    )
    print(
        f"Normalization time:    "
        f"{normalization_seconds:.3f} s"
    )
    print(
        f"Pipeline time:         "
        f"{pipeline_seconds:.3f} s"
    )
    print(
        f"Extraction pages/s:    "
        f"{pages_per_second:.3f}"
    )
    print(
        f"Pipeline pages/s:      "
        f"{pipeline_pages_per_second:.3f}"
    )
    print(
        f"Average CPU:           "
        f"{resource_metrics['average_cpu_system_capacity_percent']:.2f}%"
    )
    print(
        f"Peak CPU:              "
        f"{resource_metrics['peak_cpu_system_capacity_percent']:.2f}%"
    )
    print(
        f"Peak RAM:              "
        f"{resource_metrics['peak_rss_mb']:.3f} MB"
    )
    print(
        f"Tables detected:       "
        f"{metrics['content']['tables_detected']}"
    )
    print(
        f"Pictures detected:     "
        f"{metrics['content']['pictures_detected']}"
    )
    print(
        f"Charts detected:       "
        f"{metrics['content']['charts_detected']}"
    )
    print(
        f"Markdown tokens:       "
        f"{markdown_tokens}"
    )
    print(
        f"Tokens/page:           "
        f"{tokens_per_page:.2f}"
    )
    print(f"Markdown:              {markdown_path}")
    print(f"JSONL:                 {jsonl_path}")
    print(f"Metrics:               {metrics_path}")
    print(f"Log:                   {log_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

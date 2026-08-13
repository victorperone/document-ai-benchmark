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
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import psutil
import tiktoken
import torch
from docling.datamodel.accelerator_options import (
    AcceleratorDevice,
    AcceleratorOptions,
)
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
)
from docling.datamodel.settings import settings
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
)


TOKENIZER_NAME = "o200k_base"
MONITOR_INTERVAL_SECONDS = 0.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Docling baseline parser for the document AI benchmark."
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)

    parser.add_argument(
        "--device",
        choices=["cpu", "cuda", "auto"],
        default="cpu",
    )

    parser.add_argument(
        "--threads",
        type=int,
        default=os.cpu_count() or 1,
    )

    return parser.parse_args()


def bytes_to_mb(value: int | float) -> float:
    return round(value / (1024 * 1024), 3)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def normalize_device(device: str) -> AcceleratorDevice:
    if device == "cpu":
        return AcceleratorDevice.CPU

    if device == "cuda":
        return AcceleratorDevice.CUDA

    return AcceleratorDevice.AUTO


def effective_device(requested: str) -> str:
    if requested == "cpu":
        return "cpu"

    if requested == "cuda":
        return "cuda"

    return "cuda" if torch.cuda.is_available() else "cpu"


class ResourceMonitor:
    def __init__(
        self,
        interval: float = MONITOR_INTERVAL_SECONDS,
    ) -> None:
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
            processes.extend(
                self.process.children(recursive=True)
            )
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            pass

        return processes

    def _prime_cpu_counters(self) -> None:
        for process in self._process_tree():
            try:
                process.cpu_percent(interval=None)
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                pass

    def _sample(self) -> None:
        cpu_percent = 0.0
        rss_bytes = 0

        for process in self._process_tree():
            try:
                cpu_percent += process.cpu_percent(
                    interval=None
                )
                rss_bytes += process.memory_info().rss
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
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
                    average_cpu / self.logical_cpus,
                    100.0,
                ),
                2,
            ),
            "peak_cpu_system_capacity_percent": round(
                min(
                    peak_cpu / self.logical_cpus,
                    100.0,
                ),
                2,
            ),
            "peak_rss_mb": bytes_to_mb(
                peak_memory
            ),
        }


def count_page_items(page_document) -> dict[str, int]:
    counts: Counter[str] = Counter()

    for item, _level in page_document.iterate_items():
        label = getattr(item, "label", None)

        if label is None:
            key = type(item).__name__
        else:
            key = getattr(label, "value", str(label))

        counts[str(key)] += 1

    return dict(sorted(counts.items()))


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

    document_id = input_path.stem

    output_dir = (
        base_output_dir
        / document_id
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    markdown_path = (
        output_dir / "document.md"
    )

    jsonl_path = (
        output_dir / "document.jsonl"
    )

    metrics_path = (
        output_dir / "metrics.json"
    )

    input_bytes = input_path.stat().st_size
    input_sha256 = calculate_sha256(input_path)

    docling_version = metadata.version("docling")

    requested_device = args.device
    resolved_device = effective_device(
        requested_device
    )

    accelerator_options = AcceleratorOptions(
        num_threads=args.threads,
        device=normalize_device(
            requested_device
        ),
    )

    pipeline_options = PdfPipelineOptions()

    pipeline_options.accelerator_options = (
        accelerator_options
    )

    pipeline_options.do_ocr = False

    pipeline_options.do_table_structure = True

    pipeline_options.table_structure_options.mode = (
        TableFormerMode.ACCURATE
    )

    pipeline_options.do_picture_classification = False
    pipeline_options.do_picture_description = False
    pipeline_options.enable_remote_services = False

    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
            )
        },
    )

    print("=" * 72)
    print("DOCUMENT AI BENCHMARK")
    print("=" * 72)
    print("Parser:       Docling")
    print(f"Version:      {docling_version}")
    print(f"Input:        {input_path}")
    print(f"Output:       {output_dir}")
    print(f"Device:       {requested_device}")
    print(f"Resolved:     {resolved_device}")
    print(f"Threads:      {args.threads}")
    print("OCR:          disabled")
    print("Tables:       enabled / accurate")
    print("Pictures:     detected, not described")
    print("Remote API:   disabled")
    print(f"Tokenizer:    {TOKENIZER_NAME}")
    print("=" * 72)

    tokenizer = tiktoken.get_encoding(
        TOKENIZER_NAME
    )

    monitor = ResourceMonitor()

    pipeline_start = time.perf_counter()
    monitor.start()

    initialization_start = time.perf_counter()

    converter.initialize_pipeline(
        InputFormat.PDF
    )

    initialization_seconds = (
        time.perf_counter()
        - initialization_start
    )

    extraction_start = time.perf_counter()

    conversion_result = converter.convert(
        input_path,
        raises_on_error=True,
    )

    extraction_seconds = (
        time.perf_counter()
        - extraction_start
    )

    document = conversion_result.document

    serialization_start = time.perf_counter()

    page_count = document.num_pages()

    total_tokens = 0
    total_characters = 0
    blank_pages = 0
    global_element_counts: Counter[str] = Counter()

    with (
        markdown_path.open(
            "w",
            encoding="utf-8",
        ) as markdown_file,
        jsonl_path.open(
            "w",
            encoding="utf-8",
        ) as jsonl_file,
    ):
        for page_number in range(
            1,
            page_count + 1,
        ):
            page_document = document.filter(
                page_nrs={page_number}
            )

            page_markdown = (
                page_document.export_to_markdown()
            )

            page_output = (
                f"\n\n<!-- PAGE {page_number} -->\n\n"
                f"{page_markdown}"
            )

            page_tokens = len(
                tokenizer.encode(
                    page_output,
                    disallowed_special=(),
                )
            )

            if not page_markdown.strip():
                blank_pages += 1

            total_tokens += page_tokens
            total_characters += len(
                page_markdown
            )

            element_counts = count_page_items(
                page_document
            )

            global_element_counts.update(
                element_counts
            )

            markdown_file.write(
                page_output
            )

            record = {
                "document_id": document_id,
                "source_file": input_path.name,
                "parser": "docling",
                "parser_version": docling_version,
                "page_number": page_number,
                "tokenizer": TOKENIZER_NAME,
                "token_count": page_tokens,
                "element_counts": element_counts,
                "markdown": page_markdown,
            }

            jsonl_file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
            )

            jsonl_file.write("\n")

    serialization_seconds = (
        time.perf_counter()
        - serialization_start
    )

    pipeline_seconds = (
        time.perf_counter()
        - pipeline_start
    )

    resource_metrics = monitor.stop()

    markdown_bytes = (
        markdown_path.stat().st_size
    )

    jsonl_bytes = (
        jsonl_path.stat().st_size
    )

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
        total_tokens / page_count
        if page_count > 0
        else 0
    )

    size_ratio = (
        input_bytes / markdown_bytes
        if markdown_bytes > 0
        else 0
    )

    conversion_status = getattr(
        conversion_result.status,
        "value",
        str(conversion_result.status),
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
            "sha256": input_sha256,
            "pages": page_count,
            "input_size_mb": bytes_to_mb(
                input_bytes
            ),
        },
        "parser": {
            "name": "docling",
            "version": docling_version,
            "mode": "cpu_baseline",
            "ocr_enabled": False,
            "table_structure_enabled": True,
            "table_mode": "accurate",
            "picture_description_enabled": False,
            "remote_services_enabled": False,
        },
        "accelerator": {
            "device_requested": requested_device,
            "device_resolved": resolved_device,
            "threads": args.threads,
            "torch_version": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "torch_compile_enabled": settings.inference.compile_torch_models,
        },
        "environment": {
            "python_version": platform.python_version(),
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
            "initialization_seconds": round(
                initialization_seconds,
                3,
            ),
            "extraction_seconds": round(
                extraction_seconds,
                3,
            ),
            "serialization_seconds": round(
                serialization_seconds,
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
            "blank_pages": blank_pages,
            "extracted_characters": total_characters,
            "conversion_status": conversion_status,
        },
        "resources": resource_metrics,
        "content": {
            "element_counts": dict(
                sorted(
                    global_element_counts.items()
                )
            ),
            "tables_detected": int(
                global_element_counts.get(
                    "table",
                    0,
                )
            ),
            "pictures_detected": int(
                global_element_counts.get(
                    "picture",
                    0,
                )
            ),
        },
        "tokens": {
            "tokenizer": TOKENIZER_NAME,
            "full_markdown_tokens": total_tokens,
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
        f"Initialization time:   "
        f"{initialization_seconds:.3f} s"
    )
    print(
        f"Extraction time:       "
        f"{extraction_seconds:.3f} s"
    )
    print(
        f"Serialization time:    "
        f"{serialization_seconds:.3f} s"
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
        f"Markdown tokens:       "
        f"{total_tokens}"
    )
    print(
        f"Tokens/page:           "
        f"{tokens_per_page:.2f}"
    )
    print(f"Markdown:              {markdown_path}")
    print(f"JSONL:                 {jsonl_path}")
    print(f"Metrics:               {metrics_path}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

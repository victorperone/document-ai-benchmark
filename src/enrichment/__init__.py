"""Visual enrichment sub-package.

Provides the data contracts and worker infrastructure used to run
OCR (PaddleOCR) and visual description (SmolVLM) on image regions
extracted from parsed documents.

Modules:
    visual_contract: Dataclasses for the request/response protocol.
    visual_worker: Child-process entry point that owns the model lifecycles.
    visual_worker_client: Parent-side client that spawns and communicates
        with the worker process.
"""

"""Visual enrichment worker process.

Launched as a child process by VisualWorkerClient. Loads PaddleOCR and
SmolVLM once, then processes JSON-Lines requests from stdin and writes
JSON-Lines responses to stdout.

Protocol:
  stdin:  one JSON object per line — VisualRequest fields
  stdout: one JSON object per line — VisualResponse fields
  stderr: diagnostic messages only (never request/response data)

Image bytes (image_base64) are never written to disk, never logged,
and never included in any persistent output.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import traceback
from typing import Any


def _load_paddleocr(
    language: str,
    det_model_dir: str | None = None,
    rec_model_dir: str | None = None,
) -> Any:
    """Instantiate and return a PaddleOCR engine.

    When both model directories are supplied, the ``lang`` parameter is
    omitted so that the explicit paths are authoritative. When either
    directory is absent the language code is passed as a model-selection
    shortcut.

    Args:
        language: ISO 639-2/BCP-47 language code forwarded to PaddleOCR
            when explicit model paths are not fully specified (e.g. ``"pt"``).
        det_model_dir: Optional local directory containing the text-detection
            model. Must be paired with ``rec_model_dir`` to suppress the
            ``lang`` shortcut.
        rec_model_dir: Optional local directory containing the
            text-recognition model. Must be paired with ``det_model_dir``
            to suppress the ``lang`` shortcut.

    Returns:
        An initialised ``PaddleOCR`` instance ready for inference.
    """
    from paddleocr import PaddleOCR  # type: ignore[import]
    kwargs: dict[str, Any] = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    if det_model_dir:
        kwargs["text_detection_model_dir"] = det_model_dir
    if rec_model_dir:
        kwargs["text_recognition_model_dir"] = rec_model_dir
    # Explicit model directories identify the exact certified models. PaddleOCR
    # documents that lang/ocr_version are only model-selection shortcuts, so do
    # not pass them when both model locations are authoritative.
    if not (det_model_dir and rec_model_dir):
        kwargs["lang"] = language
    return PaddleOCR(**kwargs)


def _load_smolvlm(model_path: str) -> tuple[Any, Any]:
    """Load a SmolVLM vision-language model from a local directory.

    The model and processor are loaded in CPU-only, inference mode.
    ``local_files_only=True`` prevents any download attempts.

    Args:
        model_path: Local filesystem path to the pre-downloaded SmolVLM
            model directory (must contain ``config.json`` and weight files).

    Returns:
        A ``(processor, model)`` tuple where ``processor`` is the
        ``AutoProcessor`` and ``model`` is the ``AutoModelForImageTextToText``
        instance set to ``eval()`` mode on CPU.
    """
    from transformers import AutoProcessor, AutoModelForImageTextToText  # type: ignore[import]
    import torch  # type: ignore[import]

    processor = AutoProcessor.from_pretrained(
        model_path,
        local_files_only=True,
    )
    model = AutoModelForImageTextToText.from_pretrained(
        model_path,
        local_files_only=True,
        torch_dtype=torch.float32,
    )
    model.to("cpu")
    model.eval()
    return processor, model


def _run_ocr(ocr_engine: Any, image_bytes: bytes, language: str) -> str:
    """Run PaddleOCR on raw image bytes and return the extracted text.

    Converts the image to RGB before inference and walks multiple possible
    result shapes that PaddleOCR may return depending on version.

    Args:
        ocr_engine: An initialised ``PaddleOCR`` instance.
        image_bytes: Raw PNG (or other PIL-readable) image data.
        language: Language code used for logging/context; not forwarded
            to the engine at inference time.

    Returns:
        Recognised text lines joined by newlines. Empty string if no text
        is detected.
    """
    from PIL import Image  # type: ignore[import]
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    result = ocr_engine.predict(img)
    lines: list[str] = []
    for page_result in (result or []):
        rec_texts: Any = None
        if isinstance(page_result, dict):
            rec_texts = page_result.get("rec_texts")
        if rec_texts is None:
            try:
                rec_texts = page_result["rec_texts"]
            except (KeyError, TypeError, IndexError):
                pass
        if rec_texts is None:
            rec_texts = getattr(page_result, "rec_texts", None)
        if rec_texts is None:
            json_value = getattr(page_result, "json", None)
            if callable(json_value):
                json_value = json_value()
            if isinstance(json_value, dict):
                payload = json_value.get("res", json_value)
                if isinstance(payload, dict):
                    rec_texts = payload.get("rec_texts")
        rec_texts = rec_texts or []
        lines.extend(t for t in rec_texts if t and t.strip())
    return "\n".join(lines)


def _run_description(
    processor: Any,
    model: Any,
    image_bytes: bytes,
    prompt: str,
    model_path: str,
) -> str:
    """Generate a textual description of an image using SmolVLM.

    Applies the chat template, runs greedy decoding on CPU, and strips
    the input tokens from the output before decoding.

    Args:
        processor: ``AutoProcessor`` instance for SmolVLM.
        model: ``AutoModelForImageTextToText`` instance in eval mode.
        image_bytes: Raw image data to describe.
        prompt: Instruction text forwarded to the model.
        model_path: Model path string used only in the ``RuntimeError``
            message when the model returns an empty response.

    Returns:
        The generated description string (stripped of leading/trailing
        whitespace).

    Raises:
        RuntimeError: If the model returns an empty decoded string.
    """
    from PIL import Image  # type: ignore[import]
    import torch  # type: ignore[import]

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    input_text = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=False,
    )
    inputs = processor(
        text=input_text,
        images=[img],
        return_tensors="pt",
    )
    if hasattr(inputs, "to"):
        inputs = inputs.to("cpu")
    else:
        inputs = {
            key: value.to("cpu") if hasattr(value, "to") else value
            for key, value in inputs.items()
        }
    prompt_len = inputs["input_ids"].shape[1]
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=256,
            do_sample=False,
        )
    generated = output_ids[0][prompt_len:]
    text = processor.decode(generated, skip_special_tokens=True).strip()
    if not text:
        raise RuntimeError("SmolVLM returned empty response")
    return text


def _process_request(
    req: dict,
    ocr_engine: Any,
    smolvlm_processor: Any,
    smolvlm_model: Any,
    smolvlm_model_path: str,
    language: str,
) -> dict:
    """Process a single enrichment request dict and return a response dict.

    Runs OCR first; if OCR produces text, appends it to the prompt before
    calling the VLM so the model focuses on additional visual information
    rather than re-transcribing known text. Either step may fail
    independently — the response status is ``"error"`` only when both
    ``ocr_text`` and ``description`` remain empty after all attempts.

    Args:
        req: Decoded JSON object from stdin. Expected keys: ``request_id``,
            ``image_base64``, and optionally ``prompt``.
        ocr_engine: Initialised PaddleOCR instance.
        smolvlm_processor: SmolVLM processor.
        smolvlm_model: SmolVLM model in eval mode.
        smolvlm_model_path: Model directory path, included in the response
            for traceability.
        language: Language code forwarded to ``_run_ocr``.

    Returns:
        Dict matching the ``VisualResponse`` field layout, suitable for
        JSON serialisation and writing to stdout.
    """
    request_id = req.get("request_id", "")
    image_b64 = req.get("image_base64", "")
    prompt = req.get("prompt", "Descreva o conteúdo desta imagem de forma objetiva.")

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception as exc:
        return {
            "request_id": request_id,
            "status": "error",
            "ocr_text": "",
            "description": "",
            "ocr_engine": "paddleocr",
            "ocr_model": "",
            "description_engine": "smolvlm",
            "description_model": smolvlm_model_path,
            "error_detail": f"base64 decode failed: {exc}",
        }

    ocr_text = ""
    description = ""
    error_detail = ""

    try:
        ocr_text = _run_ocr(ocr_engine, image_bytes, language)
    except Exception as exc:
        error_detail += f"ocr: {exc}"

    try:
        effective_prompt = prompt
        if ocr_text.strip():
            effective_prompt += (
                "\n\nThe text below was already extracted by OCR. Do not "
                "transcribe or repeat it; describe only additional visual "
                "information:\n"
                + ocr_text.strip()[:2000]
            )
        description = _run_description(
            smolvlm_processor,
            smolvlm_model,
            image_bytes,
            effective_prompt,
            smolvlm_model_path,
        )
    except Exception as exc:
        sep = "; " if error_detail else ""
        error_detail += f"{sep}description: {exc}"

    status = "error" if (error_detail and not ocr_text and not description) else "success"

    return {
        "request_id": request_id,
        "status": status,
        "ocr_text": ocr_text,
        "description": description,
        "ocr_engine": "paddleocr",
        "ocr_model": "",
        "description_engine": "smolvlm",
        "description_model": smolvlm_model_path,
        "error_detail": error_detail,
    }


def main() -> None:
    """Entry point for the visual enrichment worker child process.

    Reads a JSON configuration object from the first stdin line, loads
    PaddleOCR and SmolVLM, signals readiness by writing
    ``{"status": "ready"}`` to stdout, then processes JSON-Lines requests
    in a loop until stdin is closed.

    Configuration keys (first stdin line):
        language: OCR language code (default ``"pt"``).
        smolvlm_model_path: Local path to the SmolVLM model directory.
        det_model_dir: Optional PaddleOCR detection model directory.
        rec_model_dir: Optional PaddleOCR recognition model directory.

    Exits with code 1 on configuration parse errors or model load failures,
    writing an ``{"status": "init_error", ...}`` JSON line to stdout first.
    """
    # Config arrives via first stdin line as JSON
    try:
        config_line = sys.stdin.readline()
        config = json.loads(config_line)
    except Exception as exc:
        print(json.dumps({"status": "init_error", "error": str(exc)}), flush=True)
        sys.exit(1)

    language = config.get("language", "pt")
    smolvlm_model_path = config.get("smolvlm_model_path", "")
    det_model_dir = config.get("det_model_dir") or None
    rec_model_dir = config.get("rec_model_dir") or None

    try:
        print(json.dumps({"status": "loading_ocr"}), flush=True)
        ocr_engine = _load_paddleocr(language, det_model_dir=det_model_dir, rec_model_dir=rec_model_dir)

        print(json.dumps({"status": "loading_vlm"}), flush=True)
        smolvlm_processor, smolvlm_model = _load_smolvlm(smolvlm_model_path)

        print(json.dumps({"status": "ready"}), flush=True)
    except Exception as exc:
        print(
            json.dumps({"status": "init_error", "error": traceback.format_exc()}),
            flush=True,
        )
        sys.exit(1)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"status": "parse_error", "error": str(exc)}), flush=True)
            continue

        response = _process_request(
            req,
            ocr_engine,
            smolvlm_processor,
            smolvlm_model,
            smolvlm_model_path,
            language,
        )
        # Never echo image_base64 back
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()

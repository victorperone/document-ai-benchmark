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

from __future__ import annotations

from typing import Any


def inventory_requires_content(inventory: dict[str, Any]) -> tuple[bool, str]:
    """Return the objective text expectation represented by a source inventory."""
    native = inventory.get("native_text") or {}
    images = inventory.get("images") or {}
    vector = inventory.get("vector_content") or {}
    positive_evidence = bool(
        int(native.get("characters") or 0) > 0
        or int(images.get("embedded_image_occurrences") or 0) > 0
        or int(vector.get("drawing_groups") or 0) > 0
    )
    measurements_complete = (
        images.get("measurement_complete", True) is not False
        and vector.get("measurement_complete", True) is not False
    )
    if positive_evidence:
        return True, "source inventory contains native text, embedded images, or vector content"
    if not measurements_complete:
        return True, "source inventory could not prove that the PDF is empty"
    return False, "source inventory proves no native text, embedded images, or vector content"

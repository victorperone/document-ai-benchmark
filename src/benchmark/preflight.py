"""Preflight check utilities for parser adapter self-tests.

Provides helpers for constructing and validating the standardised preflight
result dicts that parser adapters return before a benchmark run.  A preflight
result is a dict with ``schema_version``, ``parser``, ``profile``, ``ok``, and
a list of ``checks``.
"""

from __future__ import annotations

from typing import Any


VALID_STATUSES: frozenset[str] = frozenset(
    {
        "pass",
        "warn",
        "fail",
    }
)


def make_check(
    name: str,
    status: str,
    detail: str | None = None,
) -> dict[str, Any]:
    """Build a single preflight check record.

    Args:
        name: Short identifier for the check.
        status: Must be one of ``"pass"``, ``"warn"``, or ``"fail"``.
        detail: Optional human-readable explanation included when not
            ``None``.

    Returns:
        Dict with ``name`` and ``status``, plus ``detail`` when provided.

    Raises:
        ValueError: If *status* is not a valid value.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid preflight status: {status!r}. "
            f"Must be one of: {sorted(VALID_STATUSES)}"
        )

    check: dict[str, Any] = {
        "name": name,
        "status": status,
    }

    if detail is not None:
        check["detail"] = detail

    return check


def make_result(
    parser: str,
    profile: str,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a preflight result dict from a list of check records.

    Args:
        parser: Parser identifier.
        profile: Profile identifier.
        checks: List of check dicts produced by ``make_check``.

    Returns:
        Dict with ``schema_version`` (1), ``parser``, ``profile``, ``ok``
        (``True`` when no check has status ``"fail"``), and ``checks``.
    """
    ok = not any(
        c["status"] == "fail"
        for c in checks
    )

    return {
        "schema_version": 1,
        "parser": parser,
        "profile": profile,
        "ok": ok,
        "checks": checks,
    }


def validate_result(result: Any) -> None:
    """Assert that *result* is a structurally valid preflight result dict.

    Validates the presence of required fields, correct types, schema version,
    individual check structure, and that ``ok`` is consistent with the checks.

    Args:
        result: Object to validate (expected to be a ``dict``).

    Raises:
        TypeError: If *result* or any of its fields have an unexpected type.
        ValueError: If any required field is missing, the schema version is
            not 1, a check has an invalid status, or ``ok`` is inconsistent
            with the check list.
    """
    if not isinstance(result, dict):
        raise TypeError(
            "Preflight result must be a dict."
        )

    required = (
        "schema_version",
        "parser",
        "profile",
        "ok",
        "checks",
    )

    for field in required:
        if field not in result:
            raise ValueError(
                f"Preflight result missing field: {field!r}"
            )

    if result.get("schema_version") != 1:
        raise ValueError(
            "Unsupported preflight schema_version: "
            f"{result.get('schema_version')!r}"
        )

    if not isinstance(result.get("checks"), list):
        raise TypeError(
            "Preflight checks must be a list."
        )

    if not isinstance(result["ok"], bool):
        raise TypeError("'ok' must be bool.")

    if not isinstance(result["parser"], str):
        raise TypeError("'parser' must be str.")

    if not isinstance(result["profile"], str):
        raise TypeError("'profile' must be str.")

    for check in result["checks"]:
        if not isinstance(check, dict):
            raise TypeError(
                "Each check must be a dict."
            )

        if "name" not in check or "status" not in check:
            raise ValueError(
                "Each check must have 'name' and 'status'."
            )

        if check["status"] not in VALID_STATUSES:
            raise ValueError(
                f"Invalid check status: {check['status']!r}"
            )

    computed_ok = not any(
        check["status"] == "fail"
        for check in result["checks"]
    )

    if result["ok"] != computed_ok:
        raise ValueError(
            "Preflight 'ok' value is inconsistent with checks."
        )

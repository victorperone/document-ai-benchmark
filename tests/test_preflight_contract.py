"""
Unit tests for src.benchmark.preflight contract.

Validates make_check(), make_result(), validate_result()
without Docker, models or inference.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmark.preflight import make_check, make_result, validate_result


class TestMakeCheck(unittest.TestCase):

    def test_invalid_status_raises(self) -> None:
        with self.assertRaises(ValueError):
            make_check("a", "maybe")

    def test_valid_statuses_accepted(self) -> None:
        for status in ("pass", "warn", "fail"):
            check = make_check("name", status)
            self.assertEqual(check["status"], status)

    def test_detail_optional(self) -> None:
        check = make_check("x", "pass")
        self.assertNotIn("detail", check)

    def test_detail_included_when_provided(self) -> None:
        check = make_check("x", "pass", "some detail")
        self.assertEqual(check["detail"], "some detail")


class TestMakeResult(unittest.TestCase):

    def test_pass_and_warn_produces_ok_true(self) -> None:
        checks = [
            make_check("a", "pass"),
            make_check("b", "warn"),
        ]
        result = make_result("pymupdf", "native", checks)
        self.assertTrue(result["ok"])
        self.assertEqual(result["schema_version"], 1)

    def test_any_fail_produces_ok_false(self) -> None:
        checks = [
            make_check("a", "pass"),
            make_check("b", "fail", "broken"),
        ]
        result = make_result("pymupdf", "native", checks)
        self.assertFalse(result["ok"])

    def test_all_pass_produces_ok_true(self) -> None:
        checks = [make_check("a", "pass"), make_check("b", "pass")]
        result = make_result("pymupdf", "native", checks)
        self.assertTrue(result["ok"])

    def test_empty_checks_produces_ok_true(self) -> None:
        result = make_result("pymupdf", "native", [])
        self.assertTrue(result["ok"])


class TestValidateResult(unittest.TestCase):

    def _valid(self, ok: bool, status: str = "pass") -> dict:
        checks = [] if ok else [make_check("x", "fail")]
        if ok and status != "pass":
            checks = [make_check("x", status)]
        return make_result("pymupdf", "native", checks)

    def test_valid_pass_warn_accepted(self) -> None:
        checks = [make_check("a", "pass"), make_check("b", "warn")]
        result = make_result("pymupdf", "native", checks)
        validate_result(result)  # must not raise

    def test_valid_fail_accepted(self) -> None:
        checks = [make_check("a", "fail")]
        result = make_result("pymupdf", "native", checks)
        validate_result(result)  # must not raise

    def test_ok_true_with_fail_check_raises(self) -> None:
        """ok=True but a check has status=fail is incoherent."""
        result = {
            "schema_version": 1,
            "parser": "pymupdf",
            "profile": "native",
            "ok": True,
            "checks": [{"name": "x", "status": "fail"}],
        }
        with self.assertRaises(ValueError):
            validate_result(result)

    def test_ok_false_with_only_pass_checks_raises(self) -> None:
        """ok=False but no fail checks is incoherent."""
        result = {
            "schema_version": 1,
            "parser": "pymupdf",
            "profile": "native",
            "ok": False,
            "checks": [{"name": "x", "status": "pass"}],
        }
        with self.assertRaises(ValueError):
            validate_result(result)

    def test_ok_not_bool_raises(self) -> None:
        result = {
            "schema_version": 1,
            "parser": "pymupdf",
            "profile": "native",
            "ok": 1,  # int, not bool
            "checks": [],
        }
        with self.assertRaises(TypeError):
            validate_result(result)

    def test_parser_not_string_raises(self) -> None:
        result = {
            "schema_version": 1,
            "parser": 123,
            "profile": "native",
            "ok": True,
            "checks": [],
        }
        with self.assertRaises(TypeError):
            validate_result(result)

    def test_profile_not_string_raises(self) -> None:
        result = {
            "schema_version": 1,
            "parser": "pymupdf",
            "profile": None,
            "ok": True,
            "checks": [],
        }
        with self.assertRaises(TypeError):
            validate_result(result)

    def test_invalid_schema_version_raises(self) -> None:
        result = {
            "schema_version": 2,
            "parser": "pymupdf",
            "profile": "native",
            "ok": True,
            "checks": [],
        }
        with self.assertRaises(ValueError):
            validate_result(result)

    def test_invalid_check_status_raises(self) -> None:
        result = {
            "schema_version": 1,
            "parser": "pymupdf",
            "profile": "native",
            "ok": True,
            "checks": [{"name": "x", "status": "unknown"}],
        }
        with self.assertRaises(ValueError):
            validate_result(result)

    def test_not_dict_raises(self) -> None:
        with self.assertRaises(TypeError):
            validate_result("not a dict")

    def test_missing_field_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_result({"schema_version": 1, "parser": "p", "ok": True})


if __name__ == "__main__":
    unittest.main()

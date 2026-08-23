"""
Regression tests for PaddleOCR local model-directory resolution.

These tests deliberately avoid importing paddleocr_v2 normally because the
adapter imports PaddleOCR/PPStructureV3 at module import time.

Instead, they extract the production resolver and its alias table from the
adapter AST. This keeps the regression suite free of Docker, PaddleOCR model
downloads, and parser inference.
"""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ADAPTER_PATH = (
    ROOT
    / "src"
    / "parsers"
    / "paddleocr_v2.py"
)

SOURCE = ADAPTER_PATH.read_text(
    encoding="utf-8"
)

TREE = ast.parse(
    SOURCE,
    filename=str(ADAPTER_PATH),
)


def _find_assignment(
    name: str,
) -> ast.Assign:
    for node in TREE.body:
        if not isinstance(
            node,
            ast.Assign,
        ):
            continue

        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == name
            ):
                return node

    raise AssertionError(
        f"Assignment {name!r} not found "
        f"in {ADAPTER_PATH}"
    )


def _find_function(
    name: str,
) -> ast.FunctionDef:
    for node in TREE.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return node

    raise AssertionError(
        f"Function {name!r} not found "
        f"in {ADAPTER_PATH}"
    )


def _load_resolver():
    """
    Compile only the production alias table and resolver.

    No PaddleOCR or benchmark runtime modules are imported.
    """
    aliases_node = _find_assignment(
        "MODEL_DIRECTORY_CANDIDATES"
    )

    resolver_node = _find_function(
        "_resolve_model_path"
    )

    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="pathlib",
                names=[
                    ast.alias(
                        name="Path",
                    )
                ],
                level=0,
            ),
            aliases_node,
            resolver_node,
        ],
        type_ignores=[],
    )

    ast.fix_missing_locations(
        module
    )

    namespace: dict[str, object] = {}

    exec(
        compile(
            module,
            filename=str(
                ADAPTER_PATH
            ),
            mode="exec",
        ),
        namespace,
    )

    return (
        namespace[
            "_resolve_model_path"
        ],
        namespace[
            "MODEL_DIRECTORY_CANDIDATES"
        ],
    )


def _called_function_names(
    function_name: str,
) -> list[str]:
    function = _find_function(
        function_name
    )

    names: list[str] = []

    for node in ast.walk(
        function
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        if isinstance(
            node.func,
            ast.Name,
        ):
            names.append(
                node.func.id
            )

    return names


class TestPaddleOCRModelDirectoryAliases(
    unittest.TestCase,
):
    @classmethod
    def setUpClass(
        cls,
    ) -> None:
        (
            resolve_model_path,
            aliases,
        ) = _load_resolver()

        cls.resolve_model_path = staticmethod(
            resolve_model_path
        )
        cls.aliases = aliases

    def test_chart_alias_contract(
        self,
    ) -> None:
        self.assertEqual(
            self.aliases[
                "PP-Chart2Table"
            ],
            (
                "PP-Chart2Table_safetensors",
                "PP-Chart2Table",
            ),
        )

    def test_chart_prefers_safetensors_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            safetensors = (
                root
                / "PP-Chart2Table_safetensors"
            )

            legacy = (
                root
                / "PP-Chart2Table"
            )

            safetensors.mkdir()
            legacy.mkdir()

            result = (
                self.resolve_model_path(
                    root,
                    "PP-Chart2Table",
                )
            )

            self.assertEqual(
                result,
                safetensors,
            )

    def test_chart_falls_back_to_legacy_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            legacy = (
                root
                / "PP-Chart2Table"
            )

            legacy.mkdir()

            result = (
                self.resolve_model_path(
                    root,
                    "PP-Chart2Table",
                )
            )

            self.assertEqual(
                result,
                legacy,
            )

    def test_missing_chart_returns_preferred_candidate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = (
                self.resolve_model_path(
                    root,
                    "PP-Chart2Table",
                )
            )

            self.assertEqual(
                result,
                (
                    root
                    / "PP-Chart2Table_safetensors"
                ),
            )

            self.assertFalse(
                result.exists()
            )

    def test_non_aliased_model_keeps_canonical_name(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            formula = (
                root
                / "PP-FormulaNet_plus-L"
            )

            formula.mkdir()

            result = (
                self.resolve_model_path(
                    root,
                    "PP-FormulaNet_plus-L",
                )
            )

            self.assertEqual(
                result,
                formula,
            )


class TestPaddleOCRModelResolverIntegration(
    unittest.TestCase,
):
    def test_runtime_resolution_uses_shared_resolver(
        self,
    ) -> None:
        calls = _called_function_names(
            "resolve_model_paths"
        )

        self.assertIn(
            "_resolve_model_path",
            calls,
        )

    def test_preflight_uses_shared_resolver(
        self,
    ) -> None:
        calls = _called_function_names(
            "preflight_profile"
        )

        self.assertIn(
            "_resolve_model_path",
            calls,
        )


if __name__ == "__main__":
    unittest.main()

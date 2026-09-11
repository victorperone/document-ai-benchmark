"""Native-Windows functional smoke test for the PyMuPDF parser (full_cpu_local_visual profile).

Runs only when BENCHMARK_WINDOWS_FUNCTIONAL=1; exercises the complete offline
inference pipeline via run_batch.py and validates output artefacts.
"""
from parser_tests.functional_deep_smoke import make_functional_test_case


PymupdfFunctionalDeepSmokeTests = make_functional_test_case(
    "pymupdf", "full_cpu_local_visual"
)

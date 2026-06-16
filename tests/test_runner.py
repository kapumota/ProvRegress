from pathlib import Path

from llmtestlab.models import TestStatus
from llmtestlab.runner import load_run_result, run_suite_file, write_run_result

ROOT = Path(__file__).resolve().parents[1]


def test_run_suite_file_passes_customer_support() -> None:
    result = run_suite_file(ROOT / "examples" / "customer_support" / "evals.yaml")
    assert result.summary.total == 3
    assert result.summary.passed == 3
    assert result.summary.failed == 0
    assert all(test.status == TestStatus.PASSED for test in result.tests)


def test_write_and_load_run_result(tmp_path: Path) -> None:
    result = run_suite_file(ROOT / "examples" / "invoice_extractor" / "evals.yaml")
    output = tmp_path / "results.json"
    write_run_result(result, output)
    loaded = load_run_result(output)
    assert loaded.suite == result.suite
    assert loaded.summary.passed == result.summary.passed

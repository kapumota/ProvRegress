from pathlib import Path

import pytest

from llmtestlab.evals import EvalsYamlError, load_evals_yaml
from llmtestlab.models import AppType

ROOT = Path(__file__).resolve().parents[1]


def test_load_customer_support_suite() -> None:
    suite = load_evals_yaml(ROOT / "examples" / "customer_support" / "evals.yaml")
    assert suite.suite == "customer-support-chatbot"
    assert suite.app_type == AppType.SIMPLE_CHATBOT
    assert "baseline" in suite.providers
    assert "candidate" in suite.providers
    assert len(suite.tests) == 3


def test_load_invoice_suite() -> None:
    suite = load_evals_yaml(ROOT / "examples" / "invoice_extractor" / "evals.yaml")
    assert suite.app_type == AppType.JSON_EXTRACTOR
    assert suite.tests[0].assertions[0].type == "json_valid"


def test_load_rag_suite() -> None:
    suite = load_evals_yaml(ROOT / "examples" / "rag_bot" / "evals.yaml")
    assert suite.app_type == AppType.BASIC_RAG
    assert suite.tests[0].required_sources == ["docs/refund_policy.md"]


@pytest.mark.parametrize(
    "filename",
    [
        "missing_candidate.yaml",
        "unknown_assertion.yaml",
        "duplicate_test_ids.yaml",
        "json_extractor_without_json_assertion.yaml",
    ],
)
def test_invalid_examples_fail(filename: str) -> None:
    with pytest.raises(EvalsYamlError):
        load_evals_yaml(ROOT / "examples" / "invalid" / filename)

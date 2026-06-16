import pytest

from llmtestlab.assertions import (
    assert_contains,
    assert_contains_any,
    assert_exact_match,
    assert_json_schema,
    assert_json_valid,
    assert_max_latency_ms,
    assert_not_contains,
    assert_regex,
    evaluate_assertion,
)
from llmtestlab.models import AssertionConfig, LLMOutput, Severity, TestCase


def make_test(assertion: AssertionConfig) -> TestCase:
    return TestCase(id="sample-001", input="Pregunta", assertions=[assertion])


def test_assert_contains_passes() -> None:
    assert assert_contains("Refunds are allowed within 30 days.", "30 days") is True


def test_assert_not_contains_passes() -> None:
    assert assert_not_contains("Refunds are allowed within 30 days.", "always allowed") is True


def test_assert_contains_any_passes() -> None:
    assert assert_contains_any("Exceptions require manager approval.", ["exception", "denied"]) is True


def test_assert_regex_passes() -> None:
    assert assert_regex('{"invoice_number":"INV-001"}', r'INV-[0-9]+') is True


def test_assert_exact_match_passes() -> None:
    assert assert_exact_match("OK", " OK ") is True


def test_assert_max_latency_ms_passes() -> None:
    assert assert_max_latency_ms(120, 5000) is True


def test_assert_json_valid_passes() -> None:
    assert assert_json_valid('{"invoice_number":"INV-001"}') is True


def test_assert_json_schema_passes() -> None:
    schema = {
        "type": "object",
        "required": ["invoice_number"],
        "properties": {"invoice_number": {"type": "string"}},
    }
    assert assert_json_schema('{"invoice_number":"INV-001"}', schema) is True


def test_contains_evaluator_passes() -> None:
    assertion = AssertionConfig(type="contains", value="30 days", severity=Severity.CRITICAL)
    output = LLMOutput(text="Refunds are allowed within 30 days.")
    result = evaluate_assertion(assertion, make_test(assertion), output)
    assert result.passed is True


def test_not_contains_evaluator_fails() -> None:
    assertion = AssertionConfig(type="not_contains", value="always allowed")
    output = LLMOutput(text="Refunds are always allowed.")
    result = evaluate_assertion(assertion, make_test(assertion), output)
    assert result.passed is False


def test_contains_any_evaluator_fails() -> None:
    assertion = AssertionConfig(type="contains_any", values=["exception", "manager approval"])
    output = LLMOutput(text="Refunds are available within 30 days.")
    result = evaluate_assertion(assertion, make_test(assertion), output)
    assert result.passed is False


def test_regex_evaluator_passes() -> None:
    assertion = AssertionConfig(type="regex", pattern=r"INV-[0-9]+")
    output = LLMOutput(text='{"invoice_number":"INV-001"}')
    result = evaluate_assertion(assertion, make_test(assertion), output)
    assert result.passed is True


def test_exact_match_evaluator_fails() -> None:
    assertion = AssertionConfig(type="exact_match", value="OK")
    output = LLMOutput(text="OK.")
    result = evaluate_assertion(assertion, make_test(assertion), output)
    assert result.passed is False


def test_max_latency_ms_evaluator_fails() -> None:
    assertion = AssertionConfig(type="max_latency_ms", value=100)
    output = LLMOutput(text="Respuesta", latency_ms=150)
    result = evaluate_assertion(assertion, make_test(assertion), output)
    assert result.passed is False


def test_json_valid_evaluator_fails() -> None:
    assertion = AssertionConfig(type="json_valid")
    output = LLMOutput(text="no es json")
    result = evaluate_assertion(assertion, make_test(assertion), output)
    assert result.passed is False


def test_json_schema_evaluator_fails_when_required_field_is_missing() -> None:
    assertion = AssertionConfig(
        type="json_schema",
        schema_={
            "type": "object",
            "required": ["invoice_number"],
            "properties": {"invoice_number": {"type": "string"}},
        },
    )
    output = LLMOutput(text='{"vendor":"ACME"}')
    result = evaluate_assertion(assertion, make_test(assertion), output)
    assert result.passed is False


def test_assert_json_schema_raises_for_invalid_output() -> None:
    schema = {"type": "object"}
    with pytest.raises(Exception):
        assert_json_schema("no es json", schema)

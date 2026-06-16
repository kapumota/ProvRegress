from llmtestlab.assertions import evaluate_assertion
from llmtestlab.models import AssertionConfig, LLMOutput, Severity, TestCase


def test_contains_passes() -> None:
    assertion = AssertionConfig(type="contains", value="30 days", severity=Severity.CRITICAL)
    test = TestCase(id="sample-001", input="Pregunta", assertions=[assertion])
    output = LLMOutput(text="Refunds are allowed within 30 days.")
    result = evaluate_assertion(assertion, test, output)
    assert result.passed is True


def test_not_contains_fails() -> None:
    assertion = AssertionConfig(type="not_contains", value="always allowed")
    test = TestCase(id="sample-001", input="Pregunta", assertions=[assertion])
    output = LLMOutput(text="Refunds are always allowed.")
    result = evaluate_assertion(assertion, test, output)
    assert result.passed is False


def test_json_schema_passes() -> None:
    assertion = AssertionConfig(
        type="json_schema",
        schema_={"required": ["invoice_number"], "properties": {"invoice_number": {"type": "string"}}},
    )
    test = TestCase(id="invoice-001", input="Factura", assertions=[assertion])
    output = LLMOutput(text='{"invoice_number":"INV-001"}')
    result = evaluate_assertion(assertion, test, output)
    assert result.passed is True

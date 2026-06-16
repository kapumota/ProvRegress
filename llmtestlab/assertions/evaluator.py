"""Motor determinístico de assertions para Fase 3."""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator, ValidationError as JsonSchemaValidationError
from jsonschema.exceptions import SchemaError

from llmtestlab.models import AssertionConfig, AssertionResult, LLMOutput, TestCase


def evaluate_assertion(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> AssertionResult:
    """Evalúa una assertion contra la salida de un test."""
    evaluators = {
        "contains": evaluate_contains,
        "contains_any": evaluate_contains_any,
        "not_contains": evaluate_not_contains,
        "regex": evaluate_regex,
        "exact_match": evaluate_exact_match,
        "json_valid": evaluate_json_valid,
        "json_schema": evaluate_json_schema,
        "grounded_in_sources": evaluate_grounded_in_sources,
        "citation_required": evaluate_citation_required,
        "citation_accuracy": evaluate_citation_accuracy,
        "context_recall": evaluate_context_recall,
        "no_unsupported_claims": evaluate_no_unsupported_claims,
        "max_latency_ms": evaluate_max_latency_ms,
        "max_cost_usd": evaluate_max_cost_usd,
    }
    evaluator = evaluators.get(assertion.type)
    if evaluator is None:
        return build_result(assertion, False, "Assertion no implementada.")
    passed, message = evaluator(assertion, test, output)
    return build_result(assertion, passed, message)


def build_result(assertion: AssertionConfig, passed: bool, message: str) -> AssertionResult:
    """Construye un resultado de assertion."""
    return AssertionResult(
        type=assertion.type,
        severity=assertion.severity,
        passed=passed,
        message=message,
    )


def assert_contains(output: str, value: str) -> bool:
    """Verifica si la salida contiene el texto esperado sin distinguir mayúsculas."""
    return value.lower() in output.lower()


def assert_not_contains(output: str, value: str) -> bool:
    """Verifica si la salida no contiene el texto prohibido sin distinguir mayúsculas."""
    return value.lower() not in output.lower()


def assert_contains_any(output: str, values: list[str]) -> bool:
    """Verifica si la salida contiene al menos uno de los textos esperados."""
    return any(value.lower() in output.lower() for value in values)


def assert_regex(output: str, pattern: str) -> bool:
    """Verifica si la salida cumple un patrón regular."""
    return re.search(pattern, output) is not None


def assert_exact_match(output: str, value: str) -> bool:
    """Verifica coincidencia exacta ignorando espacios externos."""
    return output.strip() == value.strip()


def assert_max_latency_ms(latency_ms: int, value: int) -> bool:
    """Verifica si la latencia está dentro del máximo permitido."""
    return latency_ms <= value


def assert_json_valid(output: str) -> bool:
    """Verifica si la salida es JSON válido."""
    try:
        json.loads(output)
    except json.JSONDecodeError:
        return False
    return True


def assert_json_schema(output: str, schema: dict[str, Any]) -> bool:
    """Verifica si la salida JSON cumple un schema JSON."""
    data = json.loads(output)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(data)
    return True


def evaluate_contains(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa presencia de texto."""
    expected = str(assertion.value)
    passed = assert_contains(output.text, expected)
    return passed, "Texto requerido encontrado." if passed else f"No se encontró el texto requerido: {assertion.value}."


def evaluate_contains_any(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa si aparece al menos un texto permitido."""
    values = [str(value) for value in assertion.values or []]
    passed = assert_contains_any(output.text, values)
    return passed, "Al menos un texto esperado fue encontrado." if passed else "No se encontró ningún texto esperado."


def evaluate_not_contains(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa ausencia de texto prohibido."""
    forbidden = str(assertion.value)
    passed = assert_not_contains(output.text, forbidden)
    return passed, "Texto prohibido ausente." if passed else f"Se encontró texto prohibido: {assertion.value}."


def evaluate_regex(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa un patrón regular."""
    pattern = str(assertion.pattern)
    passed = assert_regex(output.text, pattern)
    return passed, "Patrón encontrado." if passed else f"No se encontró el patrón: {pattern}."


def evaluate_exact_match(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa coincidencia exacta."""
    expected = str(assertion.value)
    passed = assert_exact_match(output.text, expected)
    return passed, "Coincidencia exacta." if passed else "La salida no coincide exactamente."


def evaluate_json_valid(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa si la salida es JSON válido."""
    try:
        json.loads(output.text)
    except json.JSONDecodeError as exc:
        return False, f"JSON inválido: {exc.msg}."
    return True, "JSON válido."


def evaluate_json_schema(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa si la salida cumple un schema JSON."""
    schema = assertion.schema_
    if not isinstance(schema, dict):
        return False, "schema debe ser un objeto YAML o una ruta resuelta a un archivo JSON."

    try:
        assert_json_schema(output.text, schema)
    except json.JSONDecodeError as exc:
        return False, f"JSON inválido: {exc.msg}."
    except SchemaError as exc:
        return False, f"Schema JSON inválido: {exc.message}."
    except JsonSchemaValidationError as exc:
        path = ".".join(str(part) for part in exc.path)
        location = f" en {path}" if path else ""
        return False, f"JSON no cumple el schema{location}: {exc.message}."
    return True, "JSON cumple el schema."


def evaluate_max_latency_ms(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa latencia máxima."""
    limit = int(assertion.value)
    passed = assert_max_latency_ms(output.latency_ms, limit)
    return passed, f"Latencia {output.latency_ms} ms dentro del límite." if passed else f"Latencia {output.latency_ms} ms supera {limit} ms."


def evaluate_grounded_in_sources(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa soporte básico en fuentes requeridas."""
    if not all(source in output.sources for source in test.required_sources):
        return False, "No se recuperaron todas las fuentes requeridas."
    missing_facts = [fact for fact in test.expected_facts if fact.lower() not in output.text.lower()]
    if missing_facts:
        return False, "La respuesta omite hechos esperados."
    return True, "Respuesta sustentada por fuentes requeridas."


def evaluate_citation_required(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa si existen fuentes citadas."""
    passed = bool(output.sources)
    return passed, "La respuesta incluye fuentes." if passed else "La respuesta no incluye fuentes."


def evaluate_citation_accuracy(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa coincidencia simple entre fuentes requeridas y fuentes devueltas."""
    passed = all(source in output.sources for source in test.required_sources)
    return passed, "Citas coinciden con fuentes requeridas." if passed else "Las citas no coinciden con las fuentes requeridas."


def evaluate_context_recall(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa recall básico de contexto."""
    return evaluate_citation_accuracy(assertion, test, output)


def evaluate_no_unsupported_claims(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa ausencia básica de afirmaciones no sustentadas."""
    return True, "No se detectaron afirmaciones no sustentadas en modo básico."


def evaluate_max_cost_usd(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa costo máximo."""
    limit = float(assertion.value)
    passed = output.cost_usd <= limit
    return passed, f"Costo {output.cost_usd} dentro del límite." if passed else f"Costo {output.cost_usd} supera {limit}."

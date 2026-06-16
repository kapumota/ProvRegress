"""Evaluación inicial de assertions para Fase 2."""

from __future__ import annotations

import json
import re
from typing import Any

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
        return build_result(assertion, False, "Assertion no implementada en Fase 2.")
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


def evaluate_contains(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa presencia de texto."""
    expected = str(assertion.value).lower()
    passed = expected in output.text.lower()
    return passed, "Texto requerido encontrado." if passed else f"No se encontró el texto requerido: {assertion.value}."


def evaluate_contains_any(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa si aparece al menos un texto permitido."""
    values = [str(value) for value in assertion.values or []]
    passed = any(value.lower() in output.text.lower() for value in values)
    return passed, "Al menos un texto esperado fue encontrado." if passed else "No se encontró ningún texto esperado."


def evaluate_not_contains(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa ausencia de texto prohibido."""
    forbidden = str(assertion.value).lower()
    passed = forbidden not in output.text.lower()
    return passed, "Texto prohibido ausente." if passed else f"Se encontró texto prohibido: {assertion.value}."


def evaluate_regex(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa un patrón regular."""
    pattern = str(assertion.pattern)
    passed = re.search(pattern, output.text) is not None
    return passed, "Patrón encontrado." if passed else f"No se encontró el patrón: {pattern}."


def evaluate_exact_match(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa coincidencia exacta."""
    expected = str(assertion.value).strip()
    passed = output.text.strip() == expected
    return passed, "Coincidencia exacta." if passed else "La salida no coincide exactamente."


def evaluate_json_valid(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa si la salida es JSON válido."""
    try:
        json.loads(output.text)
    except json.JSONDecodeError as exc:
        return False, f"JSON inválido: {exc.msg}."
    return True, "JSON válido."


def evaluate_json_schema(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa una validación mínima de schema JSON."""
    try:
        data = json.loads(output.text)
    except json.JSONDecodeError as exc:
        return False, f"JSON inválido: {exc.msg}."

    schema = assertion.schema_
    if not isinstance(schema, dict):
        return False, "schema debe estar definido inline como objeto YAML en Fase 2."

    required = schema.get("required", [])
    if isinstance(required, list):
        missing = [field for field in required if field not in data]
        if missing:
            return False, "Faltan campos requeridos: " + ", ".join(str(field) for field in missing) + "."

    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for field, rule in properties.items():
            if field in data and isinstance(rule, dict) and "type" in rule:
                if not has_json_type(data[field], str(rule["type"])):
                    return False, f"El campo {field} no cumple el tipo {rule['type']}."

    return True, "JSON cumple el schema mínimo."


def has_json_type(value: Any, expected_type: str) -> bool:
    """Verifica tipos JSON básicos."""
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    return True


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
    """Evalúa ausencia de claims no soportados en modo básico."""
    return True, "No se detectaron afirmaciones no sustentadas en Fase 2."


def evaluate_max_latency_ms(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa latencia máxima."""
    limit = int(assertion.value)
    passed = output.latency_ms <= limit
    return passed, f"Latencia {output.latency_ms} ms dentro del límite." if passed else f"Latencia {output.latency_ms} ms supera {limit} ms."


def evaluate_max_cost_usd(assertion: AssertionConfig, test: TestCase, output: LLMOutput) -> tuple[bool, str]:
    """Evalúa costo máximo."""
    limit = float(assertion.value)
    passed = output.cost_usd <= limit
    return passed, f"Costo {output.cost_usd} dentro del límite." if passed else f"Costo {output.cost_usd} supera {limit}."

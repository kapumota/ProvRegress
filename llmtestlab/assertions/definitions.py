"""Contrato declarativo de aserciones disponibles en Fase 1.

Esta fase solo valida configuración. La ejecución real de cada aserción se implementará en Fase 3.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AssertionRule:
    """Describe los campos esperados para un tipo de assertion."""

    name: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    requires_threshold: bool = False
    requires_value: bool = False
    requires_values: bool = False
    requires_positive_integer_value: bool = False


TEXT_ASSERTION_TYPES = {
    "contains",
    "contains_any",
    "not_contains",
    "regex",
    "exact_match",
    "semantic_similarity",
    "answer_correctness",
    "relevance",
}

STRUCTURED_ASSERTION_TYPES = {
    "json_valid",
    "json_schema",
}

RAG_ASSERTION_TYPES = {
    "grounded_in_sources",
    "citation_required",
    "citation_accuracy",
    "context_recall",
    "no_unsupported_claims",
}

PERFORMANCE_ASSERTION_TYPES = {
    "max_latency_ms",
    "max_cost_usd",
}

ASSERTION_TYPES = (
    TEXT_ASSERTION_TYPES
    | STRUCTURED_ASSERTION_TYPES
    | RAG_ASSERTION_TYPES
    | PERFORMANCE_ASSERTION_TYPES
)

ASSERTION_RULES: dict[str, AssertionRule] = {
    "contains": AssertionRule(
        name="contains",
        required_fields=("value",),
        optional_fields=("severity",),
        requires_value=True,
    ),
    "contains_any": AssertionRule(
        name="contains_any",
        required_fields=("values",),
        optional_fields=("severity",),
        requires_values=True,
    ),
    "not_contains": AssertionRule(
        name="not_contains",
        required_fields=("value",),
        optional_fields=("severity",),
        requires_value=True,
    ),
    "regex": AssertionRule(
        name="regex",
        required_fields=("pattern",),
        optional_fields=("severity",),
    ),
    "exact_match": AssertionRule(
        name="exact_match",
        required_fields=("value",),
        optional_fields=("severity",),
        requires_value=True,
    ),
    "semantic_similarity": AssertionRule(
        name="semantic_similarity",
        required_fields=("threshold",),
        optional_fields=("severity",),
        requires_threshold=True,
    ),
    "answer_correctness": AssertionRule(
        name="answer_correctness",
        required_fields=("threshold",),
        optional_fields=("severity",),
        requires_threshold=True,
    ),
    "relevance": AssertionRule(
        name="relevance",
        required_fields=("threshold",),
        optional_fields=("severity",),
        requires_threshold=True,
    ),
    "json_valid": AssertionRule(
        name="json_valid",
        required_fields=(),
        optional_fields=("severity",),
    ),
    "json_schema": AssertionRule(
        name="json_schema",
        required_fields=("schema",),
        optional_fields=("severity",),
    ),
    "grounded_in_sources": AssertionRule(
        name="grounded_in_sources",
        required_fields=("threshold",),
        optional_fields=("severity",),
        requires_threshold=True,
    ),
    "citation_required": AssertionRule(
        name="citation_required",
        required_fields=(),
        optional_fields=("severity",),
    ),
    "citation_accuracy": AssertionRule(
        name="citation_accuracy",
        required_fields=("threshold",),
        optional_fields=("severity",),
        requires_threshold=True,
    ),
    "context_recall": AssertionRule(
        name="context_recall",
        required_fields=("threshold",),
        optional_fields=("severity",),
        requires_threshold=True,
    ),
    "no_unsupported_claims": AssertionRule(
        name="no_unsupported_claims",
        required_fields=("threshold",),
        optional_fields=("severity",),
        requires_threshold=True,
    ),
    "max_latency_ms": AssertionRule(
        name="max_latency_ms",
        required_fields=("value",),
        optional_fields=("severity",),
        requires_positive_integer_value=True,
    ),
    "max_cost_usd": AssertionRule(
        name="max_cost_usd",
        required_fields=("value",),
        optional_fields=("severity",),
    ),
}

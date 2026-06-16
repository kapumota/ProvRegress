"""Carga, validación y escritura del formato evals.yaml."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from llmtestlab.models import AppType, AssertionConfig, EvaluationSuite, TestCase


class EvalsYamlError(ValueError):
    """Error de configuración de evals.yaml."""


ASSERTION_TYPES = {
    "contains",
    "contains_any",
    "not_contains",
    "regex",
    "exact_match",
    "json_valid",
    "json_schema",
    "semantic_similarity",
    "answer_correctness",
    "relevance",
    "grounded_in_sources",
    "citation_required",
    "citation_accuracy",
    "context_recall",
    "no_unsupported_claims",
    "max_latency_ms",
    "max_cost_usd",
}

TEXT_ASSERTION_TYPES = {"contains", "contains_any", "not_contains", "regex", "exact_match"}
STRUCTURED_ASSERTION_TYPES = {"json_valid", "json_schema"}
RAG_ASSERTION_TYPES = {
    "grounded_in_sources",
    "citation_required",
    "citation_accuracy",
    "context_recall",
    "no_unsupported_claims",
}
SEMANTIC_ASSERTION_TYPES = {"semantic_similarity", "answer_correctness", "relevance"}

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def load_evals_yaml(path: Path | str) -> EvaluationSuite:
    """Lee, parsea y valida un archivo evals.yaml."""
    yaml_path = Path(path)
    data = load_yaml_mapping(yaml_path)
    suite = parse_evaluation_suite(data)
    resolve_schema_references(suite, yaml_path.parent)
    errors = validate_evaluation_suite(suite)
    if errors:
        joined_errors = "\n".join(f"- {error}" for error in errors)
        raise EvalsYamlError(f"El archivo evals.yaml no es válido:\n{joined_errors}")
    return suite


def load_yaml_mapping(path: Path | str) -> dict[str, Any]:
    """Carga un YAML y exige que la raíz sea un objeto."""
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise EvalsYamlError(f"No se encontró el archivo: {yaml_path}")

    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EvalsYamlError(f"El YAML tiene un error de sintaxis: {exc}") from exc

    if not isinstance(data, dict):
        raise EvalsYamlError("El archivo evals.yaml debe contener un objeto YAML en la raíz.")
    return data


def parse_evaluation_suite(data: dict[str, Any]) -> EvaluationSuite:
    """Convierte un diccionario YAML en una suite tipada."""
    try:
        return EvaluationSuite.model_validate(data)
    except ValidationError as exc:
        raise EvalsYamlError(format_pydantic_error(exc)) from exc


def resolve_schema_references(suite: EvaluationSuite, base_dir: Path) -> None:
    """Resuelve schemas JSON declarados como ruta relativa al evals.yaml."""
    for test in suite.tests:
        for assertion in test.assertions:
            if assertion.type == "json_schema" and isinstance(assertion.schema_, str):
                schema_path = resolve_safe_relative_path(base_dir, assertion.schema_)
                assertion.schema_ = load_json_schema(schema_path)


def resolve_safe_relative_path(base_dir: Path, raw_path: str) -> Path:
    """Resuelve una ruta relativa sin permitir rutas absolutas ni traversal."""
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise EvalsYamlError("Las rutas absolutas no están permitidas en schema.")
    resolved_base = base_dir.resolve()
    resolved_candidate = (base_dir / candidate).resolve()
    if resolved_base != resolved_candidate and resolved_base not in resolved_candidate.parents:
        raise EvalsYamlError("La ruta de schema debe estar dentro del directorio del evals.yaml.")
    return resolved_candidate


def load_json_schema(path: Path) -> dict[str, Any]:
    """Carga un schema JSON desde archivo."""
    if not path.exists():
        raise EvalsYamlError(f"No se encontró el schema JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalsYamlError(f"El schema JSON no es válido: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise EvalsYamlError("El schema JSON debe contener un objeto en la raíz.")
    return data


def validate_evaluation_suite(suite: EvaluationSuite) -> list[str]:
    """Devuelve errores de validación de negocio para la suite."""
    errors: list[str] = []
    errors.extend(validate_suite_header(suite))
    errors.extend(validate_providers(suite))
    errors.extend(validate_tests(suite))
    errors.extend(validate_app_type_rules(suite))
    return errors


def validate_suite_header(suite: EvaluationSuite) -> list[str]:
    """Valida campos de cabecera."""
    errors: list[str] = []
    if not suite.suite.strip():
        errors.append("suite no puede estar vacío.")
    elif not SLUG_PATTERN.match(suite.suite):
        errors.append("suite debe usar solo minúsculas, números, guiones y guiones bajos.")
    if not suite.version.strip():
        errors.append("version no puede estar vacío.")
    return errors


def validate_providers(suite: EvaluationSuite) -> list[str]:
    """Valida providers obligatorios y campos básicos."""
    errors: list[str] = []
    if "baseline" not in suite.providers:
        errors.append("providers debe incluir baseline.")
    if "candidate" not in suite.providers:
        errors.append("providers debe incluir candidate.")
    for name, provider in suite.providers.items():
        if not provider.model.strip():
            errors.append(f"El provider {name} debe definir model.")
        if not provider.prompt.strip():
            errors.append(f"El provider {name} debe definir prompt.")
        if provider.temperature is not None and provider.temperature < 0:
            errors.append(f"temperature del provider {name} no puede ser negativo.")
        if provider.max_tokens is not None and provider.max_tokens <= 0:
            errors.append(f"max_tokens del provider {name} debe ser positivo.")
    return errors


def validate_tests(suite: EvaluationSuite) -> list[str]:
    """Valida ids, inputs y assertions."""
    errors: list[str] = []
    if not suite.tests:
        return ["tests debe incluir al menos un caso de prueba."]

    seen_ids: set[str] = set()
    for test in suite.tests:
        if not test.id.strip():
            errors.append("Cada test debe tener id no vacío.")
        elif not SLUG_PATTERN.match(test.id):
            errors.append(f"El test {test.id} debe tener un id tipo slug.")
        elif test.id in seen_ids:
            errors.append(f"El test {test.id} está duplicado.")
        else:
            seen_ids.add(test.id)

        if not test.input.strip():
            errors.append(f"El test {test.id or '<sin-id>'} debe tener input no vacío.")
        if not test.assertions:
            errors.append(f"El test {test.id or '<sin-id>'} debe tener al menos una assertion.")
        for assertion in test.assertions:
            errors.extend(validate_assertion(assertion, test))
    return errors


def validate_assertion(assertion: AssertionConfig, test: TestCase) -> list[str]:
    """Valida campos requeridos por tipo de assertion."""
    errors: list[str] = []
    context = f"test {test.id or '<sin-id>'}"

    if assertion.type not in ASSERTION_TYPES:
        return [f"Aserción desconocida en {context}: {assertion.type}."]

    if assertion.threshold is not None and not 0 <= assertion.threshold <= 1:
        errors.append(f"La assertion {assertion.type} en {context} requiere threshold entre 0 y 1.")

    if assertion.type in {"contains", "not_contains", "exact_match"}:
        if not isinstance(assertion.value, str) or not assertion.value.strip():
            errors.append(f"La assertion {assertion.type} en {context} requiere value como texto no vacío.")

    if assertion.type == "contains_any":
        if not isinstance(assertion.values, list) or not assertion.values:
            errors.append(f"La assertion contains_any en {context} requiere values como lista no vacía.")
        elif not all(isinstance(value, str) and value.strip() for value in assertion.values):
            errors.append(f"La assertion contains_any en {context} requiere values de texto no vacío.")

    if assertion.type == "regex":
        if not isinstance(assertion.pattern, str) or not assertion.pattern.strip():
            errors.append(f"La assertion regex en {context} requiere pattern como texto no vacío.")
        else:
            try:
                re.compile(assertion.pattern)
            except re.error as exc:
                errors.append(f"La assertion regex en {context} tiene pattern inválido: {exc}.")

    if assertion.type in {"max_latency_ms", "max_cost_usd"}:
        if assertion.value is None:
            errors.append(f"La assertion {assertion.type} en {context} requiere value.")
        elif isinstance(assertion.value, bool) or not isinstance(assertion.value, int | float):
            errors.append(f"La assertion {assertion.type} en {context} requiere un número.")
        elif assertion.value < 0:
            errors.append(f"La assertion {assertion.type} en {context} requiere un valor no negativo.")

    if assertion.type == "json_schema" and assertion.schema_ is None:
        errors.append(f"La assertion json_schema en {context} requiere schema.")

    return errors


def validate_app_type_rules(suite: EvaluationSuite) -> list[str]:
    """Valida reglas mínimas según tipo de aplicación."""
    errors: list[str] = []
    for test in suite.tests:
        assertion_types = {assertion.type for assertion in test.assertions}
        if suite.app_type == AppType.SIMPLE_CHATBOT and not assertion_types & TEXT_ASSERTION_TYPES:
            errors.append(f"El test {test.id} de chatbot simple requiere al menos una assertion textual.")
        if suite.app_type == AppType.JSON_EXTRACTOR and not assertion_types & STRUCTURED_ASSERTION_TYPES:
            errors.append(f"El test {test.id} de json_extractor requiere json_valid o json_schema.")
        if suite.app_type == AppType.BASIC_RAG:
            if not assertion_types & RAG_ASSERTION_TYPES:
                errors.append(f"El test {test.id} de basic_rag requiere al menos una assertion RAG.")
            if assertion_types & RAG_ASSERTION_TYPES and not test.required_sources:
                errors.append(f"El test {test.id} usa assertions RAG y requiere required_sources.")
        if "semantic_similarity" in assertion_types and not test.expected_answer:
            errors.append(f"El test {test.id} usa semantic_similarity y requiere expected_answer.")
    return errors


def format_pydantic_error(exc: ValidationError) -> str:
    """Convierte errores de Pydantic en texto estable para CLI."""
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", []))
        message = error.get("msg", "error de validación")
        messages.append(f"{location}: {message}")
    return "El archivo evals.yaml no es válido:\n" + "\n".join(f"- {message}" for message in messages)


def build_example_suite(profile: str) -> EvaluationSuite:
    """Construye una suite de ejemplo para uno de los perfiles soportados."""
    builders = {
        "customer_support": build_customer_support_suite,
        "invoice_extractor": build_invoice_extractor_suite,
        "rag_bot": build_rag_bot_suite,
    }
    if profile not in builders:
        raise EvalsYamlError("Perfil no soportado. Usa customer_support, invoice_extractor o rag_bot.")
    return builders[profile]()


def build_base_providers() -> dict[str, dict[str, Any]]:
    """Crea providers de ejemplo para baseline y candidate."""
    return {
        "baseline": {
            "model": "gpt-4.1-mini",
            "prompt": "prompts/v1.txt",
            "provider": "mock",
        },
        "candidate": {
            "model": "gpt-4.1-mini",
            "prompt": "prompts/v2.txt",
            "provider": "mock",
        },
    }


def build_customer_support_suite() -> EvaluationSuite:
    """Crea una suite mínima para chatbot simple."""
    data = {
        "suite": "customer-support-chatbot",
        "app_type": "simple_chatbot",
        "version": "0.3.0",
        "providers": build_base_providers(),
        "tests": [
            {
                "id": "refund-policy-001",
                "input": "Can I get a refund after 45 days?",
                "expected_facts": ["Refunds are allowed within 30 days"],
                "metadata": {"mock_output": "Refunds are allowed within 30 days with exceptions."},
                "assertions": [
                    {"type": "contains", "value": "30 days", "severity": "critical"},
                    {"type": "contains_any", "values": ["exception", "manager approval"], "severity": "high"},
                    {"type": "not_contains", "value": "refunds are always allowed", "severity": "critical"},
                    {"type": "max_latency_ms", "value": 5000, "severity": "medium"},
                ],
            }
        ],
    }
    return parse_evaluation_suite(data)


def build_invoice_extractor_suite() -> EvaluationSuite:
    """Crea una suite mínima para extractor JSON."""
    data = {
        "suite": "invoice-json-extractor",
        "app_type": "json_extractor",
        "version": "0.3.0",
        "providers": build_base_providers(),
        "tests": [
            {
                "id": "invoice-001",
                "input": "Extrae JSON de esta factura: Proveedor ACME, total 125.50 USD.",
                "metadata": {"mock_output": '{"provider":"ACME","total":125.50}'},
                "assertions": [
                    {"type": "json_valid", "severity": "critical"},
                    {
                        "type": "json_schema",
                        "severity": "critical",
                        "schema": {
                            "type": "object",
                            "required": ["provider", "total"],
                            "properties": {
                                "provider": {"type": "string"},
                                "total": {"type": "number"},
                            },
                        },
                    },
                ],
            }
        ],
    }
    return parse_evaluation_suite(data)


def build_rag_bot_suite() -> EvaluationSuite:
    """Crea una suite mínima para RAG básico."""
    data = {
        "suite": "customer-support-rag",
        "app_type": "basic_rag",
        "version": "0.3.0",
        "providers": build_base_providers(),
        "tests": [
            {
                "id": "rag-policy-001",
                "input": "What is the refund window?",
                "expected_facts": ["The refund window is 30 days"],
                "required_sources": ["docs/refund_policy.md"],
                "metadata": {
                    "mock_output": "The refund window is 30 days.",
                    "mock_sources": ["docs/refund_policy.md"],
                },
                "assertions": [
                    {"type": "contains", "value": "30 days", "severity": "critical"},
                    {"type": "grounded_in_sources", "threshold": 0.85, "severity": "high"},
                    {"type": "citation_accuracy", "threshold": 0.9, "severity": "high"},
                ],
            }
        ],
    }
    return parse_evaluation_suite(data)


def suite_to_dict(suite: EvaluationSuite) -> dict[str, Any]:
    """Convierte una suite a un diccionario apto para YAML."""
    return suite.model_dump(mode="json", by_alias=True, exclude_none=True)


def write_evals_yaml(suite: EvaluationSuite, path: Path | str) -> None:
    """Escribe una suite como evals.yaml."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(suite_to_dict(suite), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def render_evals_summary(suite: EvaluationSuite, output_format: str = "text") -> str:
    """Renderiza un resumen corto de evals.yaml."""
    if output_format == "markdown":
        lines = [
            f"### Suite: {suite.suite}",
            "",
            "#### Tipo de aplicación",
            "",
            f"`{suite.app_type.value}`",
            "",
            "#### Tests",
            "",
        ]
        for test in suite.tests:
            lines.append(f"- `{test.id}` con {len(test.assertions)} assertions")
        return "\n".join(lines) + "\n"

    lines = [
        f"Suite: {suite.suite}",
        f"Tipo de aplicación: {suite.app_type.value}",
        f"Providers: {', '.join(suite.providers)}",
        "Tests:",
    ]
    for test in suite.tests:
        lines.append(f"- {test.id}: {len(test.assertions)} assertions")
    return "\n".join(lines) + "\n"


def render_evals_spec_markdown() -> str:
    """Renderiza la especificación mínima del YAML."""
    return """### Especificación de evals.yaml

#### Campos principales

`evals.yaml` define una suite de pruebas para aplicaciones LLM.

```yaml
suite: customer-support-rag
app_type: basic_rag
version: 0.3.0
providers:
  baseline:
    model: gpt-4.1-mini
    prompt: prompts/v1.txt
    provider: mock
  candidate:
    model: gpt-4.1-mini
    prompt: prompts/v2.txt
    provider: mock
tests:
  - id: refund-policy-001
    input: "Can I get a refund after 45 days?"
    assertions:
      - type: contains
        value: "30 days"
        severity: critical
```

#### Tipos de aplicación

`simple_chatbot`, `json_extractor` y `basic_rag`.

#### Severidades

`info`, `low`, `medium`, `high` y `critical`.

#### Assertions determinísticas

`contains`, `contains_any`, `not_contains`, `regex`, `exact_match`, `json_valid`, `json_schema`, `max_latency_ms` y `max_cost_usd`.

#### Assertions RAG básicas

`grounded_in_sources`, `citation_required`, `citation_accuracy`, `context_recall` y `no_unsupported_claims`.
"""

"""Modelo, parser y validador del formato evals.yaml.

La Fase 1 define el contrato de configuración. No ejecuta modelos ni aserciones todavía.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import re

import yaml

from llmtestlab.assertions.definitions import (
    ASSERTION_RULES,
    ASSERTION_TYPES,
    RAG_ASSERTION_TYPES,
    STRUCTURED_ASSERTION_TYPES,
    TEXT_ASSERTION_TYPES,
)


class AppType(str, Enum):
    """Tipos de aplicación soportados por la primera versión."""

    SIMPLE_CHATBOT = "simple_chatbot"
    JSON_EXTRACTOR = "json_extractor"
    BASIC_RAG = "basic_rag"


class Severity(str, Enum):
    """Niveles de severidad permitidos en una assertion."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ProviderConfig:
    """Configuración declarativa de un proveedor.

    Esta fase no llama modelos. Solo valida el contrato que usará el runner posterior.
    """

    model: str
    prompt: str
    provider: str = "openai-compatible"
    temperature: float | None = None
    max_tokens: int | None = None
    base_url: str | None = None


@dataclass(frozen=True)
class AssertionConfig:
    """Aserción declarada dentro de un caso de prueba."""

    type: str
    severity: Severity = Severity.HIGH
    value: Any | None = None
    values: list[Any] | None = None
    pattern: str | None = None
    threshold: float | None = None
    schema: Any | None = None


@dataclass(frozen=True)
class TestCase:
    """Caso de prueba de una suite LLM."""

    id: str
    input: str
    assertions: list[AssertionConfig]
    expected_answer: str | None = None
    expected_facts: list[str] = field(default_factory=list)
    required_sources: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationSuite:
    """Suite declarativa cargada desde evals.yaml."""

    suite: str
    app_type: AppType
    version: str
    providers: dict[str, ProviderConfig]
    tests: list[TestCase]
    metadata: dict[str, Any] = field(default_factory=dict)


class EvalsYamlError(ValueError):
    """Error de configuración de evals.yaml."""


TOP_LEVEL_FIELDS = {"suite", "app_type", "version", "providers", "tests", "metadata"}
PROVIDER_FIELDS = {"model", "prompt", "provider", "temperature", "max_tokens", "base_url"}
TEST_FIELDS = {
    "id",
    "input",
    "assertions",
    "expected_answer",
    "expected_facts",
    "required_sources",
    "metadata",
}
ASSERTION_FIELDS = {
    "type",
    "severity",
    "value",
    "values",
    "pattern",
    "threshold",
    "schema",
}


PROFILE_ALIASES = {
    "customer_support": AppType.SIMPLE_CHATBOT,
    "invoice_extractor": AppType.JSON_EXTRACTOR,
    "rag_bot": AppType.BASIC_RAG,
}


SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def load_evals_yaml(path: Path | str) -> EvaluationSuite:
    """Carga y valida un archivo evals.yaml."""
    data = load_evals_mapping(path)
    suite = parse_evaluation_suite(data)
    errors = validate_evaluation_suite(suite)
    if errors:
        joined_errors = "\n".join(f"- {error}" for error in errors)
        raise EvalsYamlError(f"El archivo evals.yaml no es válido:\n{joined_errors}")
    return suite


def load_evals_mapping(path: Path | str) -> dict[str, Any]:
    """Lee un archivo YAML y devuelve un diccionario."""
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise EvalsYamlError(f"No se encontró el archivo: {yaml_path}")

    try:
        loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EvalsYamlError(f"El YAML tiene un error de sintaxis: {exc}") from exc

    if not isinstance(loaded, dict):
        raise EvalsYamlError("El archivo evals.yaml debe contener un objeto YAML en la raíz.")

    return loaded


def parse_evaluation_suite(data: dict[str, Any]) -> EvaluationSuite:
    """Convierte un diccionario YAML en una suite tipada."""
    unknown_top_fields = sorted(set(data) - TOP_LEVEL_FIELDS)
    if unknown_top_fields:
        raise EvalsYamlError(
            "Campos no reconocidos en la raíz del YAML: " + ", ".join(unknown_top_fields)
        )

    try:
        app_type = AppType(str(data.get("app_type", "")))
    except ValueError as exc:
        allowed = ", ".join(app_type.value for app_type in AppType)
        raise EvalsYamlError(f"app_type debe ser uno de: {allowed}") from exc

    providers = parse_providers(data.get("providers"))
    tests = parse_tests(data.get("tests"))

    metadata = data.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise EvalsYamlError("metadata debe ser un objeto YAML.")

    return EvaluationSuite(
        suite=str(data.get("suite", "")),
        app_type=app_type,
        version=str(data.get("version", "")),
        providers=providers,
        tests=tests,
        metadata=metadata,
    )


def parse_providers(raw_providers: Any) -> dict[str, ProviderConfig]:
    """Convierte proveedores YAML en objetos ProviderConfig."""
    if not isinstance(raw_providers, dict):
        raise EvalsYamlError("providers debe ser un objeto con al menos baseline y candidate.")

    providers: dict[str, ProviderConfig] = {}
    for name, raw_provider in raw_providers.items():
        if not isinstance(name, str) or not name.strip():
            raise EvalsYamlError("Cada proveedor debe tener un nombre no vacío.")
        if not isinstance(raw_provider, dict):
            raise EvalsYamlError(f"El proveedor {name} debe ser un objeto YAML.")

        unknown_fields = sorted(set(raw_provider) - PROVIDER_FIELDS)
        if unknown_fields:
            raise EvalsYamlError(
                f"El proveedor {name} tiene campos no reconocidos: " + ", ".join(unknown_fields)
            )

        providers[name] = ProviderConfig(
            model=str(raw_provider.get("model", "")),
            prompt=str(raw_provider.get("prompt", "")),
            provider=str(raw_provider.get("provider", "openai-compatible")),
            temperature=raw_provider.get("temperature"),
            max_tokens=raw_provider.get("max_tokens"),
            base_url=raw_provider.get("base_url"),
        )

    return providers


def parse_tests(raw_tests: Any) -> list[TestCase]:
    """Convierte la lista tests del YAML en objetos TestCase."""
    if not isinstance(raw_tests, list):
        raise EvalsYamlError("tests debe ser una lista de casos de prueba.")

    tests: list[TestCase] = []
    for index, raw_test in enumerate(raw_tests, start=1):
        if not isinstance(raw_test, dict):
            raise EvalsYamlError(f"El test en posición {index} debe ser un objeto YAML.")

        unknown_fields = sorted(set(raw_test) - TEST_FIELDS)
        if unknown_fields:
            raise EvalsYamlError(
                f"El test en posición {index} tiene campos no reconocidos: "
                + ", ".join(unknown_fields)
            )

        assertions = parse_assertions(raw_test.get("assertions"), index)
        tests.append(
            TestCase(
                id=str(raw_test.get("id", "")),
                input=str(raw_test.get("input", "")),
                expected_answer=raw_test.get("expected_answer"),
                expected_facts=coerce_string_list(
                    raw_test.get("expected_facts", []), f"expected_facts del test {index}"
                ),
                required_sources=coerce_string_list(
                    raw_test.get("required_sources", []), f"required_sources del test {index}"
                ),
                assertions=assertions,
                metadata=coerce_mapping(raw_test.get("metadata", {}), f"metadata del test {index}"),
            )
        )

    return tests


def parse_assertions(raw_assertions: Any, test_index: int) -> list[AssertionConfig]:
    """Convierte assertions YAML en objetos AssertionConfig."""
    if not isinstance(raw_assertions, list):
        raise EvalsYamlError(f"assertions del test {test_index} debe ser una lista.")

    assertions: list[AssertionConfig] = []
    for assertion_index, raw_assertion in enumerate(raw_assertions, start=1):
        if not isinstance(raw_assertion, dict):
            raise EvalsYamlError(
                f"La aserción {assertion_index} del test {test_index} debe ser un objeto YAML."
            )

        unknown_fields = sorted(set(raw_assertion) - ASSERTION_FIELDS)
        if unknown_fields:
            raise EvalsYamlError(
                f"La aserción {assertion_index} del test {test_index} tiene campos no reconocidos: "
                + ", ".join(unknown_fields)
            )

        assertion_type = str(raw_assertion.get("type", ""))
        severity = parse_severity(raw_assertion.get("severity", Severity.HIGH.value))

        assertions.append(
            AssertionConfig(
                type=assertion_type,
                severity=severity,
                value=raw_assertion.get("value"),
                values=raw_assertion.get("values"),
                pattern=raw_assertion.get("pattern"),
                threshold=raw_assertion.get("threshold"),
                schema=raw_assertion.get("schema"),
            )
        )

    return assertions


def parse_severity(raw_severity: Any) -> Severity:
    """Convierte una severidad YAML en enum validado."""
    try:
        return Severity(str(raw_severity))
    except ValueError as exc:
        allowed = ", ".join(severity.value for severity in Severity)
        raise EvalsYamlError(f"severity debe ser uno de: {allowed}") from exc


def coerce_string_list(value: Any, field_name: str) -> list[str]:
    """Valida una lista de cadenas."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise EvalsYamlError(f"{field_name} debe ser una lista.")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise EvalsYamlError(f"{field_name} debe contener solo cadenas no vacías.")
    return value


def coerce_mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Valida un objeto YAML opcional."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise EvalsYamlError(f"{field_name} debe ser un objeto YAML.")
    return value


def validate_evaluation_suite(suite: EvaluationSuite) -> list[str]:
    """Devuelve todos los problemas semánticos encontrados en una suite."""
    errors: list[str] = []

    errors.extend(validate_suite_header(suite))
    errors.extend(validate_providers(suite.providers))
    errors.extend(validate_tests(suite.tests))
    errors.extend(validate_profile_constraints(suite))

    return errors


def validate_suite_header(suite: EvaluationSuite) -> list[str]:
    """Valida los campos principales de la suite."""
    errors: list[str] = []

    if not suite.suite.strip():
        errors.append("suite no puede estar vacío.")
    elif not SLUG_PATTERN.match(suite.suite):
        errors.append("suite debe usar solo minúsculas, números, guiones o guiones bajos.")

    if not suite.version.strip():
        errors.append("version no puede estar vacío.")

    return errors


def validate_providers(providers: dict[str, ProviderConfig]) -> list[str]:
    """Valida que existan baseline y candidate con configuración mínima."""
    errors: list[str] = []

    if "baseline" not in providers:
        errors.append("providers debe incluir baseline.")
    if "candidate" not in providers:
        errors.append("providers debe incluir candidate.")

    for name, provider in providers.items():
        if not provider.model.strip():
            errors.append(f"El proveedor {name} debe definir model.")
        if not provider.prompt.strip():
            errors.append(f"El proveedor {name} debe definir prompt.")
        if not provider.provider.strip():
            errors.append(f"El proveedor {name} debe definir provider.")
        if provider.temperature is not None and not isinstance(provider.temperature, int | float):
            errors.append(f"temperature del provider {name} debe ser numérico.")
        if provider.max_tokens is not None:
            if not isinstance(provider.max_tokens, int) or provider.max_tokens <= 0:
                errors.append(f"max_tokens del provider {name} debe ser un entero positivo.")

    return errors


def validate_tests(tests: list[TestCase]) -> list[str]:
    """Valida ids, inputs y assertions de los casos de prueba."""
    errors: list[str] = []

    if not tests:
        errors.append("tests debe incluir al menos un caso de prueba.")
        return errors

    seen_ids: set[str] = set()
    for test in tests:
        if not test.id.strip():
            errors.append("Cada test debe tener id no vacío.")
        elif not SLUG_PATTERN.match(test.id):
            errors.append(f"El id {test.id} debe usar solo minúsculas, números, guiones o guiones bajos.")
        elif test.id in seen_ids:
            errors.append(f"El id de test está duplicado: {test.id}.")
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
    """Valida una assertion individual."""
    errors: list[str] = []
    context = f"test {test.id or '<sin-id>'}"

    if assertion.type not in ASSERTION_TYPES:
        errors.append(f"Aserción desconocida en {context}: {assertion.type}.")
        return errors

    rule = ASSERTION_RULES[assertion.type]

    for required_field in rule.required_fields:
        if getattr(assertion, required_field) is None:
            errors.append(
                f"La aserción {assertion.type} en {context} requiere el campo {required_field}."
            )

    if rule.requires_value:
        if not isinstance(assertion.value, str) or not assertion.value.strip():
            errors.append(f"La aserción {assertion.type} en {context} requiere value como texto no vacío.")

    if rule.requires_values:
        if not isinstance(assertion.values, list) or not assertion.values:
            errors.append(f"La aserción {assertion.type} en {context} requiere values como lista no vacía.")
        elif not all(isinstance(value, str) and value.strip() for value in assertion.values):
            errors.append(f"La aserción {assertion.type} en {context} requiere values de texto no vacío.")

    if assertion.type == "regex":
        if not isinstance(assertion.pattern, str) or not assertion.pattern.strip():
            errors.append(f"La aserción regex en {context} requiere pattern como texto no vacío.")
        else:
            try:
                re.compile(assertion.pattern)
            except re.error as exc:
                errors.append(f"La aserción regex en {context} tiene pattern inválido: {exc}.")

    if rule.requires_threshold:
        errors.extend(validate_threshold(assertion, context))

    if rule.requires_positive_integer_value:
        if not isinstance(assertion.value, int) or assertion.value <= 0:
            errors.append(
                f"La aserción {assertion.type} en {context} requiere value como entero positivo."
            )

    if assertion.type == "max_cost_usd":
        if not isinstance(assertion.value, int | float) or assertion.value < 0:
            errors.append(f"La aserción max_cost_usd en {context} requiere value numérico no negativo.")

    if assertion.type == "json_schema" and assertion.schema is None:
        errors.append(f"La aserción json_schema en {context} requiere schema.")

    if assertion.type == "semantic_similarity" and not test.expected_answer:
        errors.append(f"semantic_similarity en {context} requiere expected_answer en el test.")

    if assertion.type == "answer_correctness" and not test.expected_answer and not test.expected_facts:
        errors.append(
            f"answer_correctness en {context} requiere expected_answer o expected_facts en el test."
        )

    return errors


def validate_threshold(assertion: AssertionConfig, context: str) -> list[str]:
    """Valida umbrales entre 0 y 1."""
    errors: list[str] = []
    if not isinstance(assertion.threshold, int | float):
        errors.append(f"La aserción {assertion.type} en {context} requiere threshold numérico.")
    elif assertion.threshold < 0 or assertion.threshold > 1:
        errors.append(f"La aserción {assertion.type} en {context} requiere threshold entre 0 y 1.")
    return errors


def validate_profile_constraints(suite: EvaluationSuite) -> list[str]:
    """Valida reglas específicas por tipo de aplicación."""
    errors: list[str] = []

    for test in suite.tests:
        assertion_types = {assertion.type for assertion in test.assertions}

        if suite.app_type == AppType.SIMPLE_CHATBOT:
            if not assertion_types & TEXT_ASSERTION_TYPES:
                errors.append(f"El test {test.id} de chatbot simple requiere al menos una aserción textual.")
            if assertion_types & RAG_ASSERTION_TYPES:
                errors.append(f"El test {test.id} usa aserciones RAG, pero app_type no es basic_rag.")

        if suite.app_type == AppType.JSON_EXTRACTOR:
            if not assertion_types & STRUCTURED_ASSERTION_TYPES:
                errors.append(
                    f"El test {test.id} de extractor JSON requiere json_valid o json_schema."
                )
            if assertion_types & RAG_ASSERTION_TYPES:
                errors.append(f"El test {test.id} usa aserciones RAG, pero app_type no es basic_rag.")

        if suite.app_type == AppType.BASIC_RAG:
            if not assertion_types & RAG_ASSERTION_TYPES:
                errors.append(f"El test {test.id} de RAG básico requiere al menos una aserción RAG.")
            if assertion_types & RAG_ASSERTION_TYPES and not test.required_sources:
                errors.append(f"El test {test.id} con aserciones RAG requiere required_sources.")

    return errors


def suite_to_dict(suite: EvaluationSuite) -> dict[str, Any]:
    """Convierte una suite tipada en diccionario serializable para YAML."""
    raw = asdict(suite)
    raw["app_type"] = suite.app_type.value
    raw["providers"] = {
        name: remove_none_values(asdict(provider)) for name, provider in suite.providers.items()
    }
    raw["tests"] = []
    for test in suite.tests:
        test_dict = asdict(test)
        test_dict["assertions"] = []
        for assertion in test.assertions:
            assertion_dict = remove_none_values(asdict(assertion))
            assertion_dict["severity"] = assertion.severity.value
            test_dict["assertions"].append(assertion_dict)
        raw["tests"].append(remove_empty_values(test_dict))
    return remove_empty_values(raw)


def remove_none_values(value: dict[str, Any]) -> dict[str, Any]:
    """Elimina valores None para generar YAML más limpio."""
    return {key: item for key, item in value.items() if item is not None}


def remove_empty_values(value: dict[str, Any]) -> dict[str, Any]:
    """Elimina campos vacíos que no aportan al ejemplo."""
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if item is None:
            continue
        if item == [] or item == {}:
            continue
        cleaned[key] = item
    return cleaned


def write_evals_yaml(suite: EvaluationSuite, path: Path | str) -> None:
    """Escribe una suite en formato evals.yaml."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = suite_to_dict(suite)
    output_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def build_example_suite(profile: str) -> EvaluationSuite:
    """Construye una suite de ejemplo según el perfil solicitado."""
    if profile not in PROFILE_ALIASES:
        allowed = ", ".join(sorted(PROFILE_ALIASES))
        raise EvalsYamlError(f"profile debe ser uno de: {allowed}")

    if profile == "customer_support":
        return build_customer_support_suite()
    if profile == "invoice_extractor":
        return build_invoice_extractor_suite()
    return build_rag_bot_suite()


def build_default_providers() -> dict[str, ProviderConfig]:
    """Devuelve proveedores base y candidato para ejemplos."""
    return {
        "baseline": ProviderConfig(model="gpt-4.1-mini", prompt="prompts/v1.txt"),
        "candidate": ProviderConfig(model="gpt-4.1-mini", prompt="prompts/v2.txt"),
    }


def build_customer_support_suite() -> EvaluationSuite:
    """Crea un ejemplo para chatbot simple."""
    return EvaluationSuite(
        suite="customer-support-chatbot",
        app_type=AppType.SIMPLE_CHATBOT,
        version="0.1.0",
        providers=build_default_providers(),
        tests=[
            TestCase(
                id="refund-policy-001",
                input="¿Puedo pedir un reembolso después de 45 días?",
                expected_facts=[
                    "Los reembolsos se permiten dentro de 30 días.",
                    "Las excepciones requieren aprobación de un gerente.",
                ],
                assertions=[
                    AssertionConfig(type="contains", value="30 días", severity=Severity.CRITICAL),
                    AssertionConfig(
                        type="contains_any",
                        values=["excepción", "aprobación de un gerente"],
                        severity=Severity.HIGH,
                    ),
                    AssertionConfig(
                        type="not_contains",
                        value="los reembolsos siempre están permitidos",
                        severity=Severity.CRITICAL,
                    ),
                    AssertionConfig(type="max_latency_ms", value=5000, severity=Severity.MEDIUM),
                ],
            )
        ],
    )


def build_invoice_extractor_suite() -> EvaluationSuite:
    """Crea un ejemplo para extractor JSON."""
    return EvaluationSuite(
        suite="invoice-json-extractor",
        app_type=AppType.JSON_EXTRACTOR,
        version="0.1.0",
        providers=build_default_providers(),
        tests=[
            TestCase(
                id="invoice-001",
                input=(
                    "Extrae JSON de esta factura: Proveedor ACME, número INV-001, "
                    "total 125.50 USD, fecha 2026-05-20."
                ),
                assertions=[
                    AssertionConfig(type="json_valid", severity=Severity.CRITICAL),
                    AssertionConfig(
                        type="json_schema",
                        schema="schemas/invoice.schema.json",
                        severity=Severity.CRITICAL,
                    ),
                    AssertionConfig(type="contains", value="INV-001", severity=Severity.HIGH),
                    AssertionConfig(type="max_latency_ms", value=5000, severity=Severity.MEDIUM),
                ],
            )
        ],
    )


def build_rag_bot_suite() -> EvaluationSuite:
    """Crea un ejemplo para RAG básico."""
    return EvaluationSuite(
        suite="customer-support-rag",
        app_type=AppType.BASIC_RAG,
        version="0.1.0",
        providers=build_default_providers(),
        tests=[
            TestCase(
                id="refund-policy-001",
                input="¿Puedo pedir un reembolso después de 45 días?",
                expected_facts=[
                    "Los reembolsos se permiten dentro de 30 días.",
                    "Las excepciones requieren aprobación de un gerente.",
                ],
                required_sources=["docs/refund_policy.md"],
                assertions=[
                    AssertionConfig(type="contains", value="30 días", severity=Severity.CRITICAL),
                    AssertionConfig(
                        type="contains_any",
                        values=["excepción", "aprobación de un gerente"],
                        severity=Severity.HIGH,
                    ),
                    AssertionConfig(
                        type="not_contains",
                        value="los reembolsos siempre están permitidos",
                        severity=Severity.CRITICAL,
                    ),
                    AssertionConfig(type="grounded_in_sources", threshold=0.85, severity=Severity.CRITICAL),
                    AssertionConfig(type="citation_accuracy", threshold=0.80, severity=Severity.HIGH),
                    AssertionConfig(type="max_latency_ms", value=5000, severity=Severity.MEDIUM),
                ],
            )
        ],
    )


def render_evals_summary(suite: EvaluationSuite, output_format: str = "text") -> str:
    """Renderiza un resumen de una suite validada."""
    if output_format == "markdown":
        return render_evals_summary_markdown(suite)
    return render_evals_summary_text(suite)


def render_evals_summary_text(suite: EvaluationSuite) -> str:
    """Renderiza resumen de suite en texto plano."""
    lines = [
        f"Suite: {suite.suite}",
        f"Tipo de app: {suite.app_type.value}",
        f"Versión: {suite.version}",
        f"Proveedores: {', '.join(sorted(suite.providers))}",
        f"Casos de prueba: {len(suite.tests)}",
        "Aserciones:",
    ]
    for test in suite.tests:
        assertion_names = ", ".join(assertion.type for assertion in test.assertions)
        lines.append(f"- {test.id}: {assertion_names}")
    return "\n".join(lines) + "\n"


def render_evals_summary_markdown(suite: EvaluationSuite) -> str:
    """Renderiza resumen de suite en Markdown."""
    lines = [
        f"### Suite {suite.suite}",
        "",
        f"- Tipo de app: `{suite.app_type.value}`",
        f"- Versión: `{suite.version}`",
        f"- Proveedores: `{', '.join(sorted(suite.providers))}`",
        f"- Casos de prueba: `{len(suite.tests)}`",
        "",
        "| Caso de prueba | Aserciones |",
        "|---|---|",
    ]
    for test in suite.tests:
        assertion_names = ", ".join(f"`{assertion.type}`" for assertion in test.assertions)
        lines.append(f"| `{test.id}` | {assertion_names} |")
    return "\n".join(lines) + "\n"


def render_evals_spec_markdown() -> str:
    """Renderiza la especificación del contrato evals.yaml."""
    severity_values = ", ".join(f"`{severity.value}`" for severity in Severity)
    app_types = ", ".join(f"`{app_type.value}`" for app_type in AppType)
    assertion_types = ", ".join(f"`{name}`" for name in sorted(ASSERTION_TYPES))

    return f"""### Especificación de evals.yaml - Fase 1

#### Objetivo

`evals.yaml` define suites de unit testing y regression testing para aplicaciones LLM.

En Fase 1 el archivo solo se valida. La ejecución real de modelos y aserciones queda para fases posteriores.

#### Campos principales

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---:|---|
| `suite` | string | sí | Nombre corto de la suite. Usa minúsculas, números, guiones o guiones bajos. |
| `app_type` | string | sí | Tipo de app. Valores: {app_types}. |
| `version` | string | sí | Versión del contrato de la suite. |
| `providers` | object | sí | Debe incluir `baseline` y `candidate`. |
| `tests` | list | sí | Lista de casos de prueba. |
| `metadata` | object | no | Metadatos libres de la suite. |

#### Proveedores

Cada proveedor debe declarar al menos:

```yaml
providers:
  baseline:
    model: gpt-4.1-mini
    prompt: prompts/v1.txt
  candidate:
    model: gpt-4.1-mini
    prompt: prompts/v2.txt
```

Campos permitidos por proveedor:

- `model`
- `prompt`
- `provider`
- `temperature`
- `max_tokens`
- `base_url`

#### Casos de prueba

Cada caso de prueba debe tener:

- `id`
- `input`
- `assertions`

Campos opcionales:

- `expected_answer`
- `expected_facts`
- `required_sources`
- `metadata`

#### Severidades

Valores permitidos: {severity_values}.

Si no se indica `severity`, se usa `high`.

#### Aserciones soportadas

{assertion_types}.

#### Reglas por tipo de app

| app_type | Regla mínima |
|---|---|
| `simple_chatbot` | Cada test debe tener al menos una aserción textual. |
| `json_extractor` | Cada caso de prueba debe tener `json_valid` o `json_schema`. |
| `basic_rag` | Cada test debe tener una aserción RAG y `required_sources`. |

#### Ejemplo

```yaml
suite: customer-support-rag
app_type: basic_rag
version: 0.1.0

providers:
  baseline:
    model: gpt-4.1-mini
    prompt: prompts/v1.txt
  candidate:
    model: gpt-4.1-mini
    prompt: prompts/v2.txt

tests:
  - id: refund-policy-001
    input: "¿Puedo pedir un reembolso después de 45 días?"
    expected_facts:
      - "Los reembolsos se permiten dentro de 30 días."
      - "Las excepciones requieren aprobación de un gerente."
    required_sources:
      - docs/refund_policy.md
    assertions:
      - type: contains
        value: "30 días"
        severity: critical
      - type: grounded_in_sources
        threshold: 0.85
        severity: critical
```
"""

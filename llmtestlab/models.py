"""Modelos de configuración y resultados para LLMTestLab.

Las clases usan nombres en inglés. Los mensajes visibles se mantienen en español.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AppType(str, Enum):
    """Tipos de aplicación permitidos en la primera versión."""

    SIMPLE_CHATBOT = "simple_chatbot"
    JSON_EXTRACTOR = "json_extractor"
    BASIC_RAG = "basic_rag"


class Severity(str, Enum):
    """Niveles de severidad permitidos."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TestStatus(str, Enum):
    """Estados posibles de un test ejecutado."""

    __test__ = False

    PASSED = "passed"
    FAILED = "failed"


class ProviderConfig(BaseModel):
    """Configuración declarativa de un provider."""

    model_config = ConfigDict(extra="forbid")

    model: str
    prompt: str
    provider: str = "mock"
    temperature: float | None = None
    max_tokens: int | None = None
    base_url: str | None = None


class AssertionConfig(BaseModel):
    """Assertion declarada en un caso de prueba."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: str
    severity: Severity = Severity.HIGH
    value: Any | None = None
    values: list[Any] | None = None
    pattern: str | None = None
    threshold: float | None = None
    schema_: Any | None = Field(default=None, alias="schema")


class TestCase(BaseModel):
    """Caso de prueba cargado desde evals.yaml."""

    __test__ = False
    model_config = ConfigDict(extra="forbid")

    id: str
    input: str
    assertions: list[AssertionConfig]
    expected_answer: str | None = None
    expected_facts: list[str] = Field(default_factory=list)
    required_sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationSuite(BaseModel):
    """Suite de evaluación cargada desde evals.yaml."""

    model_config = ConfigDict(extra="forbid")

    suite: str
    app_type: AppType
    version: str
    providers: dict[str, ProviderConfig]
    tests: list[TestCase]
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMOutput(BaseModel):
    """Salida normalizada de una aplicación LLM."""

    model_config = ConfigDict(extra="forbid")

    text: str
    latency_ms: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    sources: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class AssertionResult(BaseModel):
    """Resultado de una assertion."""

    type: str
    severity: Severity
    passed: bool
    message: str


class TestResult(BaseModel):
    """Resultado de un caso de prueba."""

    id: str
    status: TestStatus
    input: str
    output: LLMOutput
    assertions: list[AssertionResult]


class RunSummary(BaseModel):
    """Resumen de ejecución."""

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)


class RunResult(BaseModel):
    """Resultado completo de una suite ejecutada."""

    suite: str
    app_type: AppType
    provider: str
    summary: RunSummary
    tests: list[TestResult]


JsonType = Literal["object", "array", "string", "number", "integer", "boolean", "null"]

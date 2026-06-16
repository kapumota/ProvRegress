"""Provider simulado para Fase 2."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from llmtestlab.models import LLMOutput, ProviderConfig, TestCase
from llmtestlab.providers.base import BaseProvider


class ProviderError(RuntimeError):
    """Error controlado del provider."""


class MockProvider(BaseProvider):
    """Provider determinístico basado en metadata del test."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)

    def generate(self, test: TestCase) -> LLMOutput:
        """Devuelve una salida simulada para ejecutar el CLI sin modelos externos."""
        metadata = test.metadata or {}
        text = str(metadata["mock_output"]) if "mock_output" in metadata else build_default_text(test)
        latency_ms = read_non_negative_int(metadata, "mock_latency_ms", 100)
        cost_usd = read_non_negative_float(metadata, "mock_cost_usd", 0.0)
        sources = metadata.get("mock_sources", test.required_sources)
        if not isinstance(sources, list):
            sources = []
        try:
            return LLMOutput(
                text=text,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                sources=[str(source) for source in sources],
                raw={"provider": "mock"},
            )
        except ValidationError as exc:
            raise ProviderError(f"La salida mock no es válida: {exc}") from exc


def read_non_negative_int(metadata: dict[str, Any], key: str, default: int) -> int:
    """Lee un entero no negativo desde metadata."""
    raw_value = metadata.get(key, default)
    if isinstance(raw_value, bool):
        raise ProviderError(f"{key} debe ser un número entero no negativo.")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"{key} debe ser un número entero no negativo.") from exc
    if value < 0:
        raise ProviderError(f"{key} debe ser un número entero no negativo.")
    return value


def read_non_negative_float(metadata: dict[str, Any], key: str, default: float) -> float:
    """Lee un decimal no negativo desde metadata."""
    raw_value = metadata.get(key, default)
    if isinstance(raw_value, bool):
        raise ProviderError(f"{key} debe ser un número no negativo.")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"{key} debe ser un número no negativo.") from exc
    if value < 0:
        raise ProviderError(f"{key} debe ser un número no negativo.")
    return value


def build_default_text(test: TestCase) -> str:
    """Construye una salida por defecto a partir de hechos esperados."""
    if test.expected_answer:
        return test.expected_answer
    if test.expected_facts:
        return " ".join(test.expected_facts)
    return f"Respuesta simulada para {test.id}."

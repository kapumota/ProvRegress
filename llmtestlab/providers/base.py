"""Tipos base para proveedores de modelos.

La implementación real de llamadas a modelos queda fuera de Fase 1.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderRequest:
    """Solicitud declarativa para un proveedor."""

    input: str
    prompt: str
    model: str


@dataclass(frozen=True)
class ProviderResponse:
    """Respuesta normalizada de un proveedor."""

    text: str
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

"""Contratos estrictos para eventos observables de una ejecución piloto."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from provregress.schema.common import AppId, ArtifactRef, ComponentType, HashRef
from provregress.schema.manifests import NonBlankStr
from provregress.storage.hashing import canonical_json_bytes


class EventType(str, Enum):
    """Vocabulario P1 cerrado de los eventos observables."""

    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    PROMPT_ISSUED = "prompt.issued"
    MODEL_INVOKED = "model.invoked"
    MODEL_RETURNED = "model.returned"
    RETRIEVAL_STARTED = "retrieval.started"
    RETRIEVAL_RETURNED = "retrieval.returned"
    TOOL_CALLED = "tool.called"
    TOOL_RETURNED = "tool.returned"
    EVALUATOR_INVOKED = "evaluator.invoked"
    EVALUATOR_SCORED = "evaluator.scored"
    OUTCOME_RECORDED = "outcome.recorded"
    ERROR_OBSERVED = "error.observed"


_RESERVED_KEYS = frozenset({
    "mutation_id",
    "operator_id",
    "target_component_id",
    "severity",
})


def _check_observable_metadata(value: Any) -> None:
    """Rechaza etiquetas privilegiadas, también dentro de objetos anidados."""
    if isinstance(value, dict):
        if _RESERVED_KEYS.intersection(value):
            raise ValueError("Los metadatos observables contienen etiquetas reservadas.")
        for item in value.values():
            _check_observable_metadata(item)
    elif isinstance(value, list):
        for item in value:
            _check_observable_metadata(item)


class EventError(BaseModel):
    """Descriptor estructurado de un error de ejecución observable."""

    model_config = ConfigDict(extra="forbid", strict=True)

    category: NonBlankStr
    message: NonBlankStr
    retryable: bool = False
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def validate_details(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Comprueba JSON canónico y evita exponer etiquetas privilegiadas."""
        canonical_json_bytes(value)
        _check_observable_metadata(value)
        return value


class EventEnvelope(BaseModel):
    """Evento individual validado, sin reglas globales de orden del log."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["pilot-event-v1"] = "pilot-event-v1"
    run_id: NonBlankStr
    event_id: NonBlankStr
    sequence: int = Field(strict=True, ge=0)
    timestamp_utc: datetime
    app_id: AppId
    system_version_id: NonBlankStr
    case_id: NonBlankStr
    condition_id: NonBlankStr
    repeat_index: int = Field(strict=True, ge=0)
    event_type: EventType
    component_type: ComponentType
    component_id: NonBlankStr
    parent_event_ids: list[NonBlankStr]
    payload_hash: HashRef
    payload_ref: ArtifactRef | None = None
    attributes: dict[str, JsonValue]
    error: EventError | None = None

    @field_validator("timestamp_utc")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        """Exige zona horaria y normaliza la representación a UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("El instante del evento debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @field_validator("parent_event_ids")
    @classmethod
    def validate_parents(cls, value: list[str]) -> list[str]:
        """Prohíbe referencias parentales duplicadas."""
        if len(value) != len(set(value)):
            raise ValueError("Los identificadores parentales deben ser únicos.")
        return value

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Solo acepta metadatos canónicos sin etiquetas de mutación."""
        canonical_json_bytes(value)
        _check_observable_metadata(value)
        return value

    @model_validator(mode="after")
    def validate_local_references(self) -> EventEnvelope:
        """Comprueba coherencia local sin inspeccionar otros eventos."""
        if self.event_id in self.parent_event_ids:
            raise ValueError("Un evento no puede declararse padre de sí mismo.")
        if self.payload_ref is not None and self.payload_ref.hash != self.payload_hash:
            raise ValueError("La referencia del payload no coincide con su hash.")
        return self

"""Contratos observacionales v2: no altera ni deriva de schemas v1 congelados.

Los valores numéricos canónicos usan enteros interoperables o decimales en texto.
Un invocation_key describe una operación lógica, no un índice temporal.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from provregress.schema.common import AppId, ComponentType
from provregress.schema.events import EventType
from provregress.storage.hashing import canonical_json_bytes, sha256_hex

SAFE_INT = (1 << 53) - 1
_RESERVED = frozenset({"mutation_id", "operator_id", "target_component_id", "severity"})
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_DECIMAL = re.compile(r"(?:0|-?[1-9][0-9]*)(?:\.[0-9]*[1-9])?\Z")


class V2Error(ValueError):
    """Violación del contrato observacional o de comparación v2."""


def canonical_v2(value: Any) -> bytes:
    """JSON canónico solo en el dominio interoperable; rechaza etiquetas experimentales."""
    def check(item: Any) -> None:
        if isinstance(item, bool) or item is None or isinstance(item, str):
            return
        if type(item) is int:
            if not -SAFE_INT <= item <= SAFE_INT:
                raise V2Error("Entero fuera del dominio interoperable JSON v2.")
            return
        if type(item) is float:
            raise V2Error("Los floats están prohibidos en JSON canónico v2.")
        if isinstance(item, list):
            for element in item:
                check(element)
            return
        if isinstance(item, dict):
            for key, element in item.items():
                if not isinstance(key, str) or key in _RESERVED:
                    raise V2Error("Clave no textual o etiqueta experimental reservada.")
                check(element)
            return
        raise V2Error("Tipo JSON no admitido en v2.")
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    check(value)
    return canonical_json_bytes(value)


def decimal_v2(raw: str, *, strictly_positive: bool = False) -> Decimal:
    """Decimales exactos como cadenas de formato fijo, sin exponentes ni -0."""
    if not isinstance(raw, str) or len(raw) > 48 or not _DECIMAL.fullmatch(raw):
        raise V2Error("Decimal no canónico: usar cadenas sin exponentes ni ceros sobrantes.")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise V2Error("Decimal no válido.") from exc
    if strictly_positive and number <= 0:
        raise V2Error("Se requiere decimal positivo.")
    return number


def _nonblank(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("Identidad vacía.")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EventV2(_Strict):
    """Evento observable con identidad de invocación declarada por instrumentación."""

    schema_version: Literal["pilot-event-v2"] = "pilot-event-v2"
    run_id: str
    event_id: str
    sequence: int = Field(ge=0, strict=True)
    timestamp_utc: datetime
    app_id: AppId
    case_id: str
    repeat_index: int = Field(ge=0, strict=True)
    system_version_id: str
    condition_id: str
    component_type: ComponentType
    component_id: str
    event_type: EventType
    scope_path: list[str] = Field(min_length=1)
    invocation_key: str
    parent_event_ids: list[str] = Field(default_factory=list)
    payload: JsonValue
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    semantic_values: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("run_id", "event_id", "case_id", "condition_id", "system_version_id", "component_id", "invocation_key")
    @classmethod
    def identity(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("scope_path")
    @classmethod
    def scopes(cls, value: list[str]) -> list[str]:
        if not all(isinstance(x, str) and x.strip() for x in value):
            raise ValueError("La ruta de ámbito requiere segmentos estables no vacíos.")
        return value

    @field_validator("timestamp_utc")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("El timestamp debe contener zona horaria.")
        return value.astimezone(timezone.utc)

    @field_validator("payload", "attributes", "semantic_values")
    @classmethod
    def observable(cls, value: Any) -> Any:
        canonical_v2(value)
        return value

    @model_validator(mode="after")
    def local_integrity(self) -> EventV2:
        if self.event_id in self.parent_event_ids or len(self.parent_event_ids) != len(set(self.parent_event_ids)):
            raise ValueError("La lista de padres es cíclica o duplicada.")
        return self

    @property
    def key(self) -> tuple[str, ...]:
        return ("event", self.component_type.value, self.component_id, *self.scope_path,
                self.invocation_key, self.event_type.value)


class EventNodeV2(_Strict):
    node_id: str
    event_id: str
    sequence: int = Field(strict=True, ge=0)
    timestamp_utc: datetime
    component_type: ComponentType
    component_id: str
    event_type: EventType
    scope_path: list[str] = Field(min_length=1)
    invocation_key: str
    payload_hash: str
    attributes: dict[str, JsonValue]
    semantic_values: dict[str, JsonValue]

    @field_validator("timestamp_utc")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp sin zona horaria.")
        return value.astimezone(timezone.utc)

    @field_validator("event_id", "component_id", "invocation_key")
    @classmethod
    def identity(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("scope_path")
    @classmethod
    def scopes(cls, value: list[str]) -> list[str]:
        if not all(isinstance(segment, str) and segment.strip() for segment in value):
            raise ValueError("Ruta lógica de invocación no canónica.")
        return value

    @field_validator("node_id", "payload_hash")
    @classmethod
    def digest(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("Digest SHA-256 mal formado.")
        return value

    @field_validator("attributes", "semantic_values")
    @classmethod
    def observable(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        canonical_v2(value)
        return value

    @property
    def key(self) -> tuple[str, ...]:
        return ("event", self.component_type.value, self.component_id, *self.scope_path,
                self.invocation_key, self.event_type.value)


class EdgeV2(_Strict):
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_kind: Literal["observed_parent"] = "observed_parent"


class GraphV2(_Strict):
    schema_version: Literal["provenance-graph-v2"] = "provenance-graph-v2"
    run_id: str
    app_id: AppId
    case_id: str
    repeat_index: int
    condition_id: str
    system_version_id: str
    events: list[EventNodeV2]
    edges: list[EdgeV2]
    graph_hash: str

    @field_validator("run_id", "case_id", "condition_id", "system_version_id")
    @classmethod
    def identity(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def consistent_hash(self) -> GraphV2:
        if not _DIGEST.fullmatch(self.graph_hash):
            raise ValueError("Hash de grafo v2 mal formado.")
        fields = self.model_dump(mode="json", exclude={"graph_hash"})
        if sha256_hex(canonical_v2(fields)) != self.graph_hash:
            raise ValueError("Hash de grafo v2 inconsistente.")
        return self


class SignalRule(_Strict):
    event_type: EventType
    field: str
    kind: Literal["decimal", "categorical", "boolean"]
    weight: str
    scale: str | None = None

    @model_validator(mode="after")
    def check(self) -> SignalRule:
        _nonblank(self.field)
        if self.field in _RESERVED:
            raise ValueError("Señal reservada.")
        if not (Decimal(0) < decimal_v2(self.weight, strictly_positive=True) <= Decimal(1)):
            raise ValueError("El peso debe estar entre 0 y 1.")
        if self.kind == "decimal":
            if self.scale is None:
                raise ValueError("La señal decimal requiere escala positiva.")
            decimal_v2(self.scale, strictly_positive=True)
        elif self.scale is not None:
            raise ValueError("Una señal no decimal no utiliza escala.")
        return self


class ComparisonPolicyV2(_Strict):
    schema_version: Literal["comparison-policy-v2"] = "comparison-policy-v2"
    app_id: AppId
    rules: list[SignalRule] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_weights(self) -> ComparisonPolicyV2:
        groups: dict[EventType, set[str]] = {}
        totals: dict[EventType, Decimal] = {}
        for rule in self.rules:
            fields = groups.setdefault(rule.event_type, set())
            if rule.field in fields:
                raise ValueError("Señal duplicada para un tipo de evento.")
            fields.add(rule.field)
            totals[rule.event_type] = totals.get(rule.event_type, Decimal(0)) + decimal_v2(rule.weight)
        if any(weight != 1 for weight in totals.values()):
            raise ValueError("Los pesos de cada event_type deben sumar exactamente 1.")
        return self

    @property
    def policy_hash(self) -> str:
        return sha256_hex(canonical_v2(self))

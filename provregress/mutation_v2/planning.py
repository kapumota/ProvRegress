"""Planificación pura R1.0-M1 sobre claves semánticas de GraphV2.

No se ejecutan tratamientos, no se leen payloads de respuestas, no se crean
trazas observables y no se habilita el estudio confirmatorio.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Literal

from pydantic import Field, JsonValue, ValidationError, field_validator, model_validator

from provregress.mutation_v2.catalog import CATALOG, check_operator, check_pointer
from provregress.provenance_v2.projector import validate_graph_v2
from provregress.provenance_v2.schema import (
    AppId, ComparisonPolicyV2, GraphV2, V2Error, _Strict, canonical_v2,
)
from provregress.storage.hashing import canonical_json_bytes, sha256_hex

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
MAX_REQUESTS = 64


def _private_canonical(value: Any) -> bytes:
    """Canoniza el canal privilegiado: permite operator_id en el sobre, no floats."""
    from pydantic import BaseModel
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")

    def check(item: Any) -> None:
        if item is None or isinstance(item, (bool, str)):
            return
        if type(item) is int and -(2**53 - 1) <= item <= 2**53 - 1:
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if type(key) is not str:
                    raise M1Error("Clave privada JSON no textual.")
                check(child)
            return
        raise M1Error("Valor privado fuera del dominio JSON interoperable.")
    check(value)
    return canonical_json_bytes(value)


class M1Error(V2Error):
    """Plan de diseño inválido, incompleto o incompatible con el grafo."""


class MutationRequestV2(_Strict):
    """Solicitud privilegiada. La clave apunta a evento lógico, no a event_id."""

    request_id: str
    target_key: list[str] = Field(min_length=6, max_length=36)
    operator_id: str
    json_pointer: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("request_id")
    @classmethod
    def check_id(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError("request_id requiere identificador reproducible.")
        return value

    @field_validator("target_key")
    @classmethod
    def check_key(cls, value: list[str]) -> list[str]:
        if (value[0] != "event" or any(not isinstance(x, str) or not x.strip()
                                       or len(x.encode("utf-8")) > 160 for x in value)):
            raise ValueError("La clave debe pertenecer al espacio semántico v2.")
        canonical_v2(value)
        return value

    @model_validator(mode="after")
    def check_intent(self) -> MutationRequestV2:
        check_pointer(self.json_pointer)
        check_operator(self.operator_id, self.parameters)
        return self


class PlannedIntentV2(MutationRequestV2):
    """Solicitud resuelta inequívocamente en el grafo de origen."""

    source_payload_hash: str

    @field_validator("source_payload_hash")
    @classmethod
    def digest(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("Hash de payload inválido.")
        return value


class MutationPlanV2(_Strict):
    """Artefacto privado de planificación, nunca evento o DeltaV2 observable."""

    schema_version: Literal["mutation-plan-v2-m1"] = "mutation-plan-v2-m1"
    mode: Literal["design_only"] = "design_only"
    confirmatory_execution: Literal[False] = False
    app_id: AppId
    source_graph_hash: str
    comparison_policy_hash: str
    intents: list[PlannedIntentV2] = Field(min_length=1, max_length=MAX_REQUESTS)
    plan_hash: str

    @field_validator("source_graph_hash", "comparison_policy_hash", "plan_hash")
    @classmethod
    def digest(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("Hash SHA-256 inválido.")
        return value

    @model_validator(mode="after")
    def checked_hash(self) -> MutationPlanV2:
        body = self.model_dump(mode="json", exclude={"plan_hash"})
        if sha256_hex(_private_canonical(body)) != self.plan_hash:
            raise ValueError("El hash del plan no coincide con el contenido.")
        ids = [item.request_id for item in self.intents]
        if ids != sorted(set(ids)):
            raise ValueError("Los objetivos requieren orden canónico e IDs únicos.")
        if len({tuple(item.target_key) for item in self.intents}) != len(self.intents):
            raise ValueError("M1 no admite dos tratamientos sobre una misma identidad lógica.")
        return self


def _snapshot(model: Any, cls: Any) -> Any:
    """Desconfía de model_copy y revalida el contenido de los modelos recibidos."""
    if not isinstance(model, cls):
        raise M1Error("Objeto recibido con tipo incompatible.")
    try:
        return cls.model_validate_json(_private_canonical(model))
    except (ValidationError, ValueError, TypeError) as exc:
        raise M1Error("Objeto modificado o fuera del dominio canónico.") from exc


def plan_mutations_v2(
    graph: GraphV2, policy: ComparisonPolicyV2, requests: list[MutationRequestV2],
) -> MutationPlanV2:
    """Construye exclusivamente un plan privado y determinista, sin efectos laterales."""
    if type(requests) is not list or not 1 <= len(requests) <= MAX_REQUESTS:
        raise M1Error("M1 exige entre 1 y 64 solicitudes declaradas.")
    try:
        validate_graph_v2(graph)
        graph = _snapshot(graph, GraphV2)
        policy = _snapshot(policy, ComparisonPolicyV2)
    except (ValidationError, ValueError, TypeError) as exc:
        raise M1Error("Grafo o política v2 no válidos.") from exc
    if policy.app_id != graph.app_id:
        raise M1Error("La política y el grafo pertenecen a aplicaciones diferentes.")
    rule_types = {rule.event_type for rule in policy.rules}
    index: dict[tuple[str, ...], list[Any]] = {}
    for node in graph.events:
        index.setdefault(node.key, []).append(node)
    reqs = [_snapshot(x, MutationRequestV2) for x in requests]
    ids = [item.request_id for item in reqs]
    if len(ids) != len(set(ids)):
        raise M1Error("request_id duplicado.")
    target_keys = [tuple(item.target_key) for item in reqs]
    if len(target_keys) != len(set(target_keys)):
        raise M1Error("M1 no permite más de un tratamiento para una misma clave.")
    prepared: list[dict[str, Any]] = []
    for request in reqs:
        group = index.get(tuple(request.target_key), [])
        if len(group) != 1:
            raise M1Error("La clave de objetivo no existe o su alineamiento es ambiguo.")
        node = group[0]
        if node.event_type not in rule_types:
            raise M1Error("Objetivo sin señal funcional evaluable en la política.")
        prepared.append({**request.model_dump(mode="json"),
                         "source_payload_hash": node.payload_hash})
    prepared.sort(key=lambda x: x["request_id"])
    body = {
        "schema_version": "mutation-plan-v2-m1", "mode": "design_only",
        "confirmatory_execution": False, "app_id": graph.app_id.value,
        "source_graph_hash": graph.graph_hash,
        "comparison_policy_hash": policy.policy_hash,
        "intents": prepared,
    }
    body["plan_hash"] = sha256_hex(_private_canonical(body))
    return MutationPlanV2.model_validate_json(_private_canonical(body))


def verify_plan_v2(plan: MutationPlanV2, graph: GraphV2, policy: ComparisonPolicyV2) -> None:
    """Comprueba integridad del plan y que sigue apuntando al mismo grafo/política."""
    p = _snapshot(plan, MutationPlanV2)
    requests = [MutationRequestV2.model_validate({
        "request_id": item.request_id, "target_key": item.target_key,
        "operator_id": item.operator_id, "json_pointer": item.json_pointer,
        "parameters": item.parameters,
    }) for item in p.intents]
    regenerated = plan_mutations_v2(graph, policy, requests)
    if _private_canonical(p) != _private_canonical(regenerated):
        raise M1Error("El plan no corresponde al grafo y política de origen.")


def public_plan_summary_v2(plan: MutationPlanV2) -> dict[str, Any]:
    """Resumen no privilegiado: sin claves, pointers, parámetros o IDs de objetivos."""
    p = _snapshot(plan, MutationPlanV2)
    return {
        "schema_version": p.schema_version, "mode": p.mode,
        "confirmatory_execution": False,
        "planned_intents": len(p.intents), "plan_hash": p.plan_hash,
        "operator_counts": dict(sorted(Counter(x.operator_id for x in p.intents).items())),
    }

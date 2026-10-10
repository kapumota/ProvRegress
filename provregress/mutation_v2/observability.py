"""M2-P1: valida acoplamiento payload/señal antes de ejecutar tratamientos.

No modifica payloads, no emite eventos ni habilita experimentos confirmatorios.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from provregress.mutation_v2.catalog import check_pointer
from provregress.mutation_v2.planning import MutationPlanV2, verify_plan_v2
from provregress.provenance_v2.projector import project_trace_v2, validate_graph_v2
from provregress.provenance_v2.schema import (
    AppId, ComparisonPolicyV2, EventV2, GraphV2, V2Error, _Strict,
    canonical_v2,
)
from provregress.schema.events import EventType
from provregress.storage.hashing import sha256_hex


class M2Error(V2Error):
    """Un tratamiento no tiene relación verificable con la observación."""


class SignalBindingM2(_Strict):
    event_type: EventType
    json_pointer: str
    signal_field: str
    mechanism: Literal["direct", "propagated"] = "direct"
    operator_ids: list[Literal["json.scalar.replace.v1", "json.field.remove.v1"]] = Field(min_length=1)

    @field_validator("json_pointer")
    @classmethod
    def pointer_is_valid(cls, value: str) -> str:
        check_pointer(value)
        return value

    @field_validator("signal_field")
    @classmethod
    def signal_is_valid(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Se requiere una señal declarada no vacía.")
        return value

    @model_validator(mode="after")
    def unique_operators(self) -> SignalBindingM2:
        if sorted(set(self.operator_ids)) != sorted(self.operator_ids):
            raise ValueError("Operadores repetidos o desordenados en binding.")
        return self


class ObservationContractM2(_Strict):
    schema_version: Literal["mutation-observability-m2-p1"] = "mutation-observability-m2-p1"
    app_id: AppId
    comparison_policy_hash: str
    bindings: list[SignalBindingM2] = Field(min_length=1)

    @model_validator(mode="after")
    def bindings_are_unique(self) -> ObservationContractM2:
        keys = [(b.event_type.value, b.json_pointer, op)
                for b in self.bindings for op in b.operator_ids]
        if len(keys) != len(set(keys)):
            raise ValueError("Binding ambiguo para evento, puntero y operador.")
        if keys != sorted(keys):
            raise ValueError("Los bindings requieren orden canónico.")
        return self

    @property
    def contract_hash(self) -> str:
        return sha256_hex(canonical_v2(self))


class PreflightItemM2(_Strict):
    request_id: str
    classification: Literal[
        "observable_direct", "observable_propagated", "silent_risk",
    ]
    reason: Literal[
        "signal_bound", "no_binding", "missing_signal", "payload_signal_inconsistent",
    ]


class PreflightReportM2(_Strict):
    schema_version: Literal["mutation-preflight-m2-p1"] = "mutation-preflight-m2-p1"
    plan_hash: str
    policy_hash: str
    contract_hash: str
    items: list[PreflightItemM2]
    eligible_count: int
    silent_count: int
    confirmatory_execution: Literal[False] = False


def _lookup_object_pointer(value: Any, pointer: str) -> Any:
    """Resuelve solo propiedades de objetos, nunca índices de arreglos."""
    check_pointer(pointer)
    current = value
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise M2Error("El JSON Pointer no existe en el payload original.")
        current = current[part]
    return current


def audit_observability_m2(
    plan: MutationPlanV2,
    graph: GraphV2,
    policy: ComparisonPolicyV2,
    events: list[EventV2],
    contract: ObservationContractM2,
) -> PreflightReportM2:
    """Audita las intenciones sin aplicar tratamiento ni mirar salidas candidate."""
    verify_plan_v2(plan, graph, policy)
    validate_graph_v2(graph)
    if not isinstance(contract, ObservationContractM2):
        raise M2Error("Contrato M2 requerido.")
    contract = ObservationContractM2.model_validate_json(canonical_v2(contract))
    if contract.app_id != graph.app_id or contract.comparison_policy_hash != policy.policy_hash:
        raise M2Error("Contrato de observabilidad incompatible con política de origen.")
    if not isinstance(events, list) or not events or any(not isinstance(e, EventV2) for e in events):
        raise M2Error("Se requieren eventos originales validados.")
    checked_events = [EventV2.model_validate_json(canonical_v2(event)) for event in events]
    if project_trace_v2(checked_events).graph_hash != graph.graph_hash:
        raise M2Error("Los bytes de eventos no corresponden al grafo del plan.")

    policy_fields = {(r.event_type, r.field) for r in policy.rules}
    for binding in contract.bindings:
        if (binding.event_type, binding.signal_field) not in policy_fields:
            raise M2Error("El binding no pertenece a una señal de la política congelable.")

    by_event = {event.event_id: event for event in checked_events}
    by_key = {node.key: node for node in graph.events}
    lookup = {(b.event_type, b.json_pointer, op): b
              for b in contract.bindings for op in b.operator_ids}
    output: list[PreflightItemM2] = []
    for intent in plan.intents:
        node = by_key[tuple(intent.target_key)]
        source = by_event[node.event_id]
        # Resolver el puntero aunque la intención vaya a clasificarse como silenciosa.
        original = _lookup_object_pointer(source.payload, intent.json_pointer)
        if intent.operator_id == "json.scalar.replace.v1":
            new_value = intent.parameters["value"]
            if original is not None and type(new_value) is not type(original):
                raise M2Error("Sustitución incompatible con tipo escalar de origen.")
            if isinstance(original, (dict, list)):
                raise M2Error("El reemplazo escalar apunta a un objeto o arreglo.")
        else:
            if not isinstance(source.payload, dict):
                # No permite eliminar un elemento de lista.
                raise M2Error("La supresión exige un campo en objeto JSON.")
        binding = lookup.get((source.event_type, intent.json_pointer, intent.operator_id))
        if binding is None:
            cls, reason = "silent_risk", "no_binding"
        elif binding.signal_field not in source.semantic_values:
            cls, reason = "silent_risk", "missing_signal"
        elif binding.mechanism == "direct":
            # Una relación directa requiere igualdad inicial; si se ha declarado una
            # transformación (bool de texto, agregación), marcar como propagada.
            if canonical_v2(source.semantic_values[binding.signal_field]) != canonical_v2(original):
                cls, reason = "silent_risk", "payload_signal_inconsistent"
            else:
                cls, reason = "observable_direct", "signal_bound"
        else:
            cls, reason = "observable_propagated", "signal_bound"
        output.append(PreflightItemM2(
            request_id=intent.request_id, classification=cls, reason=reason,
        ))
    count = Counter(x.classification for x in output)
    return PreflightReportM2(
        plan_hash=plan.plan_hash, policy_hash=policy.policy_hash,
        contract_hash=contract.contract_hash, items=output,
        eligible_count=count["observable_direct"] + count["observable_propagated"],
        silent_count=count["silent_risk"],
    )


def assert_observable_plan_m2(report: PreflightReportM2) -> None:
    """Rechaza planes no observables; conservarlos en denominador de silenciosos."""
    if report.silent_count or report.eligible_count != len(report.items):
        raise M2Error("Plan contiene riesgo de mutación silenciosa; no es elegible.")

"""Alineamiento v2 y localización funcional por evento, separada de ruido/hashes."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Literal

from pydantic import Field, model_validator

from provregress.provenance_v2.projector import validate_graph_v2
from provregress.provenance_v2.schema import (
    AppId, ComparisonPolicyV2, EventNodeV2, GraphV2, SignalRule, V2Error,
    _Strict, canonical_v2, decimal_v2,
)
from provregress.storage.hashing import sha256_hex

_MAG_PRECISION = Decimal("0.000000000001")
_RATE_PRECISION = Decimal("0.000000000001")


def _decimal_text(value: Decimal) -> str:
    """Codifica magnitudes y tasas como cadenas decimales sin exponentes."""
    return "0" if value == 0 else format(value.normalize(), "f")


def _sorted(items: list[Any]) -> list[Any]:
    return sorted(items, key=canonical_v2)


class EventChangeV2(_Strict):
    key: list[str]
    changed_signals: list[str]
    magnitude: str
    raw_payload_changed: bool


class AmbiguousV2(_Strict):
    key: list[str]
    baseline_count: int
    candidate_count: int


class EdgeChangeV2(_Strict):
    source_key: list[str]
    target_key: list[str]


class EdgeAmbiguousV2(EdgeChangeV2):
    side: Literal["baseline", "candidate"]
    count: int


class DeltaV2(_Strict):
    schema_version: Literal["provenance-delta-v2"] = "provenance-delta-v2"
    baseline_run_id: str
    candidate_run_id: str
    policy_hash: str
    added_events: list[list[str]]
    removed_events: list[list[str]]
    changed_events: list[EventChangeV2]
    unchanged_events: list[list[str]]
    unassessed_events: list[list[str]]
    ambiguous_events: list[AmbiguousV2]
    ignored_payload_changes: list[list[str]]
    edges_added: list[EdgeChangeV2]
    edges_removed: list[EdgeChangeV2]
    edges_ambiguous: list[EdgeAmbiguousV2]
    ambiguous_event_rate: str
    delta_hash: str

    @model_validator(mode="after")
    def hash_is_valid(self) -> DeltaV2:
        content = self.model_dump(mode="json", exclude={"delta_hash"})
        if self.delta_hash != sha256_hex(canonical_v2(content)):
            raise ValueError("Hash del diferencial v2 inconsistente.")
        return self


def _compare_signals(
    before: EventNodeV2, after: EventNodeV2, rules: list[SignalRule]
) -> tuple[list[str], Decimal]:
    changed: list[str] = []
    total = Decimal(0)
    for rule in rules:
        if rule.field not in before.semantic_values or rule.field not in after.semantic_values:
            raise V2Error("Falta señal declarada en política de comparación.")
        old = before.semantic_values[rule.field]
        new = after.semantic_values[rule.field]
        if rule.kind == "boolean":
            if type(old) is not bool or type(new) is not bool:
                raise V2Error("Señal booleana con valor no booleano.")
            severity = Decimal(int(old != new))
        elif rule.kind == "categorical":
            if not isinstance(old, str) or not isinstance(new, str):
                raise V2Error("Señal categórica no textual.")
            severity = Decimal(int(old != new))
        else:
            distance = abs(decimal_v2(old) - decimal_v2(new))
            severity = min(Decimal(1), distance / decimal_v2(rule.scale, strictly_positive=True))
        if severity != 0:
            changed.append(rule.field)
        total += severity * decimal_v2(rule.weight)
    return sorted(changed), total


def _edge_groups(
    graph: GraphV2, ambiguous: set[tuple[str, ...]]
) -> tuple[set[tuple[tuple[str, ...], tuple[str, ...]]],
           Counter[tuple[tuple[str, ...], tuple[str, ...]]]]:
    nodes = {node.node_id: node for node in graph.events}
    clear: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    unclear: Counter[tuple[tuple[str, ...], tuple[str, ...]]] = Counter()
    for edge in graph.edges:
        relation = (nodes[edge.source_node_id].key, nodes[edge.target_node_id].key)
        if relation[0] in ambiguous or relation[1] in ambiguous:
            unclear[relation] += 1
        elif relation in clear:
            raise V2Error("Arista semántica duplicada sin ambigüedad declarada.")
        else:
            clear.add(relation)
    return clear, unclear


def compare_graphs_v2(before: GraphV2, after: GraphV2, policy: ComparisonPolicyV2) -> DeltaV2:
    """Localiza por identidad lógica. Los hashes crudos no determinan una regresión."""
    validate_graph_v2(before)
    validate_graph_v2(after)
    if not isinstance(policy, ComparisonPolicyV2):
        raise V2Error("Se requiere una ComparisonPolicyV2.")
    policy = ComparisonPolicyV2.model_validate_json(canonical_v2(policy))
    if (before.app_id != after.app_id or before.case_id != after.case_id
            or before.repeat_index != after.repeat_index or policy.app_id != before.app_id):
        raise V2Error("Incompatibilidad de aplicación, caso, repetición o política.")
    left: dict[tuple[str, ...], list[EventNodeV2]] = defaultdict(list)
    right: dict[tuple[str, ...], list[EventNodeV2]] = defaultdict(list)
    for node in before.events:
        left[node.key].append(node)
    for node in after.events:
        right[node.key].append(node)
    rules_by_type: dict[str, list[SignalRule]] = defaultdict(list)
    for rule in policy.rules:
        rules_by_type[rule.event_type.value].append(rule)

    added: list[list[str]] = []
    removed: list[list[str]] = []
    changed: list[dict[str, Any]] = []
    unchanged: list[list[str]] = []
    unassessed: list[list[str]] = []
    ambiguous: list[dict[str, Any]] = []
    ignored_payload: list[list[str]] = []
    ambiguous_keys: set[tuple[str, ...]] = set()
    ambiguous_count = 0
    for key in sorted(set(left) | set(right), key=lambda k: canonical_v2(list(k))):
        a, b = left.get(key, []), right.get(key, [])
        if len(a) > 1 or len(b) > 1:
            ambiguous_keys.add(key)
            ambiguous_count += len(a) + len(b)
            ambiguous.append({"key": list(key), "baseline_count": len(a), "candidate_count": len(b)})
        elif not a:
            added.append(list(key))
        elif not b:
            removed.append(list(key))
        else:
            rules = rules_by_type.get(a[0].event_type.value, [])
            if not rules:
                unassessed.append(list(key))
                continue
            signals, size = _compare_signals(a[0], b[0], rules)
            if signals:
                rounded = size.quantize(_MAG_PRECISION, rounding=ROUND_HALF_EVEN)
                if size > 0 and rounded == 0:
                    rounded = _MAG_PRECISION
                changed.append({
                    "key": list(key), "changed_signals": signals,
                    "magnitude": _decimal_text(rounded),
                    "raw_payload_changed": a[0].payload_hash != b[0].payload_hash,
                })
            else:
                unchanged.append(list(key))
                if a[0].payload_hash != b[0].payload_hash:
                    ignored_payload.append(list(key))

    before_clear, before_unclear = _edge_groups(before, ambiguous_keys)
    after_clear, after_unclear = _edge_groups(after, ambiguous_keys)
    edge_added = [{"source_key": list(a), "target_key": list(b)} for a, b in after_clear - before_clear]
    edge_removed = [{"source_key": list(a), "target_key": list(b)} for a, b in before_clear - after_clear]
    edge_ambiguous = [
        {"source_key": list(a), "target_key": list(b), "side": side, "count": count}
        for side, counts in (("baseline", before_unclear), ("candidate", after_unclear))
        for (a, b), count in counts.items()
    ]
    denominator = len(before.events) + len(after.events)
    rate = Decimal(ambiguous_count) / Decimal(denominator)
    content: dict[str, Any] = {
        "schema_version": "provenance-delta-v2",
        "baseline_run_id": before.run_id,
        "candidate_run_id": after.run_id,
        "policy_hash": policy.policy_hash,
        "added_events": _sorted(added),
        "removed_events": _sorted(removed),
        "changed_events": _sorted(changed),
        "unchanged_events": _sorted(unchanged),
        "unassessed_events": _sorted(unassessed),
        "ambiguous_events": _sorted(ambiguous),
        "ignored_payload_changes": _sorted(ignored_payload),
        "edges_added": _sorted(edge_added),
        "edges_removed": _sorted(edge_removed),
        "edges_ambiguous": _sorted(edge_ambiguous),
        "ambiguous_event_rate": _decimal_text(rate.quantize(_RATE_PRECISION, rounding=ROUND_HALF_EVEN)),
    }
    content["delta_hash"] = sha256_hex(canonical_v2(content))
    return DeltaV2.model_validate_json(canonical_v2(content))


_MAX_AMBIGUITY = {
    AppId.A1: Decimal("0.05"), AppId.A2: Decimal("0.05"), AppId.A3: Decimal("0.05"),
}


def assert_pilot_alignment_v2(
    before: GraphV2, after: GraphV2, delta: DeltaV2,
    *, policy: ComparisonPolicyV2, target_keys: list[tuple[str, ...]] | None = None,
) -> None:
    """Gate de ambigüedad por app y elegibilidad de objetivos de mutación."""
    validate_graph_v2(before)
    validate_graph_v2(after)
    try:
        delta = DeltaV2.model_validate_json(canonical_v2(delta))
    except (ValueError, TypeError) as exc:
        raise V2Error("DeltaV2 alterado.") from exc
    if before.app_id != after.app_id or before.app_id not in _MAX_AMBIGUITY:
        raise V2Error("La aplicación carece de umbral de aceptación piloto.")
    # Recalcular sin confiar en un hash legítimo aplicado a un diferencial falso.
    expected_delta = compare_graphs_v2(before, after, policy)
    if canonical_v2(delta) != canonical_v2(expected_delta):
        raise V2Error("El diferencial no corresponde a los grafos y política declarados.")
    # El delta se comprueba de nuevo contra su procedencia nominal, no se acepta otra pareja.
    if delta.baseline_run_id != before.run_id or delta.candidate_run_id != after.run_id:
        raise V2Error("El delta no corresponde a la pareja solicitada.")
    baseline_keys = Counter(node.key for node in before.events)
    candidate_keys = Counter(node.key for node in after.events)
    expected_groups = {
        key: (baseline_keys[key], candidate_keys[key])
        for key in baseline_keys.keys() | candidate_keys.keys()
        if baseline_keys[key] > 1 or candidate_keys[key] > 1
    }
    observed_groups = {
        tuple(group.key): (group.baseline_count, group.candidate_count)
        for group in delta.ambiguous_events
    }
    if observed_groups != expected_groups or len(observed_groups) != len(delta.ambiguous_events):
        raise V2Error("Los grupos ambiguos no corresponden a los grafos originales.")
    ambig = sum(g.baseline_count + g.candidate_count for g in delta.ambiguous_events)
    actual = Decimal(ambig) / Decimal(len(before.events) + len(after.events))
    if actual > _MAX_AMBIGUITY[before.app_id]:
        raise V2Error("El alineamiento supera la ambigüedad máxima admitida para el piloto.")
    if target_keys is None:
        return
    eligible = {tuple(k) for k in delta.added_events + delta.removed_events + delta.unchanged_events}
    eligible.update(tuple(v.key) for v in delta.changed_events)
    excluded = {tuple(v.key) for v in delta.ambiguous_events}
    excluded.update(tuple(k) for k in delta.unassessed_events)
    if any(key not in eligible or key in excluded for key in target_keys):
        raise V2Error("Objetivo de mutación no expresable como evento evaluable inequívoco.")


def topology_profile_v2(graph: GraphV2) -> dict[str, int | bool]:
    """Distingue trazas lineales de ramificadas sin inventar vínculos."""
    validate_graph_v2(graph)
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    for edge in graph.edges:
        incoming[edge.target_node_id] += 1
        outgoing[edge.source_node_id] += 1
    forks = sum(count > 1 for count in outgoing.values())
    joins = sum(count > 1 for count in incoming.values())
    return {"events": len(graph.events), "edges": len(graph.edges), "forks": forks,
            "joins": joins, "branched": bool(forks or joins)}


def sequential_baseline_view_v2(graph: GraphV2, *, include_parent_relations: bool = True) -> list[dict[str, Any]]:
    """Vista de eventos con idénticas señales; padres se conservan por defecto."""
    validate_graph_v2(graph)
    parents: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        parents[edge.target_node_id].append(edge.source_node_id)
    rows = []
    for event in sorted(graph.events, key=lambda n: n.sequence):
        rows.append({
            "event_id": event.event_id,
            "semantic_key": list(event.key),
            "sequence": event.sequence,
            "timestamp_utc": event.timestamp_utc.isoformat(),
            "payload_hash": event.payload_hash,
            "attributes": event.attributes,
            "semantic_values": event.semantic_values,
            "parent_event_ids": sorted(parents[event.node_id]) if include_parent_relations else [],
        })
    return rows

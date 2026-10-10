"""Comparación candidata v2.1: pérdida de señal como cambio explícito.

Se versiona aparte para no alterar los hashes de R0.10-F3/F4.
"""

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


class EventChangeV21(_Strict):
    key: list[str]
    changed_signals: list[str]
    reasons: list[Literal["value_changed", "signal_missing", "signal_restored"]]
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


class DeltaV21(_Strict):
    schema_version: Literal["provenance-delta-v2.1"] = "provenance-delta-v2.1"
    baseline_run_id: str
    candidate_run_id: str
    policy_hash: str
    added_events: list[list[str]]
    removed_events: list[list[str]]
    changed_events: list[EventChangeV21]
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
    def hash_is_valid(self) -> DeltaV21:
        content = self.model_dump(mode="json", exclude={"delta_hash"})
        if self.delta_hash != sha256_hex(canonical_v2(content)):
            raise ValueError("Hash del diferencial v2 inconsistente.")
        return self


def _compare_signals(
    before: EventNodeV2, after: EventNodeV2, rules: list[SignalRule]
) -> tuple[list[str], Decimal, list[str]]:
    changed: list[str] = []
    reasons: set[str] = set()
    total = Decimal(0)
    for rule in rules:
        old_present = rule.field in before.semantic_values
        new_present = rule.field in after.semantic_values
        if not old_present and not new_present:
            # Dos ausencias no prueban ni cambio funcional ni continuidad válida.
            raise V2Error("Señal obligatoria ausente en ambas ejecuciones.")
        if not new_present:
            severity = Decimal(1)
            reasons.add("signal_missing")
        elif not old_present:
            severity = Decimal(1)
            reasons.add("signal_restored")
        else:
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
            if old_present and new_present:
                reasons.add("value_changed")
        total += severity * decimal_v2(rule.weight)
    return sorted(changed), total, sorted(reasons)


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


def compare_graphs_v21(before: GraphV2, after: GraphV2, policy: ComparisonPolicyV2) -> DeltaV21:
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
            signals, size, reasons = _compare_signals(a[0], b[0], rules)
            if signals:
                rounded = size.quantize(_MAG_PRECISION, rounding=ROUND_HALF_EVEN)
                if size > 0 and rounded == 0:
                    rounded = _MAG_PRECISION
                changed.append({
                    "key": list(key), "changed_signals": signals,
                    "reasons": reasons, "magnitude": _decimal_text(rounded),
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
        "schema_version": "provenance-delta-v2.1",
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
    return DeltaV21.model_validate_json(canonical_v2(content))

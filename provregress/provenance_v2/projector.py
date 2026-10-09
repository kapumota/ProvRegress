"""Proyector v2 de eventos observados: identidad independiente del ordinal."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from provregress.provenance_v2.schema import (
    EdgeV2, EventNodeV2, EventV2, GraphV2, V2Error, canonical_v2,
)
from provregress.storage.hashing import sha256_hex


def _id(parts: list[str]) -> str:
    return sha256_hex(canonical_v2(parts))


def validate_graph_v2(graph: GraphV2) -> None:
    """Verificación estructural independiente de constructor y del hash del modelo."""
    try:
        if not isinstance(graph, GraphV2):
            raise V2Error("Se requiere GraphV2.")
        checked = GraphV2.model_validate_json(canonical_v2(graph))
    except (ValidationError, ValueError, TypeError) as exc:
        raise V2Error("Schema o hash del grafo v2 inválido.") from exc
    nodes = {node.node_id: node for node in checked.events}
    if not nodes or len(nodes) != len(checked.events):
        raise V2Error("El grafo necesita eventos con identidad única.")
    if [x.node_id for x in checked.events] != sorted(nodes):
        raise V2Error("Nodos fuera de orden canónico.")
    if [x.sequence for x in sorted(checked.events, key=lambda n: n.sequence)] != list(range(len(nodes))):
        raise V2Error("Secuencias no contiguas.")
    seen_event_ids = set()
    for node in checked.events:
        if node.event_id in seen_event_ids:
            raise V2Error("event_id repetido.")
        seen_event_ids.add(node.event_id)
        if node.node_id != _id(["r0.10.node.v2", checked.run_id, node.event_id]):
            raise V2Error("ID de nodo adulterado.")
        canonical_v2(node.attributes)
        canonical_v2(node.semantic_values)
    if [edge.edge_id for edge in checked.edges] != sorted(set(e.edge_id for e in checked.edges)):
        raise V2Error("Aristas repetidas o desordenadas.")
    adjacency: dict[str, list[str]] = {x: [] for x in nodes}
    indegree = {x: 0 for x in nodes}
    for edge in checked.edges:
        if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
            raise V2Error("Extremo inexistente.")
        if edge.edge_id != _id(["r0.10.edge.v2", "observed_parent", edge.source_node_id, edge.target_node_id]):
            raise V2Error("ID de arista adulterado.")
        if nodes[edge.source_node_id].sequence >= nodes[edge.target_node_id].sequence:
            raise V2Error("Un padre no puede preceder con secuencia posterior.")
        adjacency[edge.source_node_id].append(edge.target_node_id)
        indegree[edge.target_node_id] += 1
    available = deque(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while available:
        node = available.popleft()
        visited += 1
        for child in adjacency[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                available.append(child)
    if visited != len(nodes):
        raise V2Error("El grafo contiene un ciclo.")


def project_trace_v2(events: Iterable[EventV2]) -> GraphV2:
    """Proyecta relaciones parentales declaradas sin inferir causalidad ni invocaciones."""
    try:
        items = [EventV2.model_validate_json(canonical_v2(x)) if isinstance(x, EventV2) else None for x in events]
    except (ValidationError, TypeError, ValueError) as exc:
        raise V2Error("El evento v2 no supera validación estricta.") from exc
    if not items or any(event is None for event in items):
        raise V2Error("Se necesitan EventV2 validados no vacíos.")
    checked = [event for event in items if event is not None]
    first = checked[0]
    markers = ("run_id", "app_id", "case_id", "repeat_index", "condition_id", "system_version_id")
    for position, event in enumerate(checked):
        if event.sequence != position:
            raise V2Error("Los eventos deben tener secuencias contiguas en orden de entrada.")
        if any(getattr(event, key) != getattr(first, key) for key in markers):
            raise V2Error("Mezcla de identidades de ejecución.")
    nodes: dict[str, EventNodeV2] = {}
    relations: dict[str, EdgeV2] = {}
    previous_ids: dict[str, str] = {}
    for event in checked:
        if event.event_id in previous_ids:
            raise V2Error("event_id repetido.")
        node_id = _id(["r0.10.node.v2", event.run_id, event.event_id])
        nodes[node_id] = EventNodeV2(
            node_id=node_id, event_id=event.event_id, sequence=event.sequence,
            timestamp_utc=event.timestamp_utc, component_type=event.component_type,
            component_id=event.component_id, event_type=event.event_type,
            scope_path=list(event.scope_path), invocation_key=event.invocation_key,
            payload_hash=sha256_hex(canonical_v2(event.payload)),
            attributes=event.attributes, semantic_values=event.semantic_values,
        )
        for parent_id in event.parent_event_ids:
            if parent_id not in previous_ids:
                raise V2Error("Padre inexistente o posterior al evento hijo.")
            source = previous_ids[parent_id]
            edge_id = _id(["r0.10.edge.v2", "observed_parent", source, node_id])
            relations[edge_id] = EdgeV2(edge_id=edge_id, source_node_id=source,
                                        target_node_id=node_id)
        previous_ids[event.event_id] = node_id
    content: dict[str, Any] = {
        "schema_version": "provenance-graph-v2", "run_id": first.run_id,
        "app_id": first.app_id.value, "case_id": first.case_id,
        "repeat_index": first.repeat_index, "condition_id": first.condition_id,
        "system_version_id": first.system_version_id,
        "events": [nodes[key].model_dump(mode="json") for key in sorted(nodes)],
        "edges": [relations[key].model_dump(mode="json") for key in sorted(relations)],
    }
    content["graph_hash"] = sha256_hex(canonical_v2(content))
    graph = GraphV2.model_validate_json(canonical_v2(content))
    validate_graph_v2(graph)
    return graph

"""Proyección P2 conforme a los contratos congelados R0.8 F1-F3."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from provregress.schema.events import EventEnvelope
from provregress.schema.graph import (
    ComponentNode,
    EdgeKind,
    EventNode,
    GraphEdge,
    PayloadNode,
    ProvenanceGraph,
)
from provregress.storage.artifacts import ArtifactStore
from provregress.storage.hashing import canonical_json_bytes, sha256_hex
from provregress.storage.jsonl import EventLogError, validate_event_log


class ProjectionError(ValueError):
    """La traza no permite construir una proyección íntegra."""


class GraphValidationError(ProjectionError):
    """El grafo vulnera una invariante estructural o de aciclicidad."""


def _digest(parts: list[str]) -> str:
    """Deriva IDs sin usar el orden incidental ni información privilegiada."""
    return sha256_hex(canonical_json_bytes(parts))


def _edge(kind: EdgeKind, source: str, target: str) -> GraphEdge:
    """Materializa una arista tipada con dominio SHA-256 propio."""
    return GraphEdge(
        edge_id=_digest(["r0.8.edge.v1", kind.value, source, target]),
        edge_kind=kind,
        source_node_id=source,
        target_node_id=target,
    )


def _checked_graph(graph: ProvenanceGraph | dict[str, Any]) -> ProvenanceGraph:
    """Reconstruye un modelo estricto, incluso ante model_copy sin validación."""
    if not isinstance(graph, (ProvenanceGraph, dict)):
        raise GraphValidationError("Se requiere un ProvenanceGraph o su representación JSON.")
    try:
        data = graph.model_dump(mode="json") if isinstance(graph, ProvenanceGraph) else graph
        return ProvenanceGraph.model_validate_json(canonical_json_bytes(data))
    except (ValidationError, TypeError, ValueError, UnicodeError) as exc:
        raise GraphValidationError("El grafo no supera su schema y hash canónicos.") from exc


def validate_graph(graph: ProvenanceGraph | dict[str, Any]) -> None:
    """Valida orientación, relaciones completas y DAG con Kahn independiente."""
    checked = _checked_graph(graph)
    nodes = {node.node_id: node for node in checked.nodes}
    successors: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    incoming: dict[str, int] = {node_id: 0 for node_id in nodes}
    emits: dict[str, int] = {}
    produces: dict[str, int] = {}
    declared: set[tuple[str, str, str]] = set()
    incident: set[str] = set()
    allowed = {
        EdgeKind.EMITS: (ComponentNode, EventNode),
        EdgeKind.OBSERVED_PARENT: (EventNode, EventNode),
        EdgeKind.PRODUCES: (EventNode, PayloadNode),
    }

    for edge in checked.edges:
        source = nodes.get(edge.source_node_id)
        target = nodes.get(edge.target_node_id)
        if source is None or target is None:
            raise GraphValidationError("Una arista referencia un nodo inexistente.")
        expected_source, expected_target = allowed[edge.edge_kind]
        if not isinstance(source, expected_source) or not isinstance(target, expected_target):
            raise GraphValidationError("Una arista no respeta la orientación de sus tipos.")
        triple = (edge.edge_kind.value, edge.source_node_id, edge.target_node_id)
        if triple in declared:
            raise GraphValidationError("La arista tipada está duplicada.")
        declared.add(triple)
        successors[edge.source_node_id].append(edge.target_node_id)
        incoming[edge.target_node_id] += 1
        incident.add(edge.source_node_id)
        incident.add(edge.target_node_id)

        if edge.edge_kind is EdgeKind.EMITS:
            if (source.component_type, source.component_id) != (
                target.component_type, target.component_id
            ):
                raise GraphValidationError("El componente emisor no corresponde al evento.")
            emits[edge.target_node_id] = emits.get(edge.target_node_id, 0) + 1
        elif edge.edge_kind is EdgeKind.PRODUCES:
            if source.payload_hash != target.payload_hash:
                raise GraphValidationError("El digest del evento y su payload no coinciden.")
            produces[edge.source_node_id] = produces.get(edge.source_node_id, 0) + 1

    # No basta con que los IDs sean válidos: Kahn detecta ciclos estructurales.
    available = deque(node_id for node_id, degree in incoming.items() if degree == 0)
    visited = 0
    while available:
        source = available.popleft()
        visited += 1
        for target in successors[source]:
            incoming[target] -= 1
            if incoming[target] == 0:
                available.append(target)
    if visited != len(nodes):
        raise GraphValidationError("El grafo contiene un ciclo dirigido.")

    events = [node for node in checked.nodes if isinstance(node, EventNode)]
    if not events:
        raise GraphValidationError("El grafo debe contener al menos un evento.")
    sequences = sorted(node.sequence for node in events)
    if sequences != list(range(len(events))):
        raise GraphValidationError("Los eventos del grafo deben tener secuencia contigua.")
    for edge in checked.edges:
        if edge.edge_kind is EdgeKind.OBSERVED_PARENT:
            parent = nodes[edge.source_node_id]
            child = nodes[edge.target_node_id]
            if not isinstance(parent, EventNode) or not isinstance(child, EventNode):
                raise GraphValidationError("Los padres observados deben ser eventos.")
            if parent.sequence >= child.sequence:
                raise GraphValidationError("Un padre observado debe preceder al evento hijo.")
    for node in events:
        if emits.get(node.node_id) != 1 or produces.get(node.node_id) != 1:
            raise GraphValidationError("Cada evento requiere una emisión y una producción.")
    if len(incident) != len(nodes):
        raise GraphValidationError("El grafo contiene nodos de componente o payload huérfanos.")


def project_trace(
    events: Iterable[EventEnvelope], *, artifact_store: ArtifactStore | None = None
) -> ProvenanceGraph:
    """Construye nodos y aristas P2 exclusivamente desde eventos observados."""
    if artifact_store is not None and not isinstance(artifact_store, ArtifactStore):
        raise ProjectionError("El almacén opcional debe ser un ArtifactStore.")
    try:
        # La revalidación impide que model_copy(update=...) omita las invariantes.
        checked = [EventEnvelope.model_validate_json(canonical_json_bytes(item))
                   if isinstance(item, EventEnvelope) else None for item in events]
        if not checked or any(item is None for item in checked):
            raise ProjectionError("Se requiere una traza no vacía de EventEnvelope válidos.")
        validate_event_log(checked)
    except (ValidationError, EventLogError, TypeError, ValueError) as exc:
        if isinstance(exc, ProjectionError):
            raise
        raise ProjectionError("La traza no cumple el contrato R0.7.") from exc

    first = checked[0]
    assert first is not None
    nodes: dict[str, ComponentNode | EventNode | PayloadNode] = {}
    edges: dict[str, GraphEdge] = {}
    event_ids: dict[str, str] = {}
    for event in checked:
        assert event is not None
        run_id = event.run_id
        component_id = _digest([
            "r0.8.node.v1", run_id, "component", event.component_type.value,
            event.component_id,
        ])
        event_id = _digest(["r0.8.node.v1", run_id, "event", event.event_id])
        payload_id = _digest([
            "r0.8.node.v1", run_id, "payload", event.payload_hash.value,
        ])
        if component_id not in nodes:
            nodes[component_id] = ComponentNode(
                node_id=component_id, node_kind="component",
                component_type=event.component_type, component_id=event.component_id,
            )
        nodes[event_id] = EventNode(
            node_id=event_id, node_kind="event", event_id=event.event_id,
            sequence=event.sequence, timestamp_utc=event.timestamp_utc,
            event_type=event.event_type, component_type=event.component_type,
            component_id=event.component_id, payload_hash=event.payload_hash,
            attributes=event.attributes, error=event.error,
        )
        existing = nodes.get(payload_id)
        if existing is not None:
            if not isinstance(existing, PayloadNode) or existing.payload_ref != event.payload_ref:
                raise ProjectionError("Referencias incompatibles para el mismo digest de payload.")
        else:
            nodes[payload_id] = PayloadNode(
                node_id=payload_id, node_kind="payload",
                payload_hash=event.payload_hash, payload_ref=event.payload_ref,
            )
        if artifact_store is not None and event.payload_ref is not None:
            # El almacén verifica realmente los bytes, no solo hashes declarados.
            artifact_store.get_bytes(event.payload_ref)
        for edge in (_edge(EdgeKind.EMITS, component_id, event_id),
                     _edge(EdgeKind.PRODUCES, event_id, payload_id)):
            edges[edge.edge_id] = edge
        for parent in event.parent_event_ids:
            edge = _edge(EdgeKind.OBSERVED_PARENT, event_ids[parent], event_id)
            edges[edge.edge_id] = edge
        event_ids[event.event_id] = event_id

    content = {
        "schema_version": "provenance-graph-v1",
        "run_id": first.run_id,
        "app_id": first.app_id.value,
        "case_id": first.case_id,
        "condition_id": first.condition_id,
        "repeat_index": first.repeat_index,
        "system_version_id": first.system_version_id,
        "trace_hash": None,  # Una secuencia en memoria no acredita bytes de JSONL.
        "nodes": [nodes[key].model_dump(mode="json") for key in sorted(nodes)],
        "edges": [edges[key].model_dump(mode="json") for key in sorted(edges)],
    }
    content["graph_hash"] = sha256_hex(canonical_json_bytes(content))
    result = ProvenanceGraph.model_validate_json(canonical_json_bytes(content))
    validate_graph(result)
    return result

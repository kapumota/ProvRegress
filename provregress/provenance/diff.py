"""Diferencial tipado P3 conforme al contrato R0.8-F3 congelado."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from provregress.provenance.alignment import (
    GraphAlignment,
    align_graphs,
    semantic_key,
)
from provregress.provenance.projector import validate_graph
from provregress.schema.graph import (
    DeltaG,
    EventNode,
    ProvenanceGraph,
)
from provregress.storage.hashing import canonical_json_bytes, sha256_hex


class GraphDiffError(ValueError):
    """El diferencial no se puede derivar de forma inequívoca."""


def _snapshot(graph: ProvenanceGraph) -> ProvenanceGraph:
    """Revalida el modelo y sus aristas para evitar cambios sin validación."""
    if not isinstance(graph, ProvenanceGraph):
        raise GraphDiffError("Se requiere un ProvenanceGraph de entrada.")
    try:
        checked = ProvenanceGraph.model_validate_json(canonical_json_bytes(graph))
        validate_graph(checked)
    except (ValueError, TypeError) as exc:
        raise GraphDiffError("El grafo no cumple sus invariantes estructurales.") from exc
    return checked


def _canonical_sort(values: Iterable[Any]) -> list[Any]:
    """Ordena registros por bytes JSON, no por orden accidental de diccionarios."""
    return sorted(values, key=canonical_json_bytes)


def _edge_groups(
    graph: ProvenanceGraph,
    ambiguous_keys: set[tuple[str, ...]],
) -> tuple[set[tuple[str, tuple[str, ...], tuple[str, ...]]],
           Counter[tuple[str, tuple[str, ...], tuple[str, ...]]]]:
    """Separa relaciones comparables de incidencias en nodos ambiguos."""
    nodes = {node.node_id: node for node in graph.nodes}
    comparable: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    ambiguous: Counter[tuple[str, tuple[str, ...], tuple[str, ...]]] = Counter()
    for edge in graph.edges:
        source_key = semantic_key(nodes[edge.source_node_id])
        target_key = semantic_key(nodes[edge.target_node_id])
        key = (edge.edge_kind.value, source_key, target_key)
        if source_key in ambiguous_keys or target_key in ambiguous_keys:
            ambiguous[key] += 1
        elif key in comparable:
            # Si dos aristas distintas colapsan en una clave comparable, no
            # podemos interpretar la multiplicidad como una sola relación.
            raise GraphDiffError("Hay aristas semánticas duplicadas sin ambigüedad declarada.")
        else:
            comparable.add(key)
    return comparable, ambiguous


def _edge_record(key: tuple[str, tuple[str, ...], tuple[str, ...]]) -> dict[str, Any]:
    """Representa una arista por claves P3, nunca por IDs de un run."""
    kind, source_key, target_key = key
    return {
        "edge_kind": kind,
        "source_key": list(source_key),
        "target_key": list(target_key),
    }


def diff_graphs(baseline: ProvenanceGraph, candidate: ProvenanceGraph) -> DeltaG:
    """Calcula DeltaG sin inferir correspondencias ni relaciones no observadas.

    El alineamiento se realiza con el contrato I3; si alguno de los grafos no
    es comparable o no satisface I2, se propaga un error sin salida parcial.
    """
    before = _snapshot(baseline)
    after = _snapshot(candidate)
    alignment: GraphAlignment = align_graphs(before, after)
    left_nodes = {node.node_id: node for node in before.nodes}
    right_nodes = {node.node_id: node for node in after.nodes}

    node_added = [list(item.key) for item in alignment.candidate_only]
    node_removed = [list(item.key) for item in alignment.baseline_only]
    node_unchanged: list[list[str]] = []
    node_changed: list[dict[str, Any]] = []
    for pair in alignment.pairs:
        original = left_nodes[pair.baseline_node_id]
        revised = right_nodes[pair.candidate_node_id]
        if isinstance(original, EventNode) and isinstance(revised, EventNode):
            observed = {"payload_hash", "attributes", "error"}
            left = original.model_dump(mode="json", include=observed)
            right = revised.model_dump(mode="json", include=observed)
            modified = sorted(field for field in observed
                              if canonical_json_bytes(left[field]) != canonical_json_bytes(right[field]))
            if modified:
                node_changed.append({"key": list(pair.key),
                                     "changed_fields": sorted(modified)})
            else:
                node_unchanged.append(list(pair.key))
        else:
            node_unchanged.append(list(pair.key))

    node_ambiguous = [
        {"key": list(group.key), "baseline_count": group.baseline_count,
         "candidate_count": group.candidate_count}
        for group in alignment.ambiguous
    ]
    ambiguous_keys = {group.key for group in alignment.ambiguous}
    comparable_before, unclear_before = _edge_groups(before, ambiguous_keys)
    comparable_after, unclear_after = _edge_groups(after, ambiguous_keys)
    edge_added = [_edge_record(key) for key in comparable_after - comparable_before]
    edge_removed = [_edge_record(key) for key in comparable_before - comparable_after]
    edge_ambiguous = [
        {**_edge_record(key), "side": side, "count": count}
        for side, groups in (("baseline", unclear_before), ("candidate", unclear_after))
        for key, count in groups.items()
    ]
    content: dict[str, Any] = {
        "schema_version": "provenance-delta-v1",
        "baseline_run_id": before.run_id,
        "candidate_run_id": after.run_id,
        "node_added": _canonical_sort(node_added),
        "node_removed": _canonical_sort(node_removed),
        "node_unchanged": _canonical_sort(node_unchanged),
        "node_changed": _canonical_sort(node_changed),
        "node_ambiguous": _canonical_sort(node_ambiguous),
        "edge_added": _canonical_sort(edge_added),
        "edge_removed": _canonical_sort(edge_removed),
        "edge_ambiguous": _canonical_sort(edge_ambiguous),
    }
    content["delta_hash"] = sha256_hex(canonical_json_bytes(content))
    return DeltaG.model_validate_json(canonical_json_bytes(content))

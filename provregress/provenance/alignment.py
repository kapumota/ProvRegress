"""Alineamiento conservador P3 entre grafos de procedencia observada."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TypeAlias

from provregress.provenance.projector import GraphValidationError, validate_graph
from provregress.schema.graph import (
    ComponentNode,
    EventNode,
    PayloadNode,
    ProvenanceGraph,
)
from provregress.storage.hashing import canonical_json_bytes


SemanticKeyTuple: TypeAlias = tuple[str, ...]
GraphNodeInstance: TypeAlias = ComponentNode | EventNode | PayloadNode


class AlignmentError(ValueError):
    """No es posible obtener una correspondencia verificable entre grafos."""


class GraphComparisonError(AlignmentError):
    """Los grafos no pertenecen a ejecuciones comparables en P3."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AlignedNode:
    """Pareja inequívoca identificada por una clave semántica compartida."""

    key: SemanticKeyTuple
    baseline_node_id: str
    candidate_node_id: str


@dataclass(frozen=True, slots=True)
class UnmatchedNode:
    """Nodo único presente solo en una de las ejecuciones."""

    key: SemanticKeyTuple
    node_id: str


@dataclass(frozen=True, slots=True)
class AmbiguousGroup:
    """Eventos repetidos sin correspondencia confiable entre ejecuciones."""

    key: SemanticKeyTuple
    baseline_node_ids: tuple[str, ...]
    candidate_node_ids: tuple[str, ...]

    @property
    def baseline_count(self) -> int:
        """Cantidad de candidatos observados en la ejecución baseline."""
        return len(self.baseline_node_ids)

    @property
    def candidate_count(self) -> int:
        """Cantidad de candidatos observados en la ejecución candidate."""
        return len(self.candidate_node_ids)


@dataclass(frozen=True, slots=True)
class GraphAlignment:
    """Correspondencia parcial e inyectiva, sin calcular todavía DeltaG."""

    baseline_run_id: str
    candidate_run_id: str
    pairs: tuple[AlignedNode, ...]
    baseline_only: tuple[UnmatchedNode, ...]
    candidate_only: tuple[UnmatchedNode, ...]
    ambiguous: tuple[AmbiguousGroup, ...]


def semantic_key(node: GraphNodeInstance) -> SemanticKeyTuple:
    """Obtiene una clave comparable sin run, reloj, secuencia ni payload de evento."""
    if isinstance(node, ComponentNode):
        return ("component", node.component_type.value, node.component_id)
    if isinstance(node, EventNode):
        return (
            "event", node.component_type.value, node.component_id, node.event_type.value,
        )
    if isinstance(node, PayloadNode):
        return ("payload", node.payload_hash.value)
    raise AlignmentError("Se requiere un nodo de procedencia válido.")


def _checked(graph: ProvenanceGraph) -> ProvenanceGraph:
    """Revalida snapshots y su topología antes de extraer claves semánticas."""
    if not isinstance(graph, ProvenanceGraph):
        raise AlignmentError("Se requiere un ProvenanceGraph para el alineamiento.")
    try:
        # Reconstruir impide usar atributos alterados mediante model_copy(update=...).
        snapshot = ProvenanceGraph.model_validate_json(canonical_json_bytes(graph))
        validate_graph(snapshot)
    except (ValueError, TypeError, GraphValidationError) as exc:
        raise AlignmentError("El grafo no supera la validación estructural P2.") from exc
    return snapshot


def _group_by_key(graph: ProvenanceGraph) -> dict[SemanticKeyTuple, list[str]]:
    """Agrupa nodos sin asignar parejas por orden ni por digest observable."""
    groups: dict[SemanticKeyTuple, list[str]] = defaultdict(list)
    for node in graph.nodes:
        groups[semantic_key(node)].append(node.node_id)
    return {key: sorted(ids) for key, ids in groups.items()}


def align_graphs(baseline: ProvenanceGraph, candidate: ProvenanceGraph) -> GraphAlignment:
    """Alinea solo claves únicas; conserva como ambiguos los eventos repetidos."""
    before = _checked(baseline)
    after = _checked(candidate)
    for field, code in (
        ("app_id", "app_mismatch"),
        ("case_id", "case_mismatch"),
        ("repeat_index", "repeat_mismatch"),
    ):
        if getattr(before, field) != getattr(after, field):
            raise GraphComparisonError(
                code, f"Los grafos no son comparables: {field} diferente."
            )

    groups_before = _group_by_key(before)
    groups_after = _group_by_key(after)
    pairs: list[AlignedNode] = []
    baseline_only: list[UnmatchedNode] = []
    candidate_only: list[UnmatchedNode] = []
    ambiguous: list[AmbiguousGroup] = []

    # Ordenar por bytes canónicos preserva el mismo orden usado por DeltaG.
    keys = sorted(
        groups_before.keys() | groups_after.keys(),
        key=lambda key: canonical_json_bytes(list(key)),
    )
    for key in keys:
        left = groups_before.get(key, [])
        right = groups_after.get(key, [])
        if len(left) > 1 or len(right) > 1:
            if key[0] != "event":
                raise AlignmentError("Solo una clase evento admite claves repetidas.")
            ambiguous.append(AmbiguousGroup(key, tuple(left), tuple(right)))
        elif left and right:
            pairs.append(AlignedNode(key, left[0], right[0]))
        elif left:
            baseline_only.append(UnmatchedNode(key, left[0]))
        elif right:
            candidate_only.append(UnmatchedNode(key, right[0]))

    return GraphAlignment(
        baseline_run_id=before.run_id,
        candidate_run_id=after.run_id,
        pairs=tuple(pairs),
        baseline_only=tuple(baseline_only),
        candidate_only=tuple(candidate_only),
        ambiguous=tuple(ambiguous),
    )

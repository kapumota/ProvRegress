"""M2-P2: separa descendencia posible de diferencias observadas.

No atribuye causalidad: un descendiente alcanzable puede permanecer igual; una
mutación aplicada puede no alterar ninguna señal funcional observada.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Literal

from pydantic import Field

from provregress.provenance_v2.comparison_v21 import DeltaV21, compare_graphs_v21
from provregress.provenance_v2.projector import validate_graph_v2
from provregress.provenance_v2.schema import ComparisonPolicyV2, GraphV2, V2Error, _Strict, canonical_v2
from provregress.storage.hashing import sha256_hex


class PropagationReportM2(_Strict):
    schema_version: Literal["mutation-propagation-m2-p2"] = "mutation-propagation-m2-p2"
    baseline_graph_hash: str
    candidate_graph_hash: str
    delta_hash: str
    potential_descendant_keys: list[list[str]]
    observed_functional_keys: list[list[str]]
    observed_descendant_keys: list[list[str]]
    structurally_changed_keys: list[list[str]]
    payload_only_keys: list[list[str]]
    impact: Literal[
        "functional_observed", "structural_only", "payload_only", "no_observable_change",
    ]
    silent_functional: bool
    confirmatory_execution: Literal[False] = False


def _node_map(graph: GraphV2) -> dict[tuple[str, ...], list[str]]:
    out: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for n in graph.events:
        out[n.key].append(n.node_id)
    return out


def _descendant_keys(graph: GraphV2, origin: tuple[str, ...]) -> set[tuple[str, ...]]:
    key_map = _node_map(graph)
    if origin not in key_map:
        return set()
    if len(key_map[origin]) != 1:
        raise V2Error("Raíz de propagación ambigua.")
    by_node = {n.node_id: n.key for n in graph.events}
    children: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        children[edge.source_node_id].add(edge.target_node_id)
    seen = {key_map[origin][0]}
    queue = deque(seen)
    descendants: set[tuple[str, ...]] = set()
    while queue:
        for next_id in children.get(queue.popleft(), set()):
            if next_id not in seen:
                seen.add(next_id)
                queue.append(next_id)
                descendants.add(by_node[next_id])
    return descendants


def audit_propagation_m2(
    before: GraphV2, after: GraphV2, delta: DeltaV21,
    *, policy: ComparisonPolicyV2, root_invocation_key: str,
) -> PropagationReportM2:
    """Cuenta cambios realmente comparados; la descendencia solo indica alcance."""
    validate_graph_v2(before)
    validate_graph_v2(after)
    delta = DeltaV21.model_validate_json(canonical_v2(delta))
    expected = compare_graphs_v21(before, after, policy)
    if canonical_v2(expected) != canonical_v2(delta):
        raise V2Error("El diferencial no corresponde a los grafos y política declarados.")
    if delta.baseline_run_id != before.run_id or delta.candidate_run_id != after.run_id:
        raise V2Error("El diferencial no corresponde a estos grafos.")
    if not root_invocation_key.strip():
        raise V2Error("Se requiere una raíz declarada por el piloto.")
    matches = [n.key for n in before.events if n.invocation_key == root_invocation_key]
    matches += [n.key for n in after.events if n.invocation_key == root_invocation_key]
    if len(set(matches)) != 1:
        raise V2Error("La raíz lógica no existe o no es inequívoca.")
    root = matches[0]
    if any(count > 1 for count in Counter(n.key for n in before.events).values()):
        raise V2Error("No se audita propagación sobre identidades ambiguas.")
    if any(count > 1 for count in Counter(n.key for n in after.events).values()):
        raise V2Error("No se audita propagación sobre identidades ambiguas.")
    potential = _descendant_keys(before, root) | _descendant_keys(after, root)
    functional = {tuple(n.key) for n in delta.changed_events}
    structural = {tuple(k) for k in delta.added_events + delta.removed_events}
    payload_only = {tuple(k) for k in delta.ignored_payload_changes}
    # La modificación de aristas es un cambio estructural aunque no cambie el número de eventos.
    for edge in delta.edges_added + delta.edges_removed:
        structural.add(tuple(edge.target_key))
    # Las aristas ambiguas no permiten atribuir localización.
    if delta.ambiguous_events or delta.edges_ambiguous:
        raise V2Error("El reporte exige correspondencias sin ambigüedades.")
    if functional:
        impact = "functional_observed"
    elif structural:
        impact = "structural_only"
    elif payload_only:
        impact = "payload_only"
    else:
        impact = "no_observable_change"
    sortkeys = lambda values: [list(k) for k in sorted(values, key=lambda k: canonical_v2(list(k)))]
    return PropagationReportM2(
        baseline_graph_hash=before.graph_hash, candidate_graph_hash=after.graph_hash,
        delta_hash=delta.delta_hash, potential_descendant_keys=sortkeys(potential),
        observed_functional_keys=sortkeys(functional),
        observed_descendant_keys=sortkeys(potential & functional),
        structurally_changed_keys=sortkeys(structural), payload_only_keys=sortkeys(payload_only),
        impact=impact, silent_functional=not bool(functional),
    )


def public_propagation_summary(report: PropagationReportM2) -> dict[str, object]:
    """No publicar identificadores semánticos, punteros ni tratamiento original."""
    return {
        "schema_version": report.schema_version,
        "impact": report.impact,
        "potential_descendants": len(report.potential_descendant_keys),
        "observed_descendants": len(report.observed_descendant_keys),
        "observed_functional": len(report.observed_functional_keys),
        "structural_changes": len(report.structurally_changed_keys),
        "payload_only": len(report.payload_only_keys),
        "silent_functional": report.silent_functional,
        "confirmatory_execution": False,
    }

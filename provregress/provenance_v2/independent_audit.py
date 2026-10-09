"""Comprobación de claves con anotaciones fijas ajenas al flujo de instrumentación.

No importa ni llama al plan de acciones ni a los testigos de live_workloads.
No constituye anotación humana independiente ni un corpus externo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from provregress.provenance_v2.comparison import compare_graphs_v2, sequential_baseline_view_v2
from provregress.provenance_v2.live_workloads import ExecutedRun, comparison_policy
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import V2Error
from provregress.schema.common import AppId


def _classify(run: ExecutedRun, annotation: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Reconstruye la operación desde el payload observado y el oráculo externo."""
    identities: dict[str, tuple[str, ...]] = {}
    declared: dict[str, str] = annotation["expected_keys"]
    for event in run.events:
        if event.event_type.value != annotation["event_type"]:
            continue
        if not isinstance(event.payload, dict):
            raise V2Error("Payload sin descriptor de operación auditable.")
        resource = event.payload.get(annotation["resource_field"])
        if resource not in declared or resource in identities:
            raise V2Error("Recurso no anotado o descriptor duplicado.")
        if event.invocation_key != declared[resource]:
            raise V2Error("Falso emparejamiento: clave distinta de la anotación externa.")
        identities[resource] = tuple(event.key)
    if not identities:
        raise V2Error("No hay operaciones auditables.")
    start = [x for x in run.events if x.event_type.value == "prompt.issued"]
    finish = [x for x in run.events if x.event_type.value == "outcome.recorded"]
    if len(start) != 1 or len(finish) != 1 or (
        start[0].invocation_key != annotation["root_key"]
        or finish[0].invocation_key != annotation["outcome_key"]
    ):
        raise V2Error("La identidad de inicio o resultado no coincide con la anotación.")
    return identities


def audit_dynamic_pair(
    baseline: ExecutedRun, candidate: ExecutedRun, *,
    app_id: AppId, annotations_path: Path,
) -> dict[str, Any]:
    """Falla ante falsos emparejamientos, omisiones o pérdida de relaciones."""
    if app_id not in {AppId.A2, AppId.A3}:
        raise V2Error("Solo se permiten A2 y A3.")
    document = json.loads(annotations_path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "r0.10-i3-reviewed-annotation-v1":
        raise V2Error("Versión de anotación no admitida.")
    annotation = document["a2" if app_id == AppId.A2 else "a3"]
    before_index = _classify(baseline, annotation)
    after_index = _classify(candidate, annotation)
    shared = before_index.keys() & after_index.keys()
    false_pairs = sum(before_index[r] != after_index[r] for r in shared)
    if false_pairs:
        raise V2Error("Las operaciones compartidas no conservaron su identidad.")
    if set(after_index) - set(before_index) != {annotation["expected_new_resource"]}:
        raise V2Error("La inserción no coincide con el recurso revisado.")
    if set(before_index) - set(after_index):
        raise V2Error("Una operación preexistente desapareció.")
    before_graph = project_trace_v2(baseline.events)
    after_graph = project_trace_v2(candidate.events)
    delta = compare_graphs_v2(before_graph, after_graph, comparison_policy(app_id))
    expected_added = after_index[annotation["expected_new_resource"]]
    if {tuple(x) for x in delta.added_events} != {expected_added}:
        raise V2Error("El diferencial no identifica exactamente la operación añadida.")
    if delta.changed_events or delta.ambiguous_events or delta.removed_events:
        raise V2Error("Se detectaron falsos cambios, pérdida o ambigüedad.")
    for run, graph in ((baseline, before_graph), (candidate, after_graph)):
        rows = sequential_baseline_view_v2(graph, include_parent_relations=True)
        real = {ev.event_id: ev for ev in run.events}
        if len(rows) != len(real) or any(
            row["parent_event_ids"] != real[row["event_id"]].parent_event_ids
            or tuple(row["semantic_key"]) != real[row["event_id"]].key
            for row in rows
        ):
            raise V2Error("El comparador secuencial perdió evidencia.")
    # El número de aristas no es una unidad adicional de regresión.
    return {
        "app_id": app_id.value,
        "shared_operations": len(shared),
        "false_pairs": false_pairs,
        "new_operations": len(after_index) - len(before_index),
        "changed_events": len(delta.changed_events),
        "ambiguous_event_rate": delta.ambiguous_event_rate,
        "baseline_events": len(baseline.events),
        "candidate_events": len(candidate.events),
        "delta_hash": delta.delta_hash,
        "passed": True,
    }

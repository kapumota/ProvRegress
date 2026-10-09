"""Calibración I4 reproducible: cohorte fijada, correspondencia y secuencia fuerte.

El evaluador de información equivalente usa únicamente filas secuenciales,
no importa ni ejecuta el algoritmo de DeltaV2. No declara superioridad causal.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from provregress.provenance_v2.comparison import (
    assert_pilot_alignment_v2, compare_graphs_v2, sequential_baseline_view_v2,
    topology_profile_v2,
)
from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.live_workloads import (
    DEFAULT_INPUTS, ExecutedRun, comparison_policy, demo_study,
)
from provregress.provenance_v2.persistent import persist_trace_v2, replay_trace_v2
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import ComparisonPolicyV2, V2Error, canonical_v2
from provregress.schema.common import AppId
from provregress.storage.artifacts import ArtifactStore
from provregress.storage.hashing import sha256_hex


@dataclass(frozen=True, slots=True)
class CohortPair:
    """Una pareja ejecutada y su procedencia íntegra."""

    baseline: ExecutedRun
    candidate: ExecutedRun
    app_id: AppId


def read_cohort(path: Path) -> dict[str, Any]:
    """Rechaza cohortes alteradas, casos repetidos o configuraciones abiertas."""
    data = json.loads(path.read_bytes())
    if data.get("schema_version") != "r0.10-i4-predeclared-cohort-v1":
        raise V2Error("La versión de cohorte no corresponde a I4.")
    if data.get("applications") != [AppId.A2.value, AppId.A3.value]:
        raise V2Error("Las aplicaciones de la cohorte están incompletas.")
    if data.get("repetitions") != [0, 1, 2]:
        raise V2Error("No se permite elegir repeticiones a partir del resultado.")
    if (data.get("max_ambiguity_rate") != "0.05" or
            data.get("minimum_target_coverage") != "1" or
            data.get("maximum_false_pairs") != 0 or
            data.get("maximum_missed_pairs") != 0 or
            data.get("information_parity_required") is not True):
        raise V2Error("Se alteraron los umbrales predeclarados.")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 10:
        raise V2Error("Faltan escenarios de cohorte.")
    expected = {(app.value, name) for app in (AppId.A2, AppId.A3)
                for name in ("identity", "insert", "remove", "noise", "functional")}
    found = {(row.get("app"), row.get("id")) for row in scenarios}
    if found != expected or len(found) != len(scenarios):
        raise V2Error("La cohorte contiene escenarios ausentes o duplicados.")
    for row in scenarios:
        if row.get("baseline") not in {"standard", "extended"} or row.get("candidate") not in {
            "standard", "extended", "noise", "functional"
        } or any(not isinstance(row.get(k), list) for k in ("added", "removed", "changed")):
            raise V2Error("Escenario fuera de las variantes permitidas.")
    return data


def _run_variant(app: AppId, variant: str, *, run_id: str, workspace: Path) -> ExecutedRun:
    """Los datos determinan las ramas; no consume el oráculo de resultados."""
    study = demo_study()
    if app == AppId.A2:
        if variant == "extended":
            return run_rag_dynamic(study=study, run_id=run_id, top_k=4)
        if variant == "standard":
            return run_rag_dynamic(study=study, run_id=run_id, top_k=3)
        corpus = workspace / "corpus"
        corpus.mkdir(parents=True)
        for source in DEFAULT_INPUTS.glob("*.md"):
            shutil.copyfile(source, corpus / source.name)
        refund = corpus / "refund.md"
        if variant == "noise":
            refund.write_text(refund.read_text(encoding="utf-8") + "\nNota editorial de muestra.\n", encoding="utf-8")
        elif variant == "functional":
            refund.write_text(refund.read_text(encoding="utf-8").replace("reembolso", "solicitud"),
                              encoding="utf-8")
        else:
            raise V2Error("Variante A2 no permitida.")
        return run_rag_dynamic(study=study, run_id=run_id, top_k=3, corpus=corpus)
    if app != AppId.A3:
        raise V2Error("Aplicación no permitida.")
    catalog = json.loads((DEFAULT_INPUTS / "catalog.json").read_text(encoding="utf-8"))
    if variant == "extended":
        catalog["enable_discount_step"] = True
    elif variant == "noise":
        catalog["item"]["price_units"] = 180
    elif variant == "functional":
        catalog["item"]["stock"] = 0
    elif variant != "standard":
        raise V2Error("Variante A3 no permitida.")
    path = workspace / "catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_v2(catalog))
    return run_tools_dynamic(study=study, run_id=run_id, catalog_path=path)


def _annotation_index(run: ExecutedRun, annotation: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Revisa identidades usando el recurso observado y un catálogo declarado aparte."""
    result: dict[str, tuple[str, ...]] = {}
    for event in run.events:
        if event.event_type.value == annotation["event_type"]:
            if not isinstance(event.payload, dict):
                raise V2Error("Payload auditable inválido.")
            resource = event.payload.get(annotation["resource_field"])
            if not isinstance(resource, str) or resource not in annotation["expected_keys"]:
                raise V2Error("Recurso no reconocido por la anotación independiente.")
            if resource in result or event.invocation_key != annotation["expected_keys"][resource]:
                raise V2Error("Correspondencia falsa, duplicada o recodificada.")
            result[resource] = tuple(event.key)
        elif event.event_type.value == "prompt.issued":
            if event.invocation_key != annotation["root_key"] or "__root__" in result:
                raise V2Error("Raíz ausente, duplicada o recodificada.")
            result["__root__"] = tuple(event.key)
        elif event.event_type.value == "outcome.recorded":
            if event.invocation_key != annotation["outcome_key"] or "__outcome__" in result:
                raise V2Error("Resultado ausente, duplicado o recodificado.")
            result["__outcome__"] = tuple(event.key)
        else:
            raise V2Error("Evento no anotado en la cohorte I4.")
    if "__root__" not in result or "__outcome__" not in result or len(result) != len(run.events):
        raise V2Error("Anotación incompleta.")
    return result


def _expected_resources(app: AppId, variant: str) -> set[str]:
    """Lista previa de recursos para impedir omisiones simétricas no detectadas."""
    if app == AppId.A2:
        base = {"refund.md", "returns.md", "shipping.md"}
        if variant == "extended":
            return base | {"tracking.md"}
        if variant in {"standard", "noise", "functional"}:
            return base
    elif app == AppId.A3:
        base = {"inventory", "tax", "receipt"}
        if variant == "extended":
            return base | {"discount"}
        if variant == "functional":
            return {"inventory"}
        if variant in {"standard", "noise"}:
            return base
    raise V2Error("Variante sin expectativa de recursos predeclarada.")


def _edges_from_rows(rows: list[dict[str, Any]]) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Conserva los enlaces parentales por event_id, sin proyectar a un grafo."""
    ids = {row["event_id"]: tuple(row["semantic_key"]) for row in rows}
    if len(ids) != len(rows):
        raise V2Error("Identificador secuencial duplicado.")
    result = set()
    for row in rows:
        for parent in row["parent_event_ids"]:
            if parent not in ids:
                raise V2Error("Padre desconocido en el baseline secuencial.")
            relation = (ids[parent], tuple(row["semantic_key"]))
            if relation in result:
                raise V2Error("Arista repetida en el baseline secuencial.")
            result.add(relation)
    return result


def strong_sequential_comparison(
    before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]],
    policy: ComparisonPolicyV2,
) -> dict[str, Any]:
    """Referencia secuencial sin dependencia de compare_graphs_v2 ni de DeltaV2.

    Usa las mismas claves observadas, señales, pesos y relaciones parentales.
    La paridad mide equivalencia informativa, no superioridad del grafo.
    """
    def index(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
        found = {}
        for row in rows:
            key = tuple(row["semantic_key"])
            if key in found:
                raise V2Error("El baseline fuerte no admite claves ambiguas.")
            found[key] = row
        return found

    left, right = index(before_rows), index(after_rows)
    rules = defaultdict(list)
    for rule in policy.rules:
        rules[rule.event_type.value].append(rule)
    changed: dict[tuple[str, ...], tuple[tuple[str, ...], str]] = {}
    assessed = set()
    for key in left.keys() & right.keys():
        applicable = rules.get(key[-1], [])
        if not applicable:
            continue
        assessed.add(key)
        different = []
        magnitude = Decimal(0)
        for rule in applicable:
            field = rule.field
            a = left[key]["semantic_values"].get(field)
            b = right[key]["semantic_values"].get(field)
            if a is None or b is None:
                raise V2Error("La vista secuencial carece de una señal exigida.")
            if rule.kind != "boolean":
                raise V2Error("El comparador fuerte I4 solo implementa señales booleanas.")
            if type(a) is not bool or type(b) is not bool:
                raise V2Error("Señal booleana inválida.")
            if a != b:
                different.append(field)
                magnitude += Decimal(rule.weight)
        if different:
            changed[key] = (tuple(sorted(different)), str(magnitude.normalize()))
    return {
        "added": set(right) - set(left),
        "removed": set(left) - set(right),
        "changed": changed,
        "assessed_shared": assessed,
        "edges_added": _edges_from_rows(after_rows) - _edges_from_rows(before_rows),
        "edges_removed": _edges_from_rows(before_rows) - _edges_from_rows(after_rows),
    }


def _summary_scores(rows: list[dict[str, Any]], policy: ComparisonPolicyV2) -> tuple[Decimal, Decimal]:
    """Salida sola y promedio de señales observables; no usan claves para localizar."""
    outcomes = [row for row in rows if row["semantic_key"][-1] == "outcome.recorded"]
    if len(outcomes) != 1:
        raise V2Error("Falta el único resultado de salida para el baseline output-only.")
    field = "answer_supported" if policy.app_id == AppId.A2 else "workflow_ok"
    output_value = outcomes[0]["semantic_values"].get(field)
    if type(output_value) is not bool:
        raise V2Error("Salida funcional no booleana.")
    observations: list[Decimal] = []
    for row in rows:
        for rule in policy.rules:
            if row["semantic_key"][-1] != rule.event_type.value:
                continue
            value = row["semantic_values"].get(rule.field)
            if rule.kind != "boolean" or type(value) is not bool:
                raise V2Error("El baseline agregado requiere señales booleanas completas.")
            observations.append(Decimal(int(value)) * Decimal(rule.weight))
    if not observations:
        raise V2Error("La métrica agregada no tiene observaciones.")
    return Decimal(int(output_value)), sum(observations) / Decimal(len(observations))


def _decimal_score(value: Decimal) -> str:
    """Conserva decimales como cadenas con precisión fija, nunca floats JSON."""
    return format(value.quantize(Decimal("0.000001")), "f")


def _report_pair(pair: CohortPair, scenario: dict[str, Any], annotation: dict[str, Any],
                 store: ArtifactStore) -> dict[str, Any]:
    before, after = pair.baseline, pair.candidate
    for run in (before, after):
        receipt = persist_trace_v2(run.events, store)
        if replay_trace_v2(receipt, store) != run.events:
            raise V2Error("La persistencia no conserva los eventos de I4.")
    observed_before = _annotation_index(before, annotation)
    observed_after = _annotation_index(after, annotation)
    for observed, variant in ((observed_before, scenario["baseline"]),
                              (observed_after, scenario["candidate"])):
        resources = set(observed) - {"__root__", "__outcome__"}
        if resources != _expected_resources(pair.app_id, variant):
            raise V2Error("La ejecución omitió o añadió recursos no autorizados por la cohorte.")
    shared = observed_before.keys() & observed_after.keys()
    reverse_before = {key: name for name, key in observed_before.items()}
    reverse_after = {key: name for name, key in observed_after.items()}
    if len(reverse_before) != len(observed_before) or len(reverse_after) != len(observed_after):
        raise V2Error("Dos operaciones lógicas comparten identidad semántica.")
    common_keys = reverse_before.keys() & reverse_after.keys()
    correct_pairs = sum(reverse_before[key] == reverse_after[key] for key in common_keys)
    false_pairs = len(common_keys) - correct_pairs
    missed_pairs = len(shared) - correct_pairs
    if false_pairs or missed_pairs:
        raise V2Error("Falsos emparejamientos o correspondencias perdidas.")
    left_graph = project_trace_v2(before.events)
    right_graph = project_trace_v2(after.events)
    policy = comparison_policy(pair.app_id)
    delta = compare_graphs_v2(left_graph, right_graph, policy)
    by_key_before = reverse_before
    by_key_after = reverse_after
    def names(keys: Any, mapping: dict[tuple[str, ...], str]) -> set[str]:
        return {mapping[tuple(k)] for k in keys}
    actual_added = names(delta.added_events, by_key_after)
    actual_removed = names(delta.removed_events, by_key_before)
    actual_changed = names((record.key for record in delta.changed_events), by_key_before)
    def decode(field: str) -> str:
        if field == annotation["outcome_key"]:
            return "__outcome__"
        for name, inv in annotation["expected_keys"].items():
            if field == inv:
                return name
        raise V2Error("El oráculo declara una operación desconocida.")
    for field, actual in (("added", actual_added), ("removed", actual_removed),
                          ("changed", actual_changed)):
        if actual != {decode(entry) for entry in scenario[field]}:
            raise V2Error(f"Diferencial {field} distinto del escenario predeclarado.")
    target_names = {k for k in shared if k not in {"__root__"}}
    target_keys = [observed_before[k] for k in sorted(target_names)]
    assert_pilot_alignment_v2(left_graph, right_graph, delta, policy=policy, target_keys=target_keys)
    baseline_rows = sequential_baseline_view_v2(left_graph, include_parent_relations=True)
    candidate_rows = sequential_baseline_view_v2(right_graph, include_parent_relations=True)
    strong = strong_sequential_comparison(baseline_rows, candidate_rows, policy)
    if (strong["added"] != {tuple(k) for k in delta.added_events} or
            strong["removed"] != {tuple(k) for k in delta.removed_events} or
            strong["changed"] != {
                tuple(row.key): (tuple(row.changed_signals), row.magnitude)
                for row in delta.changed_events
            } or
            strong["edges_added"] != {
                (tuple(e.source_key), tuple(e.target_key)) for e in delta.edges_added
            } or strong["edges_removed"] != {
                (tuple(e.source_key), tuple(e.target_key)) for e in delta.edges_removed
            }):
        raise V2Error("El baseline secuencial fuerte no tiene paridad con DeltaV2.")
    if len(target_keys) != len(target_names) or not all(k in strong["assessed_shared"] for k in target_keys):
        raise V2Error("Un objetivo no está cubierto por la política funcional.")
    baseline_output, baseline_aggregate = _summary_scores(baseline_rows, policy)
    candidate_output, candidate_aggregate = _summary_scores(candidate_rows, policy)
    baseline_magnitude = sum((Decimal(item.magnitude) for item in delta.changed_events), Decimal(0))
    before_topology = topology_profile_v2(left_graph)
    after_topology = topology_profile_v2(right_graph)
    if not before_topology["branched"] and not after_topology["branched"]:
        raise V2Error("La pareja I4 carece de topología ramificada en ambas ejecuciones.")
    return {
        "app_id": pair.app_id.value,
        "scenario": scenario["id"],
        "events_examined": len(before.events) + len(after.events),
        "shared_operations": len(shared),
        "false_pairs": false_pairs,
        "missed_pairs": missed_pairs,
        "ambiguous_event_rate": delta.ambiguous_event_rate,
        "eligible_targets": len(target_keys),
        "target_coverage": "1",
        "added_events": len(delta.added_events),
        "removed_events": len(delta.removed_events),
        "functional_changes": len(delta.changed_events),
        "functional_magnitude_sum": _decimal_score(baseline_magnitude),
        "output_only_distance": _decimal_score(abs(candidate_output - baseline_output)),
        "aggregate_metric_distance": _decimal_score(abs(candidate_aggregate - baseline_aggregate)),
        "strong_sequence_parity": True,
        "branched_baseline": before_topology["branched"],
        "branched_candidate": after_topology["branched"],
        "trace_hashes_verified": True,
    }


def run_cohort(*, cohort_path: Path, annotations_path: Path, output_dir: Path) -> dict[str, Any]:
    """Ejecuta toda la cohorte, no permite selección por éxito ni reescritura de resultados."""
    if output_dir.exists() or output_dir.is_symlink():
        raise V2Error("La salida debe ser un directorio nuevo.")
    cohort = read_cohort(cohort_path)
    annotations = json.loads(annotations_path.read_bytes())
    if annotations.get("schema_version") != "r0.10-i3-reviewed-annotation-v1":
        raise V2Error("Anotación independiente no reconocida.")
    output_dir.mkdir(parents=True)
    store = ArtifactStore(output_dir / "artifacts")
    reports = []
    for case in cohort["scenarios"]:
        app = AppId(case["app"])
        annotation = annotations["a2" if app == AppId.A2 else "a3"]
        for repeat in cohort["repetitions"]:
            work = output_dir / f"{app.value}-{case['id']}-{repeat}"
            work.mkdir()
            before = _run_variant(app, case["baseline"], run_id=f"i4-{app.value}-{case['id']}-{repeat}-base",
                                  workspace=work / "baseline")
            after = _run_variant(app, case["candidate"], run_id=f"i4-{app.value}-{case['id']}-{repeat}-candidate",
                                 workspace=work / "candidate")
            report = _report_pair(CohortPair(before, after, app), case, annotation, store)
            report["repetition"] = repeat
            reports.append(report)
    expected_pairs = len(cohort["scenarios"]) * len(cohort["repetitions"])
    if len(reports) != expected_pairs or any(r["false_pairs"] or r["missed_pairs"] or
            r["target_coverage"] != "1" or not r["strong_sequence_parity"] or
            Decimal(r["ambiguous_event_rate"]) > Decimal(cohort["max_ambiguity_rate"])
            for r in reports):
        raise V2Error("Alguna pareja no satisface los gates de la cohorte.")
    per_app = {}
    for app in cohort["applications"]:
        selected = [r for r in reports if r["app_id"] == app]
        per_app[app] = {
            "pairs": len(selected),
            "events_examined": sum(x["events_examined"] for x in selected),
            "false_pairs": sum(x["false_pairs"] for x in selected),
            "missed_pairs": sum(x["missed_pairs"] for x in selected),
            "eligible_targets": sum(x["eligible_targets"] for x in selected),
            "minimum_target_coverage": min(x["target_coverage"] for x in selected),
            "maximum_ambiguity": max(x["ambiguous_event_rate"] for x in selected),
            "strong_sequence_parity_pairs": sum(x["strong_sequence_parity"] for x in selected),
        }
    summary = {
        "schema_version": "r0.10-i4-cohort-report-v1",
        "cohort_sha256": sha256_hex(cohort_path.read_bytes()),
        "annotation_sha256": sha256_hex(annotations_path.read_bytes()),
        "pairs": expected_pairs,
        "per_app": per_app,
        "technical_gate": "pass_local_controlled",
        "scientific_freeze": "blocked_pending_external_validation",
        "superiority_over_sequence": "not_demonstrated",
    }
    summary["summary_sha256"] = sha256_hex(canonical_v2(summary))
    (output_dir / "summary.json").write_bytes(canonical_v2(summary) + b"\n")
    (output_dir / "pair-reports.json").write_bytes(canonical_v2(reports) + b"\n")
    return summary

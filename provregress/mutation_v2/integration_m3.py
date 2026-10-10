"""M3: une anclas M1 y tratamientos M2 en un piloto local aislado.

El operador JSON de M1 se conserva como ancla hipotética del evento,
NO se convierte a un operador de sistema ni se ejecuta. Solo SystemRequestM2
modifica una copia del snapshot. Ningún resultado constituye evidencia confirmatoria.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import Field, model_validator

from provregress.mutation_v2.observability import (
    ObservationContractM2, audit_observability_m2, assert_observable_plan_m2,
)
from provregress.mutation_v2.planning import MutationPlanV2, _private_canonical, verify_plan_v2
from provregress.mutation_v2.propagation_audit import audit_propagation_m2, public_propagation_summary
from provregress.mutation_v2.system_treatments import (
    SystemRequestM2, SystemSnapshotM2, read_system_snapshot,
    materialize_snapshot, stage_system_treatment,
)
from provregress.provenance_v2.comparison_v21 import compare_graphs_v21
from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.live_workloads import demo_study
from provregress.provenance_v2.projector import project_trace_v2, validate_graph_v2
from provregress.provenance_v2.schema import (
    AppId, ComparisonPolicyV2, EventV2, GraphV2, V2Error, _Strict, canonical_v2,
)
from provregress.schema.common import ComponentType
from provregress.schema.events import EventType
from provregress.storage.hashing import sha256_hex


class IntegrationErrorM3(V2Error):
    """Una precondición del vínculo M1/M2 no es verificable."""


class DeclaredSignalM3(_Strict):
    event_type: EventType
    field: str


class IntegrationPlanM3(_Strict):
    schema_version: Literal["mutation-integration-m3-v1"] = "mutation-integration-m3-v1"
    mode: Literal["pilot_local_only"] = "pilot_local_only"
    confirmatory_execution: Literal[False] = False
    app_id: AppId
    m1_plan_hash: str
    graph_hash: str
    policy_hash: str
    observation_contract_hash: str
    source_snapshot_hash: str
    candidate_snapshot_hash: str
    system_request: SystemRequestM2
    m1_request_id: str
    anchor_key: list[str]
    root_invocation_key: str
    expected_signals: list[DeclaredSignalM3] = Field(min_length=1)
    preflight_classification: Literal["observable_direct", "observable_propagated"]
    plan_hash: str

    @model_validator(mode="after")
    def integrity(self) -> "IntegrationPlanM3":
        data = self.model_dump(mode="json", exclude={"plan_hash"})
        if sha256_hex(_private_canonical(data)) != self.plan_hash:
            raise ValueError("Hash del plan integrado M3 inconsistente.")
        return self


class IntegratedReceiptM3(_Strict):
    schema_version: Literal["mutation-integration-receipt-m3-v1"] = "mutation-integration-receipt-m3-v1"
    confirmatory_execution: Literal[False] = False
    scientific_evidence: Literal["not_admissible"] = "not_admissible"
    plan_hash: str
    source_snapshot_hash: str
    candidate_snapshot_hash: str
    baseline_graph_hash: str
    candidate_graph_hash: str
    delta_hash: str
    observed_impact: Literal[
        "functional_observed", "structural_only", "payload_only", "no_observable_change",
    ]
    potential_descendants: int
    observed_descendants: int
    observed_functional: int
    payload_only: int
    expected_signal_count: int
    observed_expected_signal_count: int
    receipt_hash: str

    @model_validator(mode="after")
    def integrity(self) -> "IntegratedReceiptM3":
        raw = _private_canonical(self.model_dump(mode="json", exclude={"receipt_hash"}))
        if sha256_hex(raw) != self.receipt_hash:
            raise ValueError("Recibo integrado M3 alterado.")
        return self


def _checked(cls: type, value: Any) -> Any:
    if not isinstance(value, cls):
        raise IntegrationErrorM3("Tipo incompatible con el contrato integrado.")
    return cls.model_validate_json(_private_canonical(value))


def _origin_evidence(events: list[EventV2], snapshot: SystemSnapshotM2, app: AppId) -> None:
    """Vincula el origen observable con entradas locales, sin usar resultados candidate."""
    if app is AppId.A2:
        query = [e for e in events if e.invocation_key == "query:refund"]
        if len(query) != 1 or query[0].payload != {"query": snapshot.query}:
            raise IntegrationErrorM3("El prompt de origen no coincide con el snapshot.")
        retrievals = [e for e in events if e.event_type is EventType.RETRIEVAL_RETURNED]
        if not retrievals or len(retrievals) > snapshot.top_k:
            raise IntegrationErrorM3("La recuperación no coincide con la configuración original.")
        for event in retrievals:
            data = event.payload
            if not isinstance(data, dict) or data.get("document") not in snapshot.documents:
                raise IntegrationErrorM3("Recurso recuperado ajeno al snapshot.")
            if event.invocation_key != "retrieve:" + data["document"]:
                raise IntegrationErrorM3("Clave de recuperación inconsistente.")
            content = snapshot.documents[data["document"]].encode("utf-8")
            if data.get("source_sha256") != sha256_hex(content):
                raise IntegrationErrorM3("Hash de documento original inconsistente.")
    else:
        # El hash es de los bytes locales de catalog.json, no del snapshot completo.
        # La comprobación de bytes exactos se completa en el runner.
        prompts = [e for e in events if e.invocation_key == "request:order"]
        if len(prompts) != 1 or not isinstance(prompts[0].payload, dict):
            raise IntegrationErrorM3("Falta la solicitud observable A3.")
        digest = prompts[0].payload.get("catalog_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise IntegrationErrorM3("Falta la huella del catálogo A3.")


def _allowed_anchor(app: AppId, request: SystemRequestM2, node: Any) -> str:
    """Permite solo raíces verificables para los adaptadores locales A2/A3."""
    if app is AppId.A2 and request.operator_id in {
        "prompt.query.replace.v1", "retrieval.top_k.set.v1", "index.document.replace.v1",
    }:
        if (node.component_type is not ComponentType.RETRIEVER
                or node.event_type is not EventType.RETRIEVAL_RETURNED):
            raise IntegrationErrorM3("El ancla A2 requiere recuperación observada.")
        if (request.operator_id == "index.document.replace.v1"
                and node.invocation_key != "retrieve:" + request.target):
            raise IntegrationErrorM3("El documento intervenido no coincide con el ancla M1.")
        return (node.invocation_key if request.operator_id == "index.document.replace.v1"
                else "query:refund")
    if app is AppId.A3 and request.operator_id == "tool.catalog.field.set.v1":
        if (node.component_type is not ComponentType.TOOL
                or node.event_type is not EventType.TOOL_RETURNED
                or node.invocation_key != "tool:inventory"):
            raise IntegrationErrorM3("El ancla A3 requiere la llamada de inventario observada.")
        return "request:order"
    raise IntegrationErrorM3("Operador o aplicación incompatibles.")


def _single_leaf_change(before: SystemSnapshotM2, after: SystemSnapshotM2,
                        request: SystemRequestM2) -> None:
    """Rechaza modificaciones de configuración fuera del objetivo declarado."""
    old, new = before.model_dump(mode="python"), after.model_dump(mode="python")
    if request.operator_id == "prompt.query.replace.v1":
        path = ["query"]
    elif request.operator_id == "retrieval.top_k.set.v1":
        path = ["top_k"]
    elif request.operator_id == "index.document.replace.v1":
        path = ["documents", request.target]
    else:
        path = ["catalog", *request.target.split(".")]
    target = old
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = request.value
    if _private_canonical(old) != _private_canonical(new):
        raise IntegrationErrorM3("La intervención modificó campos fuera de su objetivo.")


def build_integration_plan_m3(
    *, m1_plan: MutationPlanV2, graph: GraphV2, policy: ComparisonPolicyV2,
    events: list[EventV2], observation: ObservationContractM2,
    snapshot: SystemSnapshotM2, system_request: SystemRequestM2,
    expected_signals: list[DeclaredSignalM3],
) -> IntegrationPlanM3:
    """Construye vínculo privado, sin ejecutar operadores ni elegir señales a posteriori."""
    m1_plan = _checked(MutationPlanV2, m1_plan)
    graph = _checked(GraphV2, graph)
    policy = _checked(ComparisonPolicyV2, policy)
    observation = _checked(ObservationContractM2, observation)
    snapshot = _checked(SystemSnapshotM2, snapshot)
    request = _checked(SystemRequestM2, system_request)
    validate_graph_v2(graph)
    verify_plan_v2(m1_plan, graph, policy)
    if graph.app_id not in (AppId.A2, AppId.A3) or len(m1_plan.intents) != 1:
        raise IntegrationErrorM3("M3 admite una intervención piloto A2/A3 por plan.")
    if not isinstance(events, list) or not events:
        raise IntegrationErrorM3("Faltan eventos fuente del plan.")
    checked_events = [_checked(EventV2, e) for e in events]
    if project_trace_v2(checked_events).graph_hash != graph.graph_hash:
        raise IntegrationErrorM3("Eventos fuente distintos del grafo M1.")
    _origin_evidence(checked_events, snapshot, graph.app_id)
    report = audit_observability_m2(m1_plan, graph, policy, checked_events, observation)
    assert_observable_plan_m2(report)
    anchor = m1_plan.intents[0]
    matches = [node for node in graph.events if list(node.key) == anchor.target_key]
    if len(matches) != 1 or matches[0].payload_hash != anchor.source_payload_hash:
        raise IntegrationErrorM3("Ancla M1 inexistente o ambigua.")
    root = _allowed_anchor(graph.app_id, request, matches[0])
    if sum(node.invocation_key == root for node in graph.events) != 1:
        raise IntegrationErrorM3("Raíz de propagación original ambigua o ausente.")
    if type(expected_signals) is not list or not expected_signals:
        raise IntegrationErrorM3("Se requieren señales declaradas previamente.")
    signals = [_checked(DeclaredSignalM3, e) for e in expected_signals]
    signal_keys = [(s.event_type.value, s.field) for s in signals]
    if signal_keys != sorted(set(signal_keys)):
        raise IntegrationErrorM3("Señales esperadas duplicadas o sin orden canónico.")
    allowed = {(r.event_type.value, r.field) for r in policy.rules}
    if not set(signal_keys).issubset(allowed):
        raise IntegrationErrorM3("Señal esperada fuera de la política predeclarada.")
    changed, receipt = stage_system_treatment(snapshot, request)
    _single_leaf_change(snapshot, changed, request)
    if receipt.source_snapshot_hash != snapshot.snapshot_hash:
        raise IntegrationErrorM3("La huella anterior no coincide con el snapshot.")
    content = {
        "schema_version": "mutation-integration-m3-v1", "mode": "pilot_local_only",
        "confirmatory_execution": False, "app_id": graph.app_id.value,
        "m1_plan_hash": m1_plan.plan_hash, "graph_hash": graph.graph_hash,
        "policy_hash": policy.policy_hash, "observation_contract_hash": observation.contract_hash,
        "source_snapshot_hash": snapshot.snapshot_hash,
        "candidate_snapshot_hash": changed.snapshot_hash,
        "system_request": request.model_dump(mode="json"),
        "m1_request_id": anchor.request_id, "anchor_key": anchor.target_key,
        "root_invocation_key": root,
        "expected_signals": [s.model_dump(mode="json") for s in signals],
        "preflight_classification": report.items[0].classification,
    }
    content["plan_hash"] = sha256_hex(_private_canonical(content))
    return IntegrationPlanM3.model_validate_json(_private_canonical(content))


def execute_local_integration_m3(
    *, plan: IntegrationPlanM3, m1_plan: MutationPlanV2,
    graph: GraphV2, policy: ComparisonPolicyV2, events: list[EventV2],
    observation: ObservationContractM2, source_dir: Path,
) -> IntegratedReceiptM3:
    """Ejecuta exclusivamente la copia candidate y comprueba el vínculo completo."""
    plan = _checked(IntegrationPlanM3, plan)
    source_dir = Path(source_dir)
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise IntegrationErrorM3("Se requiere fuente local ordinaria.")
    if plan.app_id is AppId.A2:
        snapshot = read_system_snapshot(source_dir)
    else:
        snapshot = read_system_snapshot(source_dir)
        raw = (source_dir / "catalog.json").read_bytes()
        prompt = [e for e in events if e.invocation_key == "request:order"]
        if len(prompt) != 1 or prompt[0].payload.get("catalog_sha256") != sha256_hex(raw):
            raise IntegrationErrorM3("Los bytes del catálogo original no coinciden con A3.")
    regenerated = build_integration_plan_m3(
        m1_plan=m1_plan, graph=graph, policy=policy, events=events,
        observation=observation, snapshot=snapshot, system_request=plan.system_request,
        expected_signals=plan.expected_signals,
    )
    if _private_canonical(regenerated) != _private_canonical(plan):
        raise IntegrationErrorM3("El plan M3 no corresponde a sus entradas originales.")
    changed, stage = stage_system_treatment(snapshot, plan.system_request)
    _single_leaf_change(snapshot, changed, plan.system_request)
    with TemporaryDirectory(prefix="provregress-m3-pilot-") as folder:
        directory, catalog = materialize_snapshot(changed, Path(folder) / "candidate")
        checked = read_system_snapshot(directory, query=changed.query, top_k=changed.top_k)
        if checked.snapshot_hash != changed.snapshot_hash:
            raise IntegrationErrorM3("La materialización cambió el snapshot candidato.")
        study = demo_study()
        if plan.app_id is AppId.A2:
            candidate = run_rag_dynamic(
                study=study, run_id="m3-pilot-candidate", corpus=directory,
                query=changed.query, top_k=changed.top_k,
            )
        else:
            candidate = run_tools_dynamic(
                study=study, run_id="m3-pilot-candidate", catalog_path=catalog,
            )
        graph_c = project_trace_v2(list(candidate.events))
        delta = compare_graphs_v21(graph, graph_c, policy)
        propagation = audit_propagation_m2(
            graph, graph_c, delta, policy=policy, root_invocation_key=plan.root_invocation_key,
        )
    if read_system_snapshot(source_dir).snapshot_hash != snapshot.snapshot_hash:
        raise IntegrationErrorM3("La fuente se modificó durante el piloto local.")
    # Un cambio en un descendiente no prueba causalidad; las señales esperadas
    # son posibilidades predeclaradas, no una lista para filtrar éxitos.
    declared = {(item.event_type, item.field) for item in plan.expected_signals}
    actual = {(node.event_type, field) for node in graph_c.events
              for field in node.semantic_values}
    observed_fields = len(declared & actual)
    public = public_propagation_summary(propagation)
    content = {
        "schema_version": "mutation-integration-receipt-m3-v1",
        "confirmatory_execution": False, "scientific_evidence": "not_admissible",
        "plan_hash": plan.plan_hash,
        "source_snapshot_hash": stage.source_snapshot_hash,
        "candidate_snapshot_hash": stage.candidate_snapshot_hash,
        "baseline_graph_hash": graph.graph_hash,
        "candidate_graph_hash": graph_c.graph_hash,
        "delta_hash": delta.delta_hash,
        "observed_impact": public["impact"],
        "potential_descendants": public["potential_descendants"],
        "observed_descendants": public["observed_descendants"],
        "observed_functional": public["observed_functional"],
        "payload_only": public["payload_only"],
        "expected_signal_count": len(declared),
        "observed_expected_signal_count": observed_fields,
    }
    content["receipt_hash"] = sha256_hex(_private_canonical(content))
    return IntegratedReceiptM3.model_validate_json(_private_canonical(content))


def public_integrated_summary_m3(receipt: IntegratedReceiptM3) -> dict[str, Any]:
    """No publica IDs de objetivos, operator_id, ruta, hash de plan o parámetros."""
    r = _checked(IntegratedReceiptM3, receipt)
    return {
        "schema_version": r.schema_version, "observed_impact": r.observed_impact,
        "potential_descendants": r.potential_descendants,
        "observed_descendants": r.observed_descendants,
        "observed_functional": r.observed_functional,
        "payload_only": r.payload_only,
        "expected_signal_count": r.expected_signal_count,
        "observed_expected_signal_count": r.observed_expected_signal_count,
        "confirmatory_execution": False, "scientific_evidence": "not_admissible",
    }

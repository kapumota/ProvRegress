"""Adaptadores A2/A3 con decisiones de flujo basadas en datos leídos en ejecución.

Las claves representan recursos y operaciones semánticas, nunca posiciones o hashes
resultado. Este módulo no importa anotaciones externas ni resultados de auditoría.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from provregress.pilot.firewall import PilotFirewall
from provregress.provenance_v2.live_workloads import (
    CASE_RAG, CASE_TOOLS, DEFAULT_INPUTS, ExecutedRun, ExecutionRecorder,
    LogicalOperation, ObservableResult,
)
from provregress.provenance_v2.schema import V2Error, canonical_v2
from provregress.schema.common import AppId, ComponentType
from provregress.schema.events import EventType
from provregress.schema.manifests import PilotStudyManifest
from provregress.storage.hashing import sha256_hex


def _operation(name: str, *, app: str, kind: EventType, component: ComponentType,
               component_id: str, parents: tuple[str, ...] = ()) -> LogicalOperation:
    """Asigna la identidad cuando la operación es seleccionada por el ejecutor."""
    return LogicalOperation(
        logical_id=name, invocation_key=name,
        scope_path=(app, "dynamic-workflow"), event_type=kind,
        component_type=component, component_id=component_id, parents=parents,
    )


def _terms(value: str) -> set[str]:
    return set(re.findall(r"\w+", value.lower()))


def run_rag_dynamic(
    *, study: PilotStudyManifest, run_id: str, corpus: Path | None = None,
    query: str = "reembolso", top_k: int = 3, case_id: str = CASE_RAG,
) -> ExecutedRun:
    """Descubre documentos y decide durante la recuperación cuáles ejecutar."""
    PilotFirewall(study).assert_pilot_case(case_id)
    if type(top_k) is not int or not 1 <= top_k <= 32 or not query.strip():
        raise V2Error("Consulta o presupuesto de recuperación inválidos.")
    recorder = ExecutionRecorder(
        study=study, app_id=AppId.A2, case_id=case_id,
        run_id=run_id, condition_id="rag-dynamic", system_version_id="rag-adapter-i3",
    )
    recorder.record(
        _operation("query:refund", app="rag", kind=EventType.PROMPT_ISSUED,
                   component=ComponentType.PROMPT, component_id="query"),
        lambda: ObservableResult({"query": query}, {}, {}),
    )
    directory = corpus or DEFAULT_INPUTS
    if not directory.is_dir():
        raise V2Error("El directorio de documentos no existe.")
    candidates = []
    for path in directory.glob("*.md"):
        # La lectura y la puntuación se realizan efectivamente antes de seleccionar la rama.
        raw = path.read_bytes()
        content = raw.decode("utf-8")
        hits = sorted(_terms(query) & _terms(content))
        candidates.append((len(hits), path.name, raw, hits))
    ranked = sorted(candidates, key=lambda x: (-x[0], x[1]))[:top_k]
    if not ranked:
        raise V2Error("No se encontraron documentos en el corpus.")
    parents = []
    for _, name, data, hits in ranked:
        identity = f"retrieve:{name}"
        # La etiqueta 'document' permite auditoría posterior del recurso realmente leído.
        recorder.record(
            _operation(identity, app="rag", kind=EventType.RETRIEVAL_RETURNED,
                       component=ComponentType.RETRIEVER, component_id="file-retrieval",
                       parents=("query:refund",)),
            lambda data=data, hits=hits, name=name: ObservableResult(
                {"document": name, "source_sha256": sha256_hex(data), "matched_terms": hits},
                {"evidence_found": bool(hits)}, {},
            ),
        )
        parents.append(identity)
    support = any(score > 0 for score, *_ in ranked)
    recorder.record(
        _operation("compose:answer", app="rag", kind=EventType.OUTCOME_RECORDED,
                   component=ComponentType.OUTCOME, component_id="answer-composer",
                   parents=tuple(parents)),
        lambda: ObservableResult({"sources": sorted(n for _, n, _, _ in ranked)},
                                 {"answer_supported": support}, {}),
    )
    return recorder.finish()


def _tool_result(name: str, item: dict[str, object]) -> ObservableResult:
    if name == "inventory":
        result = int(item["stock"]) >= int(item["quantity"])
    elif name == "tax":
        # El dominio experimental de esta carga usa precios enteros en unidades.
        result = str(int(item["price_units"]) * 18 // 100)
    elif name == "receipt":
        result = int(item["quantity"]) > 0
    elif name == "discount":
        result = bool(item["discount_eligible"])
    else:
        raise V2Error("Herramienta fuera de la lista permitida.")
    return ObservableResult(
        {"operation": name, "result": result},
        {"task_ok": bool(result) if name != "tax" else True}, {},
    )


def run_tools_dynamic(
    *, study: PilotStudyManifest, run_id: str,
    catalog_path: Path | None = None, case_id: str = CASE_TOOLS,
) -> ExecutedRun:
    """Selecciona herramientas a partir del estado leído, no de un plan de llamadas."""
    PilotFirewall(study).assert_pilot_case(case_id)
    path = catalog_path or DEFAULT_INPUTS / "catalog.json"
    raw = path.read_bytes()
    catalog = json.loads(raw)
    canonical_v2(catalog)
    item = catalog["item"]
    if not isinstance(item, dict) or not all(k in item for k in (
        "stock", "quantity", "price_units", "discount_eligible",
    )):
        raise V2Error("Catálogo incompatible con el adaptador A3.")
    recorder = ExecutionRecorder(
        study=study, app_id=AppId.A3, case_id=case_id,
        run_id=run_id, condition_id="tools-dynamic", system_version_id="tools-adapter-i3",
    )
    recorder.record(
        _operation("request:order", app="tools", kind=EventType.PROMPT_ISSUED,
                   component=ComponentType.PROMPT, component_id="order-request"),
        lambda: ObservableResult({"catalog_sha256": sha256_hex(raw)}, {}, {}),
    )
    completed = []
    # La política de ramificación se evalúa después de leer el catálogo.
    available = int(item["stock"]) >= int(item["quantity"])
    actions = ["inventory"]
    if available:
        actions.extend(["tax", "receipt"])
        if catalog.get("enable_discount_step") is True:
            actions.append("discount")
    for action in actions:
        identity = f"tool:{action}"
        recorder.record(
            _operation(identity, app="tools", kind=EventType.TOOL_RETURNED,
                       component=ComponentType.TOOL, component_id="catalog-toolkit",
                       parents=("request:order",)),
            lambda action=action: _tool_result(action, item),
        )
        completed.append(identity)
    recorder.record(
        _operation("finish:order", app="tools", kind=EventType.OUTCOME_RECORDED,
                   component=ComponentType.OUTCOME, component_id="order-outcome",
                   parents=tuple(completed)),
        lambda: ObservableResult({"executed": len(completed)},
                                 {"workflow_ok": available}, {}),
    )
    return recorder.finish()

"""Ejecuciones A2/A3 locales observables, con testigo lógico externo al evento.

No deriva invocation_key del reloj, índice de emisión o contenido de respuesta.
Este módulo es un laboratorio ejecutable, no un runner confirmatorio.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from provregress.pilot.firewall import PilotFirewall
from provregress.provenance_v2.schema import (
    ComparisonPolicyV2, EventV2, SignalRule, V2Error, canonical_v2,
)
from provregress.schema.common import AppId, ComponentType
from provregress.schema.events import EventType
from provregress.schema.manifests import PilotStudyManifest
from provregress.storage.hashing import hash_case_ids, sha256_hex


CASE_RAG = "pilot-rag-local"
CASE_TOOLS = "pilot-tools-local"
DEFAULT_INPUTS = Path(__file__).resolve().parents[2] / "examples" / "provenance_v2_inputs"


@dataclass(frozen=True, slots=True)
class LogicalOperation:
    """Plan lógico explícito; logical_id pertenece solo al oráculo, no al evento."""

    logical_id: str
    invocation_key: str
    scope_path: tuple[str, ...]
    event_type: EventType
    component_type: ComponentType
    component_id: str
    parents: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ObservableResult:
    """Información calculada por la operación realmente ejecutada."""

    payload: Any
    semantic_values: dict[str, Any]
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Witness:
    """Testigo privilegiado tomado del plan, sin incorporarlo a EventV2."""

    event_id: str
    logical_id: str


@dataclass(frozen=True, slots=True)
class ExecutedRun:
    """Conserva separadas las observaciones del testigo independiente."""

    events: tuple[EventV2, ...]
    witness: tuple[Witness, ...]
    completed_calls: tuple[str, ...]

    def observable_jsonl(self) -> bytes:
        return b"".join(canonical_v2(event) + b"\n" for event in self.events)

    def witness_json(self) -> bytes:
        return canonical_v2({"witness": [
            {"event_id": row.event_id, "logical_id": row.logical_id}
            for row in self.witness
        ]}) + b"\n"


class ExecutionRecorder:
    """Registra solo operaciones ejecutadas después de autorizar el caso piloto."""

    def __init__(
        self, *, study: PilotStudyManifest, app_id: AppId, case_id: str,
        run_id: str, condition_id: str, system_version_id: str,
        repeat_index: int = 0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # El firewall debe ejecutarse antes de abrir archivos o llamar herramientas.
        PilotFirewall(study).assert_pilot_case(case_id)
        if not all(isinstance(x, str) and x.strip() for x in (
            run_id, condition_id, system_version_id,
        )):
            raise V2Error("Identidad de ejecución incompleta.")
        if type(repeat_index) is not int or repeat_index < 0:
            raise V2Error("Índice de repetición inválido.")
        if not isinstance(app_id, AppId):
            raise V2Error("Aplicación fuera del contrato.")
        if clock is not None and not callable(clock):
            raise V2Error("Reloj inválido.")
        self._context = (app_id, case_id, run_id, condition_id, system_version_id, repeat_index)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._events: list[EventV2] = []
        self._witness: list[Witness] = []
        self._completed: dict[str, str] = {}
        self._keys: set[tuple[str, ...]] = set()
        self._calls: list[str] = []

    def record(self, op: LogicalOperation, callback: Callable[[], ObservableResult]) -> EventV2:
        """Comprueba claves y padres antes de llamar; emite solo al completar."""
        if not isinstance(op, LogicalOperation) or not callable(callback):
            raise V2Error("Se requiere una operación y callback válidos.")
        if not op.logical_id.strip() or not op.invocation_key.strip() or not op.scope_path:
            raise V2Error("La operación necesita identidad lógica estable.")
        if any(not segment.strip() for segment in op.scope_path):
            raise V2Error("Segmento de ámbito vacío.")
        if op.logical_id in self._completed:
            raise V2Error("Operación lógica ejecutada dos veces sin identidad distinta.")
        key = ("event", op.component_type.value, op.component_id,
               *op.scope_path, op.invocation_key, op.event_type.value)
        if key in self._keys:
            raise V2Error("Colisión de invocation_key antes de ejecutar la operación.")
        if len(set(op.parents)) != len(op.parents) or any(
            parent not in self._completed for parent in op.parents
        ):
            raise V2Error("Una dependencia lógica no ha terminado.")
        result = callback()
        if not isinstance(result, ObservableResult):
            raise V2Error("Una operación no devolvió un ObservableResult.")
        app_id, case_id, run_id, condition_id, version, repeat = self._context
        event = EventV2(
            run_id=run_id, event_id=f"evt-{len(self._events):08d}",
            sequence=len(self._events), timestamp_utc=self._clock(),
            app_id=app_id, case_id=case_id, repeat_index=repeat,
            system_version_id=version, condition_id=condition_id,
            component_type=op.component_type, component_id=op.component_id,
            event_type=op.event_type, scope_path=list(op.scope_path),
            invocation_key=op.invocation_key,
            parent_event_ids=[self._completed[parent] for parent in op.parents],
            payload=result.payload, attributes=result.attributes,
            semantic_values=result.semantic_values,
        )
        self._events.append(event)
        self._completed[op.logical_id] = event.event_id
        self._keys.add(key)
        self._witness.append(Witness(event.event_id, op.logical_id))
        self._calls.append(op.logical_id)
        return event

    def finish(self) -> ExecutedRun:
        if not self._events:
            raise V2Error("No se registró ninguna operación real.")
        if len(self._calls) != len(self._witness) or len(self._calls) != len(self._events):
            raise V2Error("Testigo y log de llamadas inconsistentes.")
        return ExecutedRun(tuple(self._events), tuple(self._witness), tuple(self._calls))


def demo_study() -> PilotStudyManifest:
    """Partición exclusiva para este laboratorio, nunca para confirmatorios."""
    pilot = [CASE_RAG, CASE_TOOLS]
    holdout = ["confirmatory-rag-local", "confirmatory-tools-local"]
    return PilotStudyManifest(
        pilot_id="r010-i1-local-only", protocol_version="r0.10-i1",
        pilot_case_ids=pilot, confirmatory_case_ids=holdout,
        pilot_case_ids_hash=hash_case_ids(pilot),
        confirmatory_case_ids_hash=hash_case_ids(holdout),
        analysis_plan_version="instrumentation-i1",
    )


def comparison_policy(app_id: AppId) -> ComparisonPolicyV2:
    if app_id == AppId.A2:
        rules = [
            SignalRule(event_type=EventType.RETRIEVAL_RETURNED, field="evidence_found",
                       kind="boolean", weight="1"),
            SignalRule(event_type=EventType.OUTCOME_RECORDED, field="answer_supported",
                       kind="boolean", weight="1"),
        ]
    elif app_id == AppId.A3:
        rules = [
            SignalRule(event_type=EventType.TOOL_RETURNED, field="task_ok",
                       kind="boolean", weight="1"),
            SignalRule(event_type=EventType.OUTCOME_RECORDED, field="workflow_ok",
                       kind="boolean", weight="1"),
        ]
    else:
        raise V2Error("I1 solo instrumenta A2 y A3.")
    return ComparisonPolicyV2(app_id=app_id, rules=rules)


def _op(logical_id: str, key: str, *, app: str, event_type: EventType,
        component_type: ComponentType, component_id: str,
        parents: Sequence[str] = ()) -> LogicalOperation:
    return LogicalOperation(logical_id, key, (app, "local-workflow"), event_type,
                            component_type, component_id, tuple(parents))


def _search_local(path: Path, query: str, *, disable_match: bool, noisy: bool) -> ObservableResult:
    """Lee bytes reales del corpus y busca términos, sin proveedor externo ni LLM."""
    content_bytes = path.read_bytes()
    content = content_bytes.decode("utf-8")
    tokens = set(re.findall(r"\w+", content.lower()))
    terms = set(re.findall(r"\w+", query.lower()))
    hits = sorted(tokens & terms)
    if disable_match:
        hits = []
    payload: dict[str, Any] = {
        "document": path.name, "matched_terms": hits,
        "source_sha256": sha256_hex(content_bytes),
    }
    attributes = {"latency_ms": 11, "token_count": len(tokens)}
    if noisy:
        payload["execution_nonce"] = "variation-2"
        attributes = {"latency_ms": 999, "token_count": len(tokens) + 2}
    return ObservableResult(payload, {"evidence_found": bool(hits)}, attributes)


def run_rag_local(
    *, study: PilotStudyManifest, run_id: str,
    scenario: Literal["baseline", "insert", "reorder", "noise", "functional", "rekey", "retry"] = "baseline",
    corpus: Path | None = None, case_id: str = CASE_RAG,
) -> ExecutedRun:
    """Ejecuta búsquedas concurrentes sobre archivos y registra el DAG observado."""
    recorder = ExecutionRecorder(
        study=study, app_id=AppId.A2, case_id=case_id, run_id=run_id,
        condition_id=scenario, system_version_id="rag-local-v1",
    )
    root = "rag.query"
    recorder.record(
        _op(root, "answer-refund-question", app="rag", event_type=EventType.PROMPT_ISSUED,
            component_type=ComponentType.PROMPT, component_id="user-question"),
        lambda: ObservableResult({"query": "reembolso"}, {}, {}),
    )
    directory = corpus or DEFAULT_INPUTS
    work = [
        ("rag.refund", "refund-document", "refund.md"),
        ("rag.shipping", "shipping-document", "shipping.md"),
        ("rag.returns", "return-terms", "returns.md"),
    ]
    if scenario == "insert":
        work.insert(0, ("rag.tracking", "tracking-document", "tracking.md"))
    if scenario == "reorder":
        work.reverse()
    if scenario == "rekey":
        work = [(ident, "shipping-document" if ident == "rag.refund" else
                 "refund-document" if ident == "rag.shipping" else key, filename)
                for ident, key, filename in work]
    results: dict[str, ObservableResult] = {}
    # Las funciones de búsqueda se ejecutan realmente en hilos diferentes.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                _search_local, directory / filename, "reembolso",
                disable_match=(scenario == "functional" and ident == "rag.refund"),
                noisy=(scenario == "noise"),
            ): (ident, key)
            for ident, key, filename in work
        }
        for future in as_completed(futures):
            ident, key = futures[future]
            result = future.result()
            recorder.record(
                _op(ident, key, app="rag", event_type=EventType.RETRIEVAL_RETURNED,
                    component_type=ComponentType.RETRIEVER, component_id="local-document-search",
                    parents=(root,)),
                lambda result=result: result,
            )
            results[ident] = result
    parents = tuple(ident for ident, _, _ in work)
    if scenario == "retry":
        retry_id = "rag.refund.retry"
        retry_result = _search_local(directory / "refund.md", "reembolso",
                                     disable_match=False, noisy=False)
        recorder.record(
            _op(retry_id, "refund-validation-retry", app="rag",
                event_type=EventType.RETRIEVAL_RETURNED,
                component_type=ComponentType.RETRIEVER,
                component_id="local-document-search", parents=("rag.refund",)),
            lambda: retry_result,
        )
        results[retry_id] = retry_result
        parents += (retry_id,)
    answer_supported = any(result.semantic_values["evidence_found"] for result in results.values())
    recorder.record(
        _op("rag.answer", "compose-answer", app="rag", event_type=EventType.OUTCOME_RECORDED,
            component_type=ComponentType.OUTCOME, component_id="answer-composer", parents=parents),
        lambda: ObservableResult({"sources": sorted(results), "answer": "ok" if answer_supported else "missing"},
                                 {"answer_supported": answer_supported}, {}),
    )
    return recorder.finish()


def _tool_local(path: Path, task: str, *, noisy: bool, functional: bool) -> ObservableResult:
    """Ejecuta herramientas Python reales sobre un catálogo JSON local."""
    bytes_in = path.read_bytes()
    catalog = json.loads(bytes_in)
    canonical_v2(catalog)
    item = catalog["item"]
    if task == "inventory":
        output: Any = bool(item["stock"] >= item["quantity"])
        ok = output
    elif task == "tax":
        price = Decimal(str(item["price_units"]))
        tax = price * Decimal("0.18")
        output = format(tax, "f")
        ok = tax >= 0
    elif task == "discount":
        output = bool(item["discount_eligible"])
        ok = True
    elif task == "receipt":
        output = "receipt-ready" if item["quantity"] > 0 else "receipt-empty"
        ok = item["quantity"] > 0
    else:
        raise V2Error("Herramienta local desconocida.")
    if functional and task == "inventory":
        # Intervención local controlada sobre el resultado, no etiqueta privilegiada.
        output = False
        ok = False
    payload = {"tool_output": output, "catalog_sha256": sha256_hex(bytes_in)}
    attributes = {"latency_ms": 5, "token_count": 0}
    if noisy:
        payload["diagnostic_text"] = "trace-variation"
        attributes["latency_ms"] = 117
    return ObservableResult(payload, {"task_ok": ok}, attributes)


def run_tools_local(
    *, study: PilotStudyManifest, run_id: str,
    scenario: Literal["baseline", "insert", "reorder", "noise", "functional", "rekey", "retry"] = "baseline",
    catalog_path: Path | None = None, case_id: str = CASE_TOOLS,
) -> ExecutedRun:
    """Ejecuta herramientas repetidas y un join, con claves semánticas estables."""
    recorder = ExecutionRecorder(
        study=study, app_id=AppId.A3, case_id=case_id, run_id=run_id,
        condition_id=scenario, system_version_id="tools-local-v1",
    )
    root = "tools.request"
    recorder.record(
        _op(root, "order-request", app="tools", event_type=EventType.PROMPT_ISSUED,
            component_type=ComponentType.PROMPT, component_id="order-input"),
        lambda: ObservableResult({"request": "process-order"}, {}, {}),
    )
    path = catalog_path or DEFAULT_INPUTS / "catalog.json"
    work = [
        ("tools.inventory", "check-inventory", "inventory"),
        ("tools.tax", "calculate-tax", "tax"),
        ("tools.receipt", "build-receipt", "receipt"),
    ]
    if scenario == "insert":
        work.insert(0, ("tools.discount", "verify-discount", "discount"))
    if scenario == "reorder":
        work.reverse()
    if scenario == "rekey":
        work = [(ident, "calculate-tax" if ident == "tools.inventory" else
                 "check-inventory" if ident == "tools.tax" else key, task)
                for ident, key, task in work]
    results: dict[str, ObservableResult] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_tool_local, path, task, noisy=scenario == "noise",
                        functional=scenario == "functional"): (ident, key)
            for ident, key, task in work
        }
        for future in as_completed(futures):
            ident, key = futures[future]
            result = future.result()
            recorder.record(
                _op(ident, key, app="tools", event_type=EventType.TOOL_RETURNED,
                    component_type=ComponentType.TOOL, component_id="order-toolkit",
                    parents=(root,)),
                lambda result=result: result,
            )
            results[ident] = result
    parents = tuple(ident for ident, _, _ in work)
    if scenario == "retry":
        retry_id = "tools.inventory.retry"
        retry_result = _tool_local(path, "inventory", noisy=False, functional=False)
        recorder.record(
            _op(retry_id, "inventory-validation-retry", app="tools",
                event_type=EventType.TOOL_RETURNED, component_type=ComponentType.TOOL,
                component_id="order-toolkit", parents=("tools.inventory",)),
            lambda: retry_result,
        )
        results[retry_id] = retry_result
        parents += (retry_id,)
    passed = all(result.semantic_values["task_ok"] for result in results.values())
    recorder.record(
        _op("tools.finish", "commit-order", app="tools", event_type=EventType.OUTCOME_RECORDED,
            component_type=ComponentType.OUTCOME, component_id="order-coordinator",
            parents=parents),
        lambda: ObservableResult({"processed": passed}, {"workflow_ok": passed}, {}),
    )
    return recorder.finish()


def assert_external_witness(baseline: ExecutedRun, candidate: ExecutedRun) -> None:
    """Rechaza claves recodificadas por posición usando IDs del plan externo."""
    def index(run: ExecutedRun) -> tuple[dict[str, tuple[str, ...]], dict[tuple[str, ...], str]]:
        events = {event.event_id: event for event in run.events}
        if len(events) != len(run.events) or len(run.witness) != len(events):
            raise V2Error("Testigo incompleto o eventos repetidos.")
        forward: dict[str, tuple[str, ...]] = {}
        inverse: dict[tuple[str, ...], str] = {}
        for witness in run.witness:
            if witness.event_id not in events:
                raise V2Error("Testigo desvinculado de eventos observables.")
            key = events[witness.event_id].key
            if witness.logical_id in forward or key in inverse:
                raise V2Error("Identidad de invocación repetida o testigo duplicado.")
            forward[witness.logical_id] = key
            inverse[key] = witness.logical_id
        return forward, inverse
    left, li = index(baseline)
    right, ri = index(candidate)
    if any(left[x] != right[x] for x in left.keys() & right.keys()):
        raise V2Error("Una operación lógica cambió invocation_key entre ejecuciones.")
    if any(li[k] != ri[k] for k in li.keys() & ri.keys()):
        raise V2Error("Una clave alineó operaciones lógicas diferentes.")

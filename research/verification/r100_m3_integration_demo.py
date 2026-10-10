"""Demostración pública M3: integra M1/M2 sin exponer parámetros ni identidades."""
from __future__ import annotations

import json

from provregress.mutation_v2.integration_m3 import (
    DeclaredSignalM3, build_integration_plan_m3, execute_local_integration_m3,
    public_integrated_summary_m3,
)
from provregress.mutation_v2.observability import ObservationContractM2, SignalBindingM2
from provregress.mutation_v2.planning import MutationRequestV2, plan_mutations_v2
from provregress.mutation_v2.system_treatments import make_request, read_system_snapshot
from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.live_workloads import demo_study, comparison_policy, DEFAULT_INPUTS
from provregress.provenance_v2.projector import project_trace_v2
from provregress.schema.common import AppId
from provregress.schema.events import EventType


def run_demo(app: AppId) -> dict[str, object]:
    """Prueba local controlada. El plan M1 es únicamente el ancla observacional."""
    study = demo_study()
    if app is AppId.A2:
        before = run_rag_dynamic(study=study, run_id="m3-a2-base", corpus=DEFAULT_INPUTS)
        anchor = next(x for x in before.events if x.event_type is EventType.RETRIEVAL_RETURNED)
        pointer, params, field, mechanism = "/document", {"value": "propuesta.md"}, "evidence_found", "propagated"
        sys_request = make_request(read_system_snapshot(DEFAULT_INPUTS),
                                   "prompt.query.replace.v1", "query", "devolucion")
    else:
        before = run_tools_dynamic(study=study, run_id="m3-a3-base",
                                   catalog_path=DEFAULT_INPUTS / "catalog.json")
        anchor = next(x for x in before.events if x.invocation_key == "tool:inventory")
        pointer, params, field, mechanism = "/result", {"value": False}, "task_ok", "direct"
        sys_request = make_request(read_system_snapshot(DEFAULT_INPUTS),
                                   "tool.catalog.field.set.v1", "item.stock", 0)
    graph = project_trace_v2(list(before.events))
    policy = comparison_policy(app)
    m1 = plan_mutations_v2(graph, policy, [MutationRequestV2(
        request_id="pilot-anchor", target_key=list(anchor.key),
        operator_id="json.scalar.replace.v1", json_pointer=pointer, parameters=params,
    )])
    contract = ObservationContractM2(
        app_id=app, comparison_policy_hash=policy.policy_hash,
        bindings=[SignalBindingM2(
            event_type=anchor.event_type, json_pointer=pointer, signal_field=field,
            mechanism=mechanism, operator_ids=["json.scalar.replace.v1"],
        )],
    )
    plan = build_integration_plan_m3(
        m1_plan=m1, graph=graph, policy=policy, events=list(before.events),
        observation=contract, snapshot=read_system_snapshot(DEFAULT_INPUTS),
        system_request=sys_request,
        expected_signals=[DeclaredSignalM3(event_type=anchor.event_type, field=field)],
    )
    receipt = execute_local_integration_m3(
        plan=plan, m1_plan=m1, graph=graph, policy=policy,
        events=list(before.events), observation=contract, source_dir=DEFAULT_INPUTS,
    )
    return {"app_id": app.value, **public_integrated_summary_m3(receipt)}


def main() -> None:
    print(json.dumps({"schema_version": "r1.0-m3-demo-v1", "results": [
        run_demo(AppId.A2), run_demo(AppId.A3),
    ]}, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()

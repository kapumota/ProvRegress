"""M3: vinculación, sandbox, separación y controles adversariales."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.mutation_v2.integration_m3 import (
    DeclaredSignalM3, IntegratedReceiptM3, IntegrationErrorM3,
    IntegrationPlanM3, build_integration_plan_m3, execute_local_integration_m3,
    public_integrated_summary_m3,
)
from provregress.mutation_v2.observability import (
    ObservationContractM2, SignalBindingM2,
)
from provregress.mutation_v2.planning import MutationRequestV2, plan_mutations_v2
from provregress.mutation_v2.system_treatments import make_request, read_system_snapshot
from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.live_workloads import demo_study, comparison_policy, DEFAULT_INPUTS
from provregress.provenance_v2.projector import project_trace_v2
from provregress.schema.common import AppId
from provregress.schema.events import EventType


@pytest.fixture(params=["a2", "a3"])
def kit(request, tmp_path):
    # Aislar toda entrada sin modificar las fuentes del repositorio.
    import shutil
    src = tmp_path / "data"
    src.mkdir()
    for source in DEFAULT_INPUTS.iterdir():
        if source.is_file():
            shutil.copy2(source, src / source.name)
    app = AppId.A2 if request.param == "a2" else AppId.A3
    study = demo_study()
    if app == AppId.A2:
        baseline = run_rag_dynamic(study=study, run_id="m3-base", corpus=src)
        selected = next(ev for ev in baseline.events if ev.event_type == EventType.RETRIEVAL_RETURNED)
        pointer, hypothetical = "/document", {"value": "otro.md"}
        signal = "evidence_found"
        sys_request = make_request(read_system_snapshot(src), "prompt.query.replace.v1", "query", "devolucion")
        mechanism = "propagated"
        expected = [DeclaredSignalM3(event_type=EventType.RETRIEVAL_RETURNED, field=signal)]
    else:
        baseline = run_tools_dynamic(study=study, run_id="m3-base", catalog_path=src/"catalog.json")
        selected = next(ev for ev in baseline.events if ev.invocation_key == "tool:inventory")
        pointer, hypothetical = "/result", {"value": not selected.payload["result"]}
        signal = "task_ok"
        sys_request = make_request(read_system_snapshot(src), "tool.catalog.field.set.v1", "item.stock", 0)
        mechanism = "direct"
        expected = [DeclaredSignalM3(event_type=EventType.TOOL_RETURNED, field=signal)]
    graph = project_trace_v2(list(baseline.events))
    policy = comparison_policy(app)
    m1_plan = plan_mutations_v2(graph, policy, [MutationRequestV2(
        request_id="anchor", target_key=list(selected.key),
        operator_id="json.scalar.replace.v1", json_pointer=pointer, parameters=hypothetical,
    )])
    observation = ObservationContractM2(
        app_id=app, comparison_policy_hash=policy.policy_hash,
        bindings=[SignalBindingM2(event_type=selected.event_type,
                                  json_pointer=pointer, signal_field=signal,
                                  mechanism=mechanism, operator_ids=["json.scalar.replace.v1"])],
    )
    return {
        "source_dir": src, "app": app, "m1_plan": m1_plan,
        "graph": graph, "policy": policy, "events": list(baseline.events),
        "observation": observation, "snapshot": read_system_snapshot(src),
        "system_request": sys_request, "expected_signals": expected,
    }


def prepare(kit):
    keys = ("m1_plan", "graph", "policy", "events", "observation",
            "snapshot", "system_request", "expected_signals")
    return build_integration_plan_m3(**{key: kit[key] for key in keys})


def execute(kit, plan):
    args = {k: kit[k] for k in ("m1_plan", "graph", "policy", "events", "observation", "source_dir")}
    return execute_local_integration_m3(plan=plan, **args)


def test_plan_is_deterministic_and_pins_all_origins(kit):
    plan = prepare(kit)
    assert prepare(kit).plan_hash == plan.plan_hash
    assert plan.m1_plan_hash == kit["m1_plan"].plan_hash
    assert plan.graph_hash == kit["graph"].graph_hash
    assert plan.policy_hash == kit["policy"].policy_hash
    assert plan.observation_contract_hash == kit["observation"].contract_hash
    assert plan.source_snapshot_hash == kit["snapshot"].snapshot_hash
    assert plan.mode == "pilot_local_only"
    assert plan.confirmatory_execution is False
    assert plan.preflight_classification in ("observable_direct", "observable_propagated")


def test_pilot_runs_and_receipt_is_verifiable(kit):
    plan = prepare(kit)
    original = (kit["source_dir"]/"catalog.json").read_bytes()
    receipt = execute(kit, plan)
    assert receipt.plan_hash == plan.plan_hash
    assert receipt.candidate_snapshot_hash == plan.candidate_snapshot_hash
    assert receipt.baseline_graph_hash == kit["graph"].graph_hash
    assert receipt.candidate_graph_hash != receipt.baseline_graph_hash
    assert receipt.scientific_evidence == "not_admissible"
    assert receipt.confirmatory_execution is False
    assert (kit["source_dir"]/"catalog.json").read_bytes() == original
    assert public_integrated_summary_m3(receipt)["confirmatory_execution"] is False


def test_private_fields_not_exposed(kit):
    plan = prepare(kit)
    summary = public_integrated_summary_m3(execute(kit, plan))
    flattened = json.dumps(summary)
    for forbidden in ("operator_id", "mutation_id", "target_key", "request_id",
                      "parameters", "item.stock", "source_snapshot_hash", "plan_hash"):
        assert forbidden not in flattened


def test_plan_detects_tampering(kit):
    plan = prepare(kit)
    with pytest.raises(ValidationError):
        IntegrationPlanM3.model_validate({**plan.model_dump(), "candidate_snapshot_hash": "f" * 64})


def test_receipt_detects_tampering(kit):
    receipt = execute(kit, prepare(kit))
    with pytest.raises(ValidationError):
        IntegratedReceiptM3.model_validate({**receipt.model_dump(), "observed_functional": 999})


def test_system_precondition_rejected(kit):
    from provregress.mutation_v2.system_treatments import SystemRequestM2
    data = kit["system_request"].model_dump()
    data["expected_before_hash"] = "f" * 64
    kit["system_request"] = SystemRequestM2.model_validate(data)
    with pytest.raises(ValueError):
        prepare(kit)


def test_source_change_between_plan_and_execution_rejected(kit):
    plan = prepare(kit)
    (kit["source_dir"] / "catalog.json").write_text('{"item":{}}', encoding="utf8")
    with pytest.raises(ValueError):
        execute(kit, plan)


def test_altered_graph_rejected(kit):
    from provregress.provenance_v2.schema import GraphV2
    altered = kit["graph"].model_dump()
    altered["graph_hash"] = "0"*64
    with pytest.raises(ValidationError):
        GraphV2.model_validate(altered)


def test_wrong_m1_anchor_rejected(kit):
    graph, policy = kit["graph"], kit["policy"]
    if kit["app"] == AppId.A2:
        root = next(n for n in graph.events if n.invocation_key == "compose:answer")
        pointer,params = "/sources", {"value": "test"}
    else:
        root = next(n for n in graph.events if n.invocation_key == "finish:order")
        pointer,params = "/executed", {"value": 1}
    kit["m1_plan"] = plan_mutations_v2(graph, policy, [MutationRequestV2(
        request_id="anchor", target_key=list(root.key), operator_id="json.scalar.replace.v1",
        json_pointer=pointer, parameters=params,
    )])
    with pytest.raises(ValueError):
        prepare(kit)


def test_expected_signal_must_be_in_policy(kit):
    kit["expected_signals"] = [DeclaredSignalM3(event_type=EventType.OUTCOME_RECORDED,
                                                  field="falso")]
    with pytest.raises(IntegrationErrorM3, match="fuera de la política"):
        prepare(kit)


def test_mismatched_observation_contract_rejected(kit):
    kit["observation"] = kit["observation"].model_copy(update={"comparison_policy_hash":"f"*64})
    with pytest.raises(ValueError):
        prepare(kit)


def test_wrong_app_operator_rejected(kit):
    from provregress.mutation_v2.system_treatments import SystemRequestM2
    if kit["app"] == AppId.A2:
        request = SystemRequestM2(operator_id="tool.catalog.field.set.v1",target="item.stock",expected_before_hash="f"*64,value=0)
    else:
        request = SystemRequestM2(operator_id="prompt.query.replace.v1",target="query",expected_before_hash="f"*64,value="otro")
    kit["system_request"] = request
    with pytest.raises(ValueError):
        prepare(kit)


def test_incorrect_source_evidence_rejected(kit):
    from provregress.provenance_v2.schema import EventV2
    events = list(kit["events"])
    ix = next(i for i,e in enumerate(events) if e.invocation_key in ("query:refund", "request:order"))
    broken = {**events[ix].model_dump(mode="python"), "payload": {"foo":"bar"}}
    events[ix] = EventV2.model_validate(broken)
    kit["events"] = events
    with pytest.raises(ValueError):
        prepare(kit)


def test_duplicate_expected_signal_rejected(kit):
    kit["expected_signals"] *= 2
    with pytest.raises(IntegrationErrorM3, match="duplicadas"):
        prepare(kit)


def test_price_only_is_not_reported_as_functional(kit):
    if kit["app"] != AppId.A3:
        pytest.skip("Solo A3 tiene señal task_ok sin sensibilidad al precio.")
    kit["system_request"] = make_request(kit["snapshot"], "tool.catalog.field.set.v1",
                                         "item.price_units", 900)
    receipt = execute(kit, prepare(kit))
    assert receipt.observed_functional == 0
    assert receipt.payload_only > 0
    assert receipt.observed_impact == "payload_only"


def test_broader_retrieval_is_structural_not_inferred_causal(kit):
    if kit["app"] != AppId.A2:
        pytest.skip("La variación top_k corresponde a A2.")
    kit["system_request"] = make_request(kit["snapshot"], "retrieval.top_k.set.v1", "top_k", 4)
    receipt = execute(kit, prepare(kit))
    assert receipt.observed_impact in {"structural_only", "functional_observed"}
    assert receipt.potential_descendants >= receipt.observed_descendants


def test_symlink_source_rejected_before_execution(kit, tmp_path):
    symlink = tmp_path / "linked-source"
    symlink.symlink_to(kit["source_dir"], target_is_directory=True)
    kit["source_dir"] = symlink
    with pytest.raises(IntegrationErrorM3, match="fuente local"):
        execute(kit, prepare(kit))

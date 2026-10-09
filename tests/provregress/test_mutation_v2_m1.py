"""M1: selección v2 y planificación pura. No se ejecuta ningún tratamiento."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.mutation_v2 import (
    M1Error, MutationPlanV2, MutationRequestV2, plan_mutations_v2,
    public_plan_summary_v2, verify_plan_v2,
)
from provregress.mutation_v2.catalog import check_pointer
from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.live_workloads import comparison_policy, demo_study
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import EventV2, V2Error, canonical_v2
from provregress.schema.common import AppId
from provregress.storage.hashing import sha256_hex


@pytest.fixture(params=[AppId.A2, AppId.A3])
def scenario(request):
    app = request.param
    execute = run_rag_dynamic if app == AppId.A2 else run_tools_dynamic
    run = execute(study=demo_study(), run_id=f"m1-{app.value}")
    graph = project_trace_v2(run.events)
    policy = comparison_policy(app)
    assessed = {x.event_type for x in policy.rules}
    eligible = [node for node in graph.events if node.event_type in assessed]
    return app, graph, policy, eligible, run


def req(node, rid="candidate-a", *, op="json.scalar.replace.v1", ptr="/result", params=None):
    return MutationRequestV2(
        request_id=rid, target_key=list(node.key), operator_id=op,
        json_pointer=ptr,
        parameters={"value": "cambio"} if params is None and op == "json.scalar.replace.v1" else (params or {}),
    )


def test_plan_compiles_for_a2_and_a3_without_execution(scenario):
    _, graph, policy, eligible, _ = scenario
    plan = plan_mutations_v2(graph, policy, [req(eligible[0])])
    verify_plan_v2(plan, graph, policy)
    assert plan.mode == "design_only" and plan.confirmatory_execution is False
    assert plan.app_id == graph.app_id
    assert plan.intents[0].source_payload_hash == eligible[0].payload_hash
    assert plan.source_graph_hash == graph.graph_hash
    assert plan.comparison_policy_hash == policy.policy_hash
    assert not hasattr(plan, "apply")


def test_deterministic_plan_irrespective_request_order(scenario):
    _, graph, policy, eligible, _ = scenario
    a, b = req(eligible[0], "candidate-a"), req(eligible[-1], "candidate-b",
                   op="json.field.remove.v1", ptr="/optional", params={})
    assert eligible[0].key != eligible[-1].key
    first = plan_mutations_v2(graph, policy, [a, b])
    second = plan_mutations_v2(graph, policy, [b, a])
    assert canonical_v2(first.model_dump(mode="json", exclude={"intents"})) == canonical_v2(second.model_dump(mode="json", exclude={"intents"}))
    assert first == second and first.plan_hash == second.plan_hash
    verify_plan_v2(first, graph, policy)


def test_rejects_missing_target(scenario):
    _, graph, policy, eligible, _ = scenario
    x = req(eligible[0]).model_copy(update={"target_key": [*eligible[0].key[:-2], "absent", eligible[0].key[-1]]})
    with pytest.raises(M1Error, match="no existe"):
        plan_mutations_v2(graph, policy, [x])


def test_rejects_event_id_as_selector(scenario):
    _, graph, policy, eligible, _ = scenario
    with pytest.raises(ValidationError):
        MutationRequestV2.model_validate({**req(eligible[0]).model_dump(),
                                         "target_key": [eligible[0].event_id]})


def test_rejects_duplicate_request_ids(scenario):
    _, graph, policy, eligible, _ = scenario
    with pytest.raises(M1Error, match="duplicado"):
        plan_mutations_v2(graph, policy, [req(eligible[0]), req(eligible[-1])])


def test_rejects_duplicate_target_even_when_operators_differ(scenario):
    _, graph, policy, eligible, _ = scenario
    with pytest.raises(M1Error, match="más de un tratamiento"):
        plan_mutations_v2(graph, policy, [req(eligible[0], "first"),
                                               req(eligible[0], "second", op="json.field.remove.v1", params={})])


def test_rejects_mismatched_policy(scenario):
    app, graph, _, eligible, _ = scenario
    other = comparison_policy(AppId.A3 if app == AppId.A2 else AppId.A2)
    with pytest.raises(M1Error, match="aplicaciones diferentes"):
        plan_mutations_v2(graph, other, [req(eligible[0])])


def test_rejects_event_without_functional_rule(scenario):
    _, graph, policy, _, _ = scenario
    assessed = {rule.event_type for rule in policy.rules}
    unassessed = next(node for node in graph.events if node.event_type not in assessed)
    with pytest.raises(M1Error, match="sin señal funcional"):
        plan_mutations_v2(graph, policy, [req(unassessed)])


def test_rejects_unknown_operator(scenario):
    _, _, _, eligible, _ = scenario
    with pytest.raises(ValidationError, match="Operador inexistente"):
        req(eligible[0], op="shell.exec.v1", params={})


@pytest.mark.parametrize("pointer", ["", "field", "/", "/0", "/array/12", "/-", "/mutation_id", "/operator_id", "/severity", "/target_component_id", "/~", "/~2", "/foo/", "/a//b", "/" + "x" * 300])
def test_unsafe_json_pointers_are_rejected(pointer):
    with pytest.raises(V2Error):
        check_pointer(pointer)


@pytest.mark.parametrize("pointer", ["/result", "/value~1key", "/tilde~0name", "/nested/field"])
def test_object_pointers_are_allowed(pointer):
    check_pointer(pointer)


@pytest.mark.parametrize("value", [1.2, float("nan"), 2**60, {"mutation_id": "secret"}, ["hi"], {"x": 1}])
def test_invalid_replacement_values_rejected(scenario, value):
    _, _, _, eligible, _ = scenario
    with pytest.raises((V2Error, ValidationError, ValueError)):
        req(eligible[0], params={"value": value})


def test_remove_does_not_accept_parameter(scenario):
    _, _, _, eligible, _ = scenario
    with pytest.raises(ValidationError, match="no admite"):
        req(eligible[0], op="json.field.remove.v1", params={"value": "no"})


def test_rejects_no_request_and_nonlist(scenario):
    _, graph, policy, _, _ = scenario
    with pytest.raises(M1Error):
        plan_mutations_v2(graph, policy, [])
    with pytest.raises(M1Error):
        plan_mutations_v2(graph, policy, ())


def test_rejects_modified_plan_hash(scenario):
    _, graph, policy, eligible, _ = scenario
    plan = plan_mutations_v2(graph, policy, [req(eligible[0])])
    from provregress.mutation_v2.planning import _private_canonical
    with pytest.raises(ValidationError, match="hash"):
        MutationPlanV2.model_validate_json(_private_canonical({**plan.model_dump(mode="json"), "plan_hash": "0" * 64}))


def test_rejects_forged_source_hash_even_when_rehashed(scenario):
    _, graph, policy, eligible, _ = scenario
    plan = plan_mutations_v2(graph, policy, [req(eligible[0])])
    altered = plan.model_dump(mode="json", exclude={"plan_hash"})
    altered["intents"][0]["source_payload_hash"] = "a" * 64
    from provregress.mutation_v2.planning import _private_canonical
    altered["plan_hash"] = sha256_hex(_private_canonical(altered))
    forged = MutationPlanV2.model_validate_json(_private_canonical(altered))
    with pytest.raises(M1Error, match="no corresponde"):
        verify_plan_v2(forged, graph, policy)


def test_public_summary_has_no_target_identity_or_parameters(scenario):
    _, graph, policy, eligible, _ = scenario
    plan = plan_mutations_v2(graph, policy, [req(eligible[0], params={"value": "sensitive-value"})])
    summary = public_plan_summary_v2(plan)
    rendered = str(summary)
    assert summary["planned_intents"] == 1
    assert "sensitive-value" not in rendered
    assert eligible[0].invocation_key not in rendered
    assert "json_pointer" not in rendered and "target_key" not in rendered


def test_rejects_ambiguous_key_even_when_node_ids_unique(scenario):
    _, _, policy, eligible, run = scenario
    target_event = next(ev for ev in run.events if ev.key == eligible[0].key)
    clone = EventV2.model_validate({**target_event.model_dump(mode="python"),
                                    "event_id": "evt-duplicate", "sequence": len(run.events)})
    ambiguous = project_trace_v2((*run.events, clone))
    with pytest.raises(M1Error, match="ambiguo"):
        plan_mutations_v2(ambiguous, policy, [req(eligible[0])])


def test_modifying_original_request_after_planning_does_not_change_plan(scenario):
    _, graph, policy, eligible, _ = scenario
    request = req(eligible[0])
    plan = plan_mutations_v2(graph, policy, [request])
    request.parameters["value"] = "otra cosa"
    verify_plan_v2(plan, graph, policy)


def test_no_files_written_by_planner(tmp_path, scenario, monkeypatch):
    _, graph, policy, eligible, _ = scenario
    monkeypatch.chdir(tmp_path)
    before = set(Path(".").iterdir())
    plan_mutations_v2(graph, policy, [req(eligible[0])])
    assert set(Path(".").iterdir()) == before


def test_confirmatory_mode_cannot_be_enabled_even_when_rehashed(scenario):
    _, graph, policy, eligible, _ = scenario
    from provregress.mutation_v2.planning import _private_canonical
    plan = plan_mutations_v2(graph, policy, [req(eligible[0])])
    tampered = plan.model_dump(mode="json", exclude={"plan_hash"})
    tampered["confirmatory_execution"] = True
    tampered["plan_hash"] = sha256_hex(_private_canonical(tampered))
    with pytest.raises(ValidationError):
        MutationPlanV2.model_validate_json(_private_canonical(tampered))


def test_plan_bound_to_source_graph_even_when_app_is_same(scenario):
    app, graph, policy, eligible, _ = scenario
    plan = plan_mutations_v2(graph, policy, [req(eligible[0])])
    execute = run_rag_dynamic if app == AppId.A2 else run_tools_dynamic
    other = project_trace_v2(execute(study=demo_study(), run_id=f"m1-different-{app.value}").events)
    with pytest.raises(M1Error, match="no corresponde"):
        verify_plan_v2(plan, other, policy)

"""M2-P1: oráculos negativos y positivos de observabilidad y señal ausente."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from provregress.mutation_v2.observability import (
    M2Error, ObservationContractM2, SignalBindingM2,
    assert_observable_plan_m2, audit_observability_m2,
)
from provregress.mutation_v2.planning import MutationRequestV2, plan_mutations_v2
from provregress.provenance_v2.comparison import compare_graphs_v2
from provregress.provenance_v2.comparison_v21 import compare_graphs_v21
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import (
    AppId, ComparisonPolicyV2, EventV2, SignalRule, V2Error,
)
from provregress.schema.common import ComponentType
from provregress.schema.events import EventType


def _event(run: str, *, payload=None, signals=None) -> EventV2:
    return EventV2(
        run_id=run, event_id="evt-0", sequence=0,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        app_id=AppId.A3, case_id="m2-test", repeat_index=0,
        system_version_id=run, condition_id=run,
        component_type=ComponentType.TOOL, component_id="toolkit",
        event_type=EventType.TOOL_RETURNED, scope_path=["tool", "order"],
        invocation_key="inventory-check", parent_event_ids=[],
        payload={"result": True, "noise": "x"} if payload is None else payload,
        semantic_values={"result": True} if signals is None else signals,
        attributes={},
    )


def _policy(kind="boolean"):
    return ComparisonPolicyV2(app_id=AppId.A3, rules=[
        SignalRule(event_type=EventType.TOOL_RETURNED, field="result", kind=kind,
                   weight="1", **({"scale": "1"} if kind == "decimal" else {})),
    ])


def _context(pointer="/result", replacement=False, operator="json.scalar.replace.v1"):
    source = _event("before")
    graph = project_trace_v2([source])
    policy = _policy()
    plan = plan_mutations_v2(graph, policy, [MutationRequestV2(
        request_id="case-a", target_key=list(graph.events[0].key),
        operator_id=operator, json_pointer=pointer,
        parameters={"value": replacement} if operator.endswith("replace.v1") else {},
    )])
    return source, graph, policy, plan


def _contract(policy, pointer="/result", signal="result", mechanism="direct", operator=None):
    return ObservationContractM2(app_id=AppId.A3, comparison_policy_hash=policy.policy_hash,
                                 bindings=[SignalBindingM2(
                                     event_type=EventType.TOOL_RETURNED,
                                     json_pointer=pointer, signal_field=signal,
                                     mechanism=mechanism,
                                     operator_ids=[operator or "json.scalar.replace.v1"],
                                 )])


def test_directly_bound_payload_is_eligible_without_execution():
    event, graph, policy, plan = _context()
    report = audit_observability_m2(plan, graph, policy, [event], _contract(policy))
    assert report.eligible_count == 1 and report.silent_count == 0
    assert report.items[0].classification == "observable_direct"
    assert report.confirmatory_execution is False
    assert_observable_plan_m2(report)


def test_unmapped_payload_change_is_silent_risk_not_detection():
    event, graph, policy, plan = _context(pointer="/noise", replacement="y")
    report = audit_observability_m2(plan, graph, policy, [event], _contract(policy))
    assert report.silent_count == 1
    assert report.items[0].reason == "no_binding"
    with pytest.raises(M2Error, match="silenciosa"):
        assert_observable_plan_m2(report)


def test_inconsistent_direct_mapping_is_not_eligible():
    event, graph, policy, plan = _context(pointer="/noise", replacement="y")
    report = audit_observability_m2(plan, graph, policy, [event],
                                    _contract(policy, pointer="/noise"))
    assert report.items[0].reason == "payload_signal_inconsistent"
    assert report.eligible_count == 0


def test_propagated_mapping_is_declared_not_proven():
    event, graph, policy, plan = _context(pointer="/noise", replacement="y")
    report = audit_observability_m2(plan, graph, policy, [event],
                                    _contract(policy, pointer="/noise", mechanism="propagated"))
    assert report.items[0].classification == "observable_propagated"
    assert report.eligible_count == 1


def test_missing_payload_pointer_rejected():
    event, graph, policy, plan = _context(pointer="/missing")
    with pytest.raises(M2Error, match="no existe"):
        audit_observability_m2(plan, graph, policy, [event], _contract(policy, pointer="/missing"))


def test_type_mismatch_rejected():
    event, graph, policy, plan = _context(replacement="texto")
    with pytest.raises(M2Error, match="tipo escalar"):
        audit_observability_m2(plan, graph, policy, [event], _contract(policy))


def test_unbound_policy_signal_rejected():
    event, graph, policy, plan = _context()
    with pytest.raises(M2Error, match="política"):
        audit_observability_m2(plan, graph, policy, [event],
                                _contract(policy, signal="other"))


def test_invalid_input_graph_is_rejected():
    event, graph, policy, plan = _context()
    altered = event.model_copy(update={"payload": {"result": False}})
    with pytest.raises(M2Error, match="grafo"):
        audit_observability_m2(plan, graph, policy, [altered], _contract(policy))


def test_removed_signal_is_explicitly_reported_only_in_v21():
    before = project_trace_v2([_event("baseline")])
    after = project_trace_v2([_event("candidate", payload={"noise": "x"}, signals={})])
    policy = _policy()
    with pytest.raises(V2Error, match="Falta señal"):
        compare_graphs_v2(before, after, policy)
    delta = compare_graphs_v21(before, after, policy)
    assert len(delta.changed_events) == 1
    assert delta.changed_events[0].reasons == ["signal_missing"]
    assert delta.changed_events[0].magnitude == "1"
    assert delta.schema_version == "provenance-delta-v2.1"


def test_signal_restoration_is_distinguished_from_disappearance():
    before = project_trace_v2([_event("baseline", signals={})])
    after = project_trace_v2([_event("candidate")])
    delta = compare_graphs_v21(before, after, _policy())
    assert delta.changed_events[0].reasons == ["signal_restored"]


def test_null_is_not_missing():
    before = project_trace_v2([_event("baseline")])
    after = project_trace_v2([_event("candidate", signals={"result": None})])
    with pytest.raises(V2Error, match="booleana"):
        compare_graphs_v21(before, after, _policy())


def test_missing_both_sides_is_not_imputed():
    before = project_trace_v2([_event("baseline", signals={})])
    after = project_trace_v2([_event("candidate", signals={})])
    with pytest.raises(V2Error, match="ambas ejecuciones"):
        compare_graphs_v21(before, after, _policy())


def test_noise_does_not_become_functional_change():
    before = project_trace_v2([_event("baseline")])
    after = project_trace_v2([_event("candidate", payload={"result": True, "noise": "changed"})])
    d = compare_graphs_v21(before, after, _policy())
    assert not d.changed_events
    assert len(d.ignored_payload_changes) == 1


def test_decimal_magnitude_is_preserved():
    before = project_trace_v2([_event("baseline", signals={"result": "0.4"})])
    after = project_trace_v2([_event("candidate", signals={"result": "0.5"})])
    d = compare_graphs_v21(before, after, _policy("decimal"))
    assert len(d.changed_events) == 1
    assert d.changed_events[0].reasons == ["value_changed"]
    assert d.changed_events[0].magnitude == "0.1"


def test_duplicate_binding_is_rejected():
    policy = _policy()
    item = SignalBindingM2(event_type=EventType.TOOL_RETURNED,
                           json_pointer="/result", signal_field="result",
                           operator_ids=["json.scalar.replace.v1"])
    with pytest.raises(ValidationError, match="Binding ambiguo"):
        ObservationContractM2(app_id=AppId.A3, comparison_policy_hash=policy.policy_hash,
                              bindings=[item, item])

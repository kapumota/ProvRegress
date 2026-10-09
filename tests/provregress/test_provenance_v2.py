"""R0.10, pruebas adversariales y comparabilidad de procedencia v2."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from provregress.provenance_v2 import (
    ComparisonPolicyV2, EventV2, GraphV2, SignalRule, V2Error,
    assert_pilot_alignment_v2, canonical_v2, compare_graphs_v2,
    decimal_v2, project_trace_v2, sequential_baseline_view_v2,
    topology_profile_v2, validate_graph_v2,
)
from provregress.schema.common import AppId, ComponentType
from provregress.schema.events import EventType
from provregress.storage.hashing import sha256_hex

T0 = datetime(2026, 10, 8, 18, tzinfo=timezone.utc)


def policy(app_id: AppId = AppId.A3) -> ComparisonPolicyV2:
    return ComparisonPolicyV2(
        app_id=app_id,
        rules=[
            SignalRule(event_type=EventType.TOOL_CALLED, field="args_valid", kind="boolean", weight="1"),
            SignalRule(event_type=EventType.TOOL_RETURNED, field="quality", kind="decimal", scale="0.5", weight="1"),
            SignalRule(event_type=EventType.RETRIEVAL_RETURNED, field="relevant_evidence", kind="decimal", scale="5", weight="1"),
            SignalRule(event_type=EventType.OUTCOME_RECORDED, field="result", kind="categorical", weight="1"),
        ],
    )


def event(run_id: str, event_id: str, sequence: int, *, invocation: str,
          kind: EventType = EventType.TOOL_RETURNED, component: str = "search",
          parents: list[str] | None = None, payload: object = None,
          attributes: dict | None = None, signals: dict | None = None,
          scope: list[str] | None = None, app_id: AppId = AppId.A3, **kwargs) -> EventV2:
    if signals is None:
        signals = ({"quality": "0.8"} if kind == EventType.TOOL_RETURNED else
                   {"args_valid": True} if kind == EventType.TOOL_CALLED else
                   {"relevant_evidence": "4"} if kind == EventType.RETRIEVAL_RETURNED else
                   {"result": "ok"})
    return EventV2(
        run_id=run_id, event_id=event_id, sequence=sequence,
        timestamp_utc=T0 + timedelta(seconds=sequence), app_id=app_id,
        case_id="pilot-case", repeat_index=0, system_version_id=run_id,
        condition_id=run_id, component_type=ComponentType.MODEL,
        component_id=component, event_type=kind, scope_path=scope or ["workflow", "search"],
        invocation_key=invocation, parent_event_ids=parents or [],
        payload={"output": "ok"} if payload is None else payload,
        attributes=attributes or {}, semantic_values=signals, **kwargs,
    )


def repeated(run_id: str, count: int) -> list[EventV2]:
    records: list[EventV2] = []
    for iteration in range(count):
        call_id = f"call-{iteration}"
        return_id = f"return-{iteration}"
        key = f"lookup-{iteration}"
        records.append(event(run_id, call_id, len(records), invocation=key,
                             kind=EventType.TOOL_CALLED,
                             parents=[f"return-{iteration - 1}"] if iteration else []))
        records.append(event(run_id, return_id, len(records), invocation=key,
                             kind=EventType.TOOL_RETURNED, parents=[call_id]))
    return records


def graphs(count_a: int = 3, count_b: int = 4):
    return project_trace_v2(repeated("baseline", count_a)), project_trace_v2(repeated("candidate", count_b))


def test_three_vs_four_repetitions_are_not_ambiguous():
    baseline, candidate = graphs()
    delta = compare_graphs_v2(baseline, candidate, policy())
    assert len(delta.added_events) == 2  # llamada y retorno de la invocación extra
    assert len(delta.removed_events) == 0
    assert len(delta.changed_events) == 0
    assert len(delta.unchanged_events) == 6
    assert len(delta.ambiguous_events) == 0
    assert len(delta.edges_added) == 2
    assert delta.ambiguous_event_rate == "0"
    assert_pilot_alignment_v2(baseline, candidate, delta, policy=policy(), target_keys=[
        tuple(delta.added_events[0]), tuple(delta.added_events[1])])


def test_inserted_invocation_does_not_relabel_later_calls():
    baseline = repeated("baseline", 3)
    candidate = repeated("candidate", 4)
    # Cambia el orden de las invocaciones, pero conserva sus claves declaradas.
    reordered = [candidate[6], candidate[7], *candidate[:6]]
    rebuilt: list[EventV2] = []
    for index, original in enumerate(reordered):
        values = original.model_dump(mode="python")
        values["sequence"] = index
        values["parent_event_ids"] = [] if index % 2 == 0 else [rebuilt[-1].event_id]
        rebuilt.append(EventV2.model_validate(values))
    delta = compare_graphs_v2(project_trace_v2(baseline), project_trace_v2(rebuilt), policy())
    assert len(delta.unchanged_events) == 6
    assert len(delta.added_events) == 2
    assert len(delta.ambiguous_events) == 0


def test_noise_in_payload_and_latency_does_not_trigger_functional_change():
    first = event("b", "e0", 0, invocation="lookup-tax", payload={"answer": "x"},
                  attributes={"latency_ms": 10, "tokens": 50})
    second = event("c", "e0", 0, invocation="lookup-tax", payload={"answer": "x!"},
                   attributes={"latency_ms": 800, "tokens": 900})
    result = compare_graphs_v2(project_trace_v2([first]), project_trace_v2([second]), policy())
    assert not result.changed_events
    assert len(result.unchanged_events) == 1
    assert len(result.ignored_payload_changes) == 1
    assert result.edges_added == result.edges_removed == []


def test_one_functional_change_is_one_event_not_five_records():
    a = event("b", "e0", 0, invocation="tax", signals={"quality": "0.8"}, payload={"answer": "x"})
    b = event("c", "e0", 0, invocation="tax", signals={"quality": "0.6"}, payload={"answer": "y"})
    delta = compare_graphs_v2(project_trace_v2([a]), project_trace_v2([b]), policy())
    assert len(delta.changed_events) == 1
    assert delta.changed_events[0].changed_signals == ["quality"]
    assert Decimal(delta.changed_events[0].magnitude) == Decimal("0.4")
    assert delta.changed_events[0].raw_payload_changed
    assert not delta.added_events and not delta.removed_events
    assert not delta.edges_added and not delta.edges_removed


def test_decimal_weighting_and_cap_at_one():
    a = event("b", "e0", 0, invocation="tax", signals={"quality": "0"})
    b = event("c", "e0", 0, invocation="tax", signals={"quality": "9"})
    delta = compare_graphs_v2(project_trace_v2([a]), project_trace_v2([b]), policy())
    assert Decimal(delta.changed_events[0].magnitude) == 1


def test_ambiguous_invocation_is_not_paired_by_ordinal():
    a = [event("b", "a1", 0, invocation="same"), event("b", "a2", 1, invocation="same")]
    b = [event("c", "b1", 0, invocation="same")]
    baseline, candidate = project_trace_v2(a), project_trace_v2(b)
    result = compare_graphs_v2(baseline, candidate, policy())
    assert len(result.ambiguous_events) == 1
    assert result.ambiguous_events[0].baseline_count == 2
    assert result.ambiguous_events[0].candidate_count == 1
    assert not result.changed_events and not result.removed_events
    with pytest.raises(V2Error, match="ambigüedad"):
        assert_pilot_alignment_v2(baseline, candidate, result, policy=policy())


def test_ambiguous_target_is_rejected_even_with_low_global_ambiguity():
    a = repeated("b", 30)
    b = repeated("c", 30)
    # Solo un grupo semántico ambiguo en 120 eventos, menos de 5 %.
    a.append(event("b", "extra1", len(a), invocation="duplicated"))
    a.append(event("b", "extra2", len(a), invocation="duplicated"))
    b.append(event("c", "extra1", len(b), invocation="duplicated"))
    baseline, candidate = project_trace_v2(a), project_trace_v2(b)
    delta = compare_graphs_v2(baseline, candidate, policy())
    assert Decimal(delta.ambiguous_event_rate) < Decimal("0.05")
    assert_pilot_alignment_v2(baseline, candidate, delta, policy=policy())
    with pytest.raises(V2Error, match="Objetivo"):
        assert_pilot_alignment_v2(baseline, candidate, delta, policy=policy(),
                                  target_keys=[tuple(delta.ambiguous_events[0].key)])


def test_branched_graph_and_equal_information_sequential_view():
    before = [
        event("b", "start", 0, invocation="root", kind=EventType.TOOL_CALLED),
        event("b", "left", 1, invocation="left", parents=["start"]),
        event("b", "right", 2, invocation="right", parents=["start"]),
        event("b", "join", 3, invocation="join", parents=["left", "right"]),
    ]
    graph = project_trace_v2(before)
    stats = topology_profile_v2(graph)
    assert stats["branched"] is True and stats["forks"] == 1 and stats["joins"] == 1
    equal_info = sequential_baseline_view_v2(graph)
    ablative = sequential_baseline_view_v2(graph, include_parent_relations=False)
    assert sum(len(row["parent_event_ids"]) for row in equal_info) == len(graph.edges) == 4
    assert all(not row["parent_event_ids"] for row in ablative)
    assert all(a["semantic_values"] == b["semantic_values"] for a, b in zip(equal_info, ablative))


def test_linear_graph_is_declared_non_discriminating():
    linear = project_trace_v2(repeated("b", 3))
    assert topology_profile_v2(linear)["branched"] is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.1, 2**53, -(2**53), {"severity": "high"},
                                   {"nested": [{"mutation_id": "secret"}]}])
def test_canonical_v2_rejects_numeric_unsafe_or_leaks(bad):
    with pytest.raises(V2Error):
        canonical_v2({"content": bad})


@pytest.mark.parametrize("bad", ["0.0", "1.00", "-0", "01", "1e-3", "NaN", "Infinity", "", " 1", ".5"])
def test_decimal_rejects_noncanonical_forms(bad):
    with pytest.raises(V2Error):
        decimal_v2(bad)


def test_decimal_accepts_canonical_forms():
    for value in ("0", "1", "0.001", "-100.25", "12345678901234567890"):
        assert decimal_v2(value) == Decimal(value)


def test_outside_scope_uses_different_key_and_is_not_guessed():
    a = event("b", "e0", 0, invocation="lookup", scope=["workflow", "research"])
    b = event("c", "e0", 0, invocation="lookup", scope=["workflow", "finance"])
    result = compare_graphs_v2(project_trace_v2([a]), project_trace_v2([b]), policy())
    assert len(result.added_events) == len(result.removed_events) == 1


def test_comparison_incompatible_app_case_and_repeat_fail_closed():
    for field, value in [("app_id", AppId.A2), ("case_id", "different"), ("repeat_index", 1)]:
        baseline = event("b", "e0", 0, invocation="target")
        kwargs = baseline.model_dump(mode="python")
        kwargs.update({"run_id": "c", field: value})
        candidate = EventV2.model_validate(kwargs)
        with pytest.raises(V2Error, match="Incompatibilidad"):
            compare_graphs_v2(project_trace_v2([baseline]), project_trace_v2([candidate]), policy())


def test_unassessed_event_is_not_silently_unchanged():
    a = event("b", "e0", 0, invocation="n", kind=EventType.RUN_STARTED, signals={"other": "yes"})
    b = event("c", "e0", 0, invocation="n", kind=EventType.RUN_STARTED, signals={"other": "no"})
    delta = compare_graphs_v2(project_trace_v2([a]), project_trace_v2([b]), policy())
    assert len(delta.unassessed_events) == 1
    assert not delta.changed_events and not delta.unchanged_events
    with pytest.raises(V2Error, match="Objetivo"):
        assert_pilot_alignment_v2(project_trace_v2([a]), project_trace_v2([b]), delta, policy=policy(),
                                  target_keys=[tuple(delta.unassessed_events[0])])


def test_missing_whitelisted_signal_rejected():
    a = event("b", "e0", 0, invocation="n", signals={"quality": "0.5"})
    b = event("c", "e0", 0, invocation="n", signals={"other": "0.5"})
    with pytest.raises(V2Error, match="Falta señal"):
        compare_graphs_v2(project_trace_v2([a]), project_trace_v2([b]), policy())


def test_rejects_invalid_event_and_parent():
    item = event("b", "e0", 0, invocation="n")
    with pytest.raises(V2Error, match="Padre"):
        project_trace_v2([item.model_copy(update={"parent_event_ids": ["future"]})])
    with pytest.raises(V2Error, match="contiguas"):
        project_trace_v2([item.model_copy(update={"sequence": 3})])
    with pytest.raises(V2Error):
        project_trace_v2([item.model_copy(update={"attributes": {"severity": "high"}})])


def test_detects_forged_graph_and_delta():
    baseline, candidate = graphs()
    delta = compare_graphs_v2(baseline, candidate, policy())
    with pytest.raises(V2Error):
        validate_graph_v2(baseline.model_copy(update={"graph_hash": "0" * 64}))
    with pytest.raises(V2Error):
        assert_pilot_alignment_v2(baseline, candidate, delta.model_copy(update={"delta_hash": "0" * 64}), policy=policy())


def test_result_deterministic():
    a, b = graphs()
    result = compare_graphs_v2(a, b, policy())
    assert all(canonical_v2(compare_graphs_v2(a, b, policy())) == canonical_v2(result) for _ in range(5))
    assert sha256_hex(canonical_v2(result.model_dump(mode="json", exclude={"delta_hash"}))) == result.delta_hash


def test_policy_weights_must_sum_one():
    with pytest.raises(ValidationError):
        ComparisonPolicyV2(app_id=AppId.A3, rules=[
            SignalRule(event_type=EventType.TOOL_RETURNED, field="quality", kind="decimal", weight="0.5", scale="1")])


def test_schema_new_versions_do_not_redefine_v1():
    assert EventV2.model_fields["schema_version"].default == "pilot-event-v2"
    assert GraphV2.model_fields["schema_version"].default == "provenance-graph-v2"


def test_v2_oracle_candidates_independent_counts_and_hashes():
    """Los conteos esperados están declarados, no se regeneran desde compare_graphs_v2."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "fixtures/provenance/r0_10"
    cases = json.loads((root / "cases.json").read_bytes())["cases"]
    expected = {row["id"]: row for row in json.loads((root / "expected.json").read_bytes())["cases"]}
    for digest, filename in (line.split("  ", 1) for line in (root / "SHA256SUMS").read_text().splitlines()):
        assert sha256_hex((root / filename).read_bytes()) == digest
    assert len(cases) == 4 and set(expected) == {row["id"] for row in cases}
    for case in cases:
        left = project_trace_v2([EventV2.model_validate_json(canonical_v2(x)) for x in case["baseline"]])
        right = project_trace_v2([EventV2.model_validate_json(canonical_v2(x)) for x in case["candidate"]])
        result = compare_graphs_v2(left, right, policy(left.app_id))
        expectation = expected[case["id"]]
        for field in ("added_events", "removed_events", "changed_events", "unchanged_events",
                      "ambiguous_events", "ignored_payload_changes", "edges_added", "edges_removed",
                      "edges_ambiguous", "unassessed_events"):
            assert len(getattr(result, field)) == expectation[field], f"{case['id']}: {field}"
        assert Decimal(result.ambiguous_event_rate) == Decimal(expectation["ambiguity_rate"])
        if "forks" in expectation:
            assert topology_profile_v2(left)["forks"] == expectation["forks"]
            assert topology_profile_v2(left)["joins"] == expectation["joins"]
        if case["id"] == "V202":
            assert result.changed_events[0].changed_signals == ["relevant_evidence"]
            assert Decimal(result.changed_events[0].magnitude) == Decimal("0.2")


def test_pilot_gate_does_not_trust_rehashed_forged_ambiguity_count():
    baseline, candidate = graphs()
    delta = compare_graphs_v2(baseline, candidate, policy())
    content = delta.model_dump(mode="json", exclude={"delta_hash"})
    content["ambiguous_events"] = [{
        "key": ["event", "model", "search", "workflow", "search", "lookup-0", "tool.returned"],
        "baseline_count": 2, "candidate_count": 2,
    }]
    content["delta_hash"] = sha256_hex(canonical_v2(content))
    forged = type(delta).model_validate_json(canonical_v2(content))
    with pytest.raises(V2Error, match="diferencial"):
        assert_pilot_alignment_v2(baseline, candidate, forged, policy=policy())


def test_magnitude_is_not_counted_as_five_structural_regressions():
    before = event("b", "e0", 0, invocation="step", signals={"quality": "0.8"},
                   attributes={"latency_ms": 30, "tokens": 500})
    after = event("c", "e0", 0, invocation="step", signals={"quality": "0.7"},
                  attributes={"latency_ms": 400, "tokens": 700})
    delta = compare_graphs_v2(project_trace_v2([before]), project_trace_v2([after]), policy())
    assert len(delta.changed_events) == 1
    assert Decimal(delta.changed_events[0].magnitude) == Decimal("0.2")
    assert not delta.edges_added and not delta.edges_removed
    assert not delta.ignored_payload_changes


def test_graph_rejects_rehashed_blank_invocation_key():
    baseline, _ = graphs()
    content = baseline.model_dump(mode="json", exclude={"graph_hash"})
    content["events"][0]["invocation_key"] = ""
    content["graph_hash"] = sha256_hex(canonical_v2(content))
    with pytest.raises(ValidationError):
        GraphV2.model_validate_json(canonical_v2(content))


def test_rejects_policy_replacement_during_pilot_gate():
    a, b = graphs()
    original = compare_graphs_v2(a, b, policy())
    alternate = ComparisonPolicyV2(app_id=AppId.A3, rules=[
        SignalRule(event_type=EventType.TOOL_RETURNED, field="quality", kind="decimal", scale="1", weight="1"),
        SignalRule(event_type=EventType.TOOL_CALLED, field="args_valid", kind="boolean", weight="1"),
    ])
    with pytest.raises(V2Error, match="diferencial"):
        assert_pilot_alignment_v2(a, b, original, policy=alternate)

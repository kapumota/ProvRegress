"""Pruebas I1: trazas creadas por cargas A2/A3 que se ejecutan realmente."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from provregress.pilot.firewall import PilotContaminationError
from provregress.provenance_v2.comparison import (
    assert_pilot_alignment_v2, compare_graphs_v2, sequential_baseline_view_v2,
    topology_profile_v2,
)
from provregress.provenance_v2.live_workloads import (
    CASE_RAG, CASE_TOOLS, ExecutionRecorder, LogicalOperation, ObservableResult,
    assert_external_witness, comparison_policy, demo_study, run_rag_local, run_tools_local,
)
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import V2Error, canonical_v2
from provregress.schema.common import AppId, ComponentType
from provregress.schema.events import EventType
from research.verification.r010_i1_live_runs import execute_pair


@pytest.mark.parametrize("app,runner", [
    (AppId.A2, run_rag_local), (AppId.A3, run_tools_local),
])
@pytest.mark.parametrize("scenario", ["baseline", "insert", "reorder", "noise", "functional", "retry"])
def test_live_execution_has_independent_witness_and_valid_dag(app, runner, scenario):
    b = runner(study=demo_study(), run_id="i1-left")
    a = runner(study=demo_study(), run_id="i1-right", scenario=scenario)
    assert_external_witness(b, a)
    assert len(b.events) == len(b.witness) == len(b.completed_calls)
    assert len(a.events) == len(a.witness) == len(a.completed_calls)
    for run in (b, a):
        graph = project_trace_v2(run.events)
        assert topology_profile_v2(graph)["branched"] is True
        assert len(run.observable_jsonl().splitlines()) == len(run.events)
        for line, event in zip(run.observable_jsonl().splitlines(), run.events):
            assert canonical_v2(json.loads(line)) == canonical_v2(event)
            assert b"logical_id" not in line and b"mutation_id" not in line
    gb, ga = project_trace_v2(b.events), project_trace_v2(a.events)
    delta = compare_graphs_v2(gb, ga, comparison_policy(app))
    assert delta.ambiguous_events == []
    assert delta.ambiguous_event_rate == "0"
    target_type = EventType.RETRIEVAL_RETURNED if app == AppId.A2 else EventType.TOOL_RETURNED
    target = next(node.key for node in gb.events if node.event_type == target_type)
    assert_pilot_alignment_v2(gb, ga, delta, policy=comparison_policy(app), target_keys=[target])


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
def test_insertion_and_reorder_preserve_existing_logical_keys(app, runner):
    b = runner(study=demo_study(), run_id="baseline")
    inserted = runner(study=demo_study(), run_id="with-extra", scenario="insert")
    reordered = runner(study=demo_study(), run_id="order-reversed", scenario="reorder")
    delta_extra = compare_graphs_v2(project_trace_v2(b.events), project_trace_v2(inserted.events),
                                    comparison_policy(app))
    delta_order = compare_graphs_v2(project_trace_v2(b.events), project_trace_v2(reordered.events),
                                    comparison_policy(app))
    assert len(delta_extra.added_events) == 1
    assert not delta_extra.removed_events and not delta_extra.changed_events
    assert not delta_extra.ambiguous_events
    assert delta_order.added_events == []
    assert delta_order.removed_events == []
    assert delta_order.changed_events == []
    assert delta_order.edges_added == [] and delta_order.edges_removed == []
    assert len(delta_order.unchanged_events) >= 3
    assert_external_witness(b, inserted)
    assert_external_witness(b, reordered)


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
def test_operational_noise_is_not_functional_regression(app, runner):
    b = runner(study=demo_study(), run_id="noise-b")
    noisy = runner(study=demo_study(), run_id="noise-c", scenario="noise")
    delta = compare_graphs_v2(project_trace_v2(b.events), project_trace_v2(noisy.events),
                              comparison_policy(app))
    assert delta.changed_events == []
    assert delta.ignored_payload_changes


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
def test_real_functional_difference_detected_on_one_task(app, runner):
    b = runner(study=demo_study(), run_id="functional-b")
    c = runner(study=demo_study(), run_id="functional-c", scenario="functional")
    delta = compare_graphs_v2(project_trace_v2(b.events), project_trace_v2(c.events),
                              comparison_policy(app))
    assert len(delta.changed_events) >= 1
    assert all(change.magnitude != "0" for change in delta.changed_events)
    assert not delta.ambiguous_events


@pytest.mark.parametrize("runner", [run_rag_local, run_tools_local])
def test_witness_detects_swapped_keys_even_if_delta_would_align(runner):
    b = runner(study=demo_study(), run_id="rekey-b")
    c = runner(study=demo_study(), run_id="rekey-c", scenario="rekey")
    # El motor por sí solo no identifica una clave incorrecta: testigo fuera de la traza.
    with pytest.raises(V2Error, match="invocation_key|diferentes"):
        assert_external_witness(b, c)


@pytest.mark.parametrize("app,runner,kind", [
    (AppId.A2, run_rag_local, EventType.RETRIEVAL_RETURNED),
    (AppId.A3, run_tools_local, EventType.TOOL_RETURNED),
])
def test_repeated_operations_three_vs_four_match_distinct_keys(app, runner, kind):
    base = runner(study=demo_study(), run_id="3-iterations")
    extra = runner(study=demo_study(), run_id="4-iterations", scenario="insert")
    a = [event for event in base.events if event.event_type == kind]
    b = [event for event in extra.events if event.event_type == kind]
    assert (len(a), len(b)) == (3, 4)
    assert len({x.component_id for x in b}) == 1
    assert len({x.invocation_key for x in b}) == 4
    delta = compare_graphs_v2(project_trace_v2(base.events), project_trace_v2(extra.events),
                              comparison_policy(app))
    assert len(delta.added_events) == 1
    assert not delta.changed_events and not delta.ambiguous_events
    assert_external_witness(base, extra)


@pytest.mark.parametrize("app,runner,kind", [
    (AppId.A2, run_rag_local, EventType.RETRIEVAL_RETURNED),
    (AppId.A3, run_tools_local, EventType.TOOL_RETURNED),
])
def test_retry_is_a_real_fourth_operation_with_declared_parent(app, runner, kind):
    baseline = runner(study=demo_study(), run_id="retry-b")
    candidate = runner(study=demo_study(), run_id="retry-c", scenario="retry")
    assert_external_witness(baseline, candidate)
    events = [event for event in candidate.events if event.event_type == kind]
    assert len(events) == 4
    key_by_id = {event.event_id: event.invocation_key for event in candidate.events}
    retry = next(event for event in events if "retry" in event.invocation_key)
    assert len(retry.parent_event_ids) == 1
    assert key_by_id[retry.parent_event_ids[0]] in ("refund-document", "check-inventory")
    delta = compare_graphs_v2(project_trace_v2(baseline.events),
                              project_trace_v2(candidate.events), comparison_policy(app))
    assert len(delta.added_events) == 1
    assert not delta.changed_events and not delta.ambiguous_events


def test_firewall_blocks_confirmatory_before_io(tmp_path: Path):
    missing = tmp_path / "missing-corpus"
    with pytest.raises(PilotContaminationError):
        run_rag_local(study=demo_study(), run_id="blocked",
                      case_id="confirmatory-rag-local", corpus=missing)
    with pytest.raises(PilotContaminationError):
        run_tools_local(study=demo_study(), run_id="blocked",
                        case_id="confirmatory-tools-local", catalog_path=tmp_path / "missing.json")


def test_recorder_rejects_duplicate_key_and_bad_parent_without_callback():
    rec = ExecutionRecorder(study=demo_study(), app_id=AppId.A3, case_id=CASE_TOOLS,
                            run_id="identity", condition_id="baseline", system_version_id="v1")
    ran: list[int] = []
    first = LogicalOperation("operation.one", "first", ("app",), EventType.TOOL_RETURNED,
                             ComponentType.TOOL, "same-tool")
    rec.record(first, lambda: ObservableResult({"result": 1}, {"task_ok": True}, {}))
    duplicate = LogicalOperation("operation.two", "first", ("app",), EventType.TOOL_RETURNED,
                                 ComponentType.TOOL, "same-tool")
    with pytest.raises(V2Error, match="Colisión"):
        rec.record(duplicate, lambda: ran.append(1))
    wrong_parent = LogicalOperation("operation.three", "third", ("app",), EventType.TOOL_RETURNED,
                                    ComponentType.TOOL, "same-tool", ("unknown",))
    with pytest.raises(V2Error, match="dependencia"):
        rec.record(wrong_parent, lambda: ran.append(2))
    assert ran == []


def test_events_are_real_function_outputs_not_static_oracles(tmp_path: Path):
    source = tmp_path / "refund.md"
    source.write_text("Existe reembolso aquí.", encoding="utf-8")
    (tmp_path / "shipping.md").write_text("Solo transporte.", encoding="utf-8")
    (tmp_path / "returns.md").write_text("Condiciones generales.", encoding="utf-8")
    study = demo_study()
    first = run_rag_local(study=study, run_id="corpus-original", corpus=tmp_path)
    source.write_text("No existe devolución aquí.", encoding="utf-8")
    second = run_rag_local(study=study, run_id="corpus-modified", corpus=tmp_path)
    delta = compare_graphs_v2(project_trace_v2(first.events), project_trace_v2(second.events),
                              comparison_policy(AppId.A2))
    assert len(delta.changed_events) >= 1
    assert not delta.ambiguous_events


def test_primary_sequential_baseline_has_same_parent_evidence():
    execution = run_tools_local(study=demo_study(), run_id="sequential")
    graph = project_trace_v2(execution.events)
    view = sequential_baseline_view_v2(graph)
    assert sum(len(row["parent_event_ids"]) for row in view) == len(graph.edges)
    assert {row["event_id"] for row in view} == {event.event_id for event in execution.events}


@pytest.mark.parametrize("app", [AppId.A2, AppId.A3])
def test_cli_executor_returns_consistent_summary_and_separates_outputs(app, tmp_path: Path):
    destination = tmp_path / app.value
    summary = execute_pair(app, scenario="insert", output=destination)
    assert summary["added_events"] == 1
    assert summary["ambiguous_events"] == 0
    assert summary["baseline_branched"] and summary["candidate_branched"]
    assert set(x.name for x in (destination / "observable").iterdir()) == {
        "baseline.jsonl", "candidate.jsonl", "baseline-graph.json",
        "candidate-graph.json", "delta.json",
    }
    assert {x.name for x in (destination / "privileged").iterdir()} == {
        "baseline-witness.json", "candidate-witness.json", "execution-hashes.json",
    }
    assert b"logical_id" not in (destination / "observable" / "candidate.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        execute_pair(app, scenario="insert", output=destination)

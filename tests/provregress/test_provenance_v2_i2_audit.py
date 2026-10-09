"""Gate I2: testigo externo, métricas exactas y cobertura de objetivos A2/A3."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from provregress.provenance_v2.live_workloads import (
    ExecutedRun, Witness, comparison_policy, demo_study, run_rag_local, run_tools_local,
)
from provregress.provenance_v2.pilot_audit import (
    PairAuditV2, assert_i2_cohort_gate, audit_execution_pair_v2, _equivalent_sequential_input,
)
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import V2Error, canonical_v2
from provregress.schema.common import AppId
from research.verification.r010_i2_pilot_audit import (
    _scenario_contract, audit_i2_local,
)


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
@pytest.mark.parametrize("scenario", ["baseline", "insert", "reorder", "noise", "functional", "retry"])
def test_pilot_scenarios_pass_with_independent_ground_truth(app, runner, scenario):
    study = demo_study()
    b = runner(study=study, run_id="i2-b")
    c = runner(study=study, run_id="i2-c", scenario=scenario)
    record = audit_execution_pair_v2(b, c, comparison_policy(app), scenario=scenario,
                                     **_scenario_contract(app, scenario))
    assert record.passed, record.privileged_dict()
    assert record.false_pairs == record.missed_pairs == 0
    assert record.ambiguous_members == 0
    assert record.ambiguity_rate == Decimal(0)
    assert record.target_covered == record.target_count == 4
    assert record.equivalent_sequential_input and record.branched_both


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
def test_rekey_is_false_alignment_even_when_ambiguity_rate_is_zero(app, runner):
    b = runner(study=demo_study(), run_id="rekey-b")
    c = runner(study=demo_study(), run_id="rekey-c", scenario="rekey")
    record = audit_execution_pair_v2(b, c, comparison_policy(app), scenario="rekey",
                                     **_scenario_contract(app, "rekey"))
    assert record.ambiguity_rate == 0
    assert record.false_pairs == 2
    assert record.missed_pairs == 2
    assert record.target_covered < record.target_count
    assert record.passed is False
    assert record.errors


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
def test_unknown_mutation_target_is_rejected(app, runner):
    b = runner(study=demo_study(), run_id="target-b")
    c = runner(study=demo_study(), run_id="target-c")
    result = audit_execution_pair_v2(b, c, comparison_policy(app), scenario="baseline",
                                    target_logical_ids=("unknown-experiment-target",))
    assert result.target_covered == 0
    assert not result.passed


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
def test_wrong_expected_functional_change_causes_failure(app, runner):
    b = runner(study=demo_study(), run_id="f-b")
    c = runner(study=demo_study(), run_id="f-c", scenario="functional")
    result = audit_execution_pair_v2(b, c, comparison_policy(app), scenario="functional",
                                    target_logical_ids=_scenario_contract(app, "functional")["target_logical_ids"])
    assert result.functional_false_positives > 0
    assert result.passed is False


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
def test_missing_expected_added_event_fails(app, runner):
    b = runner(study=demo_study(), run_id="insert-b")
    c = runner(study=demo_study(), run_id="insert-c", scenario="insert")
    result = audit_execution_pair_v2(b, c, comparison_policy(app), scenario="insert",
                                    target_logical_ids=_scenario_contract(app, "insert")["target_logical_ids"])
    assert result.added_false_positives == 1
    assert not result.passed


@pytest.mark.parametrize("app,runner", [(AppId.A2, run_rag_local), (AppId.A3, run_tools_local)])
def test_corrupt_or_missing_witness_fails_closed(app, runner):
    b = runner(study=demo_study(), run_id="bad-b")
    c = runner(study=demo_study(), run_id="bad-c")
    params = _scenario_contract(app, "baseline")
    for bad in (
        replace(c, witness=c.witness[:-1]),
        replace(c, witness=(Witness("missing-event", "fake"), *c.witness[1:])),
        replace(c, completed_calls=(*c.completed_calls, c.completed_calls[0])),
    ):
        with pytest.raises(V2Error):
            audit_execution_pair_v2(b, bad, comparison_policy(app), scenario="baseline", **params)


def test_requires_nonempty_unique_declared_targets():
    b = run_tools_local(study=demo_study(), run_id="invalid-b")
    c = run_tools_local(study=demo_study(), run_id="invalid-c")
    for targets in ((), ("tools.inventory", "tools.inventory"), ("",)):
        with pytest.raises(V2Error):
            audit_execution_pair_v2(b, c, comparison_policy(AppId.A3), scenario="baseline",
                                    target_logical_ids=targets)


def test_sequential_baseline_has_same_parents_and_signals():
    run = run_rag_local(study=demo_study(), run_id="seq")
    graph = project_trace_v2(run.events)
    assert _equivalent_sequential_input(graph, run)
    # Una relación falseada debe ser rechazada por el cotejo independiente.
    victim = next(x for x in run.events if x.parent_event_ids)
    changed = victim.model_copy(update={"parent_event_ids": []})
    altered = replace(run, events=tuple(changed if x is victim else x for x in run.events))
    assert not _equivalent_sequential_input(graph, altered)


def test_ambiguity_gate_uses_exact_counts_without_rounding():
    b = run_rag_local(study=demo_study(), run_id="exact-b")
    c = run_rag_local(study=demo_study(), run_id="exact-c")
    record = audit_execution_pair_v2(b, c, comparison_policy(AppId.A2), scenario="baseline",
                                     **_scenario_contract(AppId.A2, "baseline"))
    assert record.passed
    assert replace(record, ambiguous_members=1).ambiguity_rate > Decimal("0.05")
    assert not replace(record, ambiguous_members=1).passed


def test_full_cohort_has_six_scenarios_per_app_and_detects_rekey():
    summary = audit_i2_local(repeats=2)
    assert summary["status"] == "pass_local_instrumentation"
    assert summary["negative_rekey_rejections"] == 4
    assert len(summary["audit_hash"]) == 64
    assert all(app["pairs"] == 12 and app["false_pairs"] == 0
               and app["missed_pairs"] == 0 and app["target_coverage"] == "1"
               and app["branched_pairs"] == 12
               for app in summary["applications"].values())


def test_incomplete_cohort_is_rejected():
    with pytest.raises(V2Error, match="Faltan escenarios"):
        assert_i2_cohort_gate([], repeats=2)


def test_privileged_witnesses_are_separate_from_public_summary(tmp_path: Path):
    dest = tmp_path / "audit-i2"
    summary = audit_i2_local(repeats=1, output=dest)
    public = (dest / "audit-summary.json").read_bytes()
    protected = (dest / "privileged" / "pair-reports.json").read_bytes()
    assert json.loads(public)["audit_hash"] == summary["audit_hash"]
    assert b"logical_id" not in public and b"invocation_key" not in public
    assert b"rag.refund" not in public and b"tools.inventory" not in public
    assert b"rag.refund" in protected and b"tools.inventory" in protected
    assert canonical_v2(json.loads(public)) + b"\n" == public
    assert (dest / "privileged" / "pair-reports.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        audit_i2_local(repeats=1, output=dest)


@pytest.mark.parametrize("repeats", [0, -1, 21, True, "3"])
def test_rejects_unsupported_repetition_counts(repeats):
    with pytest.raises(V2Error):
        audit_i2_local(repeats=repeats)

"""Gates I4 de cohorte predeclarada, contrafactuales y baselines equitativos."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from provregress.provenance_v2.cohort_audit import (
    _annotation_index, _decimal_score, _edges_from_rows, _run_variant,
    read_cohort, run_cohort, strong_sequential_comparison,
)
from provregress.provenance_v2.comparison import compare_graphs_v2, sequential_baseline_view_v2
from provregress.provenance_v2.live_workloads import comparison_policy
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import EventV2, V2Error
from provregress.schema.common import AppId
from research.verification.r010_i4_cohort_eval import COHORT, ANNOTATIONS
from provregress.storage.hashing import sha256_hex


@pytest.fixture(scope="module")
def cohort():
    return read_cohort(COHORT)


@pytest.fixture(scope="module")
def annotations():
    return json.loads(ANNOTATIONS.read_bytes())


def test_cohort_hash_is_pinned_before_assessment(cohort):
    assert sha256_hex(COHORT.read_bytes()) == "813970ca018b2249cadf6e050df5809f64302b9d587240628c793435943ac3a3"
    assert len(cohort["scenarios"]) == 10
    assert cohort["repetitions"] == [0, 1, 2]


@pytest.mark.parametrize("invalid", [
    {"repetitions": [0]},
    {"max_ambiguity_rate": "1"},
    {"maximum_false_pairs": 1},
    {"information_parity_required": False},
    {"scenarios": []},
])
def test_cohort_rejects_protocol_changes(tmp_path, invalid, cohort):
    path = tmp_path / "cohort.json"
    path.write_text(json.dumps({**cohort, **invalid}), encoding="utf-8")
    with pytest.raises(V2Error):
        read_cohort(path)


def test_cohort_rejects_duplicate_scenario(tmp_path, cohort):
    changes = dict(cohort)
    changes["scenarios"] = list(cohort["scenarios"])
    changes["scenarios"][1] = changes["scenarios"][0]
    path = tmp_path / "duplicated.json"
    path.write_text(json.dumps(changes), encoding="utf-8")
    with pytest.raises(V2Error):
        read_cohort(path)


@pytest.mark.parametrize("app,app_field", [(AppId.A2, "a2"), (AppId.A3, "a3")])
def test_dynamic_identity_is_validated_from_resource_not_ordinal(app, app_field, tmp_path, annotations):
    before = _run_variant(app, "standard", run_id=f"i4-ident-b-{app_field}", workspace=tmp_path / "base")
    after = _run_variant(app, "extended", run_id=f"i4-ident-c-{app_field}", workspace=tmp_path / "new")
    left = _annotation_index(before, annotations[app_field])
    right = _annotation_index(after, annotations[app_field])
    assert all(left[key] == right[key] for key in left)
    assert len(set(right.values())) == len(right)
    assert len(right) == len(left) + 1


@pytest.mark.parametrize("app,app_field", [(AppId.A2, "a2"), (AppId.A3, "a3")])
def test_swapped_invocations_rejected_even_with_zero_ambiguity(app, app_field, tmp_path, annotations):
    candidate = _run_variant(app, "extended", run_id=f"i4-rekey-{app_field}", workspace=tmp_path)
    events = list(candidate.events)
    kind = annotations[app_field]["event_type"]
    positions = [i for i, ev in enumerate(events) if ev.event_type.value == kind]
    assert len(positions) >= 2
    a, b = positions[:2]
    x, y = events[a].invocation_key, events[b].invocation_key
    events[a] = EventV2.model_validate({**events[a].model_dump(mode="python"), "invocation_key": y})
    events[b] = EventV2.model_validate({**events[b].model_dump(mode="python"), "invocation_key": x})
    forged = replace(candidate, events=tuple(events))
    with pytest.raises(V2Error, match="Correspondencia falsa"):
        _annotation_index(forged, annotations[app_field])


def test_seq_strong_rejects_unknown_parent_and_duplicate():
    left = [{"event_id": "a", "semantic_key": ["event", "first"],
             "parent_event_ids": ["missing"]}]
    with pytest.raises(V2Error, match="Padre desconocido"):
        _edges_from_rows(left)
    left.append({"event_id": "a", "semantic_key": ["event", "second"], "parent_event_ids": []})
    with pytest.raises(V2Error, match="Identificador secuencial duplicado"):
        _edges_from_rows(left)


def test_seq_strong_matches_graph_diff_on_functional_case(tmp_path):
    before = _run_variant(AppId.A2, "standard", run_id="i4-func-b", workspace=tmp_path / "b")
    after = _run_variant(AppId.A2, "functional", run_id="i4-func-c", workspace=tmp_path / "c")
    a, b = project_trace_v2(before.events), project_trace_v2(after.events)
    policy = comparison_policy(AppId.A2)
    d = compare_graphs_v2(a, b, policy)
    strong = strong_sequential_comparison(sequential_baseline_view_v2(a),
                                          sequential_baseline_view_v2(b), policy)
    assert len(d.changed_events) == 2
    assert len(strong["changed"]) == len(d.changed_events)
    assert all(item.magnitude == "1" for item in d.changed_events)
    assert _decimal_score(sum((__import__("decimal").Decimal(x.magnitude) for x in d.changed_events),
                              __import__("decimal").Decimal(0))) == "2.000000"


def test_seq_ablated_loses_links_but_not_identifiers(tmp_path):
    run = _run_variant(AppId.A3, "standard", run_id="i4-ablated", workspace=tmp_path)
    graph = project_trace_v2(run.events)
    full = sequential_baseline_view_v2(graph, include_parent_relations=True)
    ablated = sequential_baseline_view_v2(graph, include_parent_relations=False)
    assert len(full) == len(ablated)
    assert _edges_from_rows(ablated) == set()
    assert len(_edges_from_rows(full)) == len(graph.edges)
    assert [x["semantic_key"] for x in ablated] == [x["semantic_key"] for x in full]


def test_cohort_report_all_pairs_and_no_superiority_claim(tmp_path, cohort):
    result = run_cohort(cohort_path=COHORT, annotations_path=ANNOTATIONS,
                        output_dir=tmp_path / "output")
    assert result["pairs"] == 30
    assert result["scientific_freeze"] == "blocked_pending_external_validation"
    assert result["superiority_over_sequence"] == "not_demonstrated"
    assert result["summary_sha256"] == "4241fa7d975270ff4cb00934f8aa77aa1a30cbab43b43e067347dc1a8810c58c"
    for app in (AppId.A2.value, AppId.A3.value):
        report = result["per_app"][app]
        assert report["pairs"] == 15
        assert report["false_pairs"] == report["missed_pairs"] == 0
        assert report["minimum_target_coverage"] == "1"
        assert report["maximum_ambiguity"] == "0"
        assert report["strong_sequence_parity_pairs"] == 15
    details = json.loads((tmp_path / "output/pair-reports.json").read_bytes())
    assert len(details) == 30
    assert {(x["scenario"], x["app_id"]) for x in details} == {
        (s["id"], s["app"]) for s in cohort["scenarios"]}
    assert all(x["trace_hashes_verified"] for x in details)
    assert all(isinstance(x["functional_magnitude_sum"], str) for x in details)
    assert any(x["branched_baseline"] and not x["branched_candidate"] for x in details)


def test_existing_output_is_never_overwritten(tmp_path):
    output = tmp_path / "present"
    output.mkdir()
    with pytest.raises(V2Error, match="directorio nuevo"):
        run_cohort(cohort_path=COHORT, annotations_path=ANNOTATIONS, output_dir=output)


def test_predeclared_oracle_cannot_be_rewritten_to_fit_output(tmp_path, cohort):
    modified = dict(cohort)
    modified["scenarios"] = [dict(row) for row in cohort["scenarios"]]
    modified["scenarios"][0]["added"] = ["retrieve:tracking.md"]
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(V2Error, match="Diferencial added"):
        run_cohort(cohort_path=path, annotations_path=ANNOTATIONS, output_dir=tmp_path / "evidence")

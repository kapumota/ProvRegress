"""R1.0-M2-P2: operadores de sistema y análisis no causal de propagación."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.mutation_v2.local_smoke import run_local_smoke_m2
from provregress.mutation_v2.system_treatments import (
    SystemRequestM2, SystemSnapshotM2, SystemTreatmentError,
    make_request, materialize_snapshot, read_system_snapshot, stage_system_treatment,
)
from provregress.provenance_v2.comparison_v21 import compare_graphs_v21
from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic
from provregress.provenance_v2.live_workloads import (
    DEFAULT_INPUTS, comparison_policy, demo_study,
)
from provregress.provenance_v2.projector import project_trace_v2
from provregress.mutation_v2.propagation_audit import (
    audit_propagation_m2, public_propagation_summary,
)
from provregress.schema.common import AppId
from provregress.storage.hashing import sha256_hex
from provregress.provenance_v2.schema import V2Error, canonical_v2
from research.verification.r100_m2_p2_system_smoke import evaluate_local_examples


@pytest.fixture
def source():
    return read_system_snapshot(DEFAULT_INPUTS)


@pytest.mark.parametrize("operator,target,new_value,expected_field", [
    ("prompt.query.replace.v1", "query", "envío", "query"),
    ("retrieval.top_k.set.v1", "top_k", 4, "top_k"),
    ("index.document.replace.v1", "refund.md", "Texto nuevo sin coincidencia", "documents"),
    ("tool.catalog.field.set.v1", "item.stock", 0, "catalog"),
    ("tool.catalog.field.set.v1", "enable_discount_step", True, "catalog"),
])
def test_stage_changes_only_requested_property(source, operator, target, new_value, expected_field):
    original = source.model_dump(mode="json")
    request = make_request(source, operator, target, new_value)
    result, receipt = stage_system_treatment(source, request)
    assert receipt.source_snapshot_hash == source.snapshot_hash
    assert receipt.candidate_snapshot_hash == result.snapshot_hash
    assert receipt.source_snapshot_hash != receipt.candidate_snapshot_hash
    assert receipt.confirmatory_execution is False
    assert source.model_dump(mode="json") == original
    assert {k for k in original if original[k] != result.model_dump(mode="json")[k]} == {expected_field}


@pytest.mark.parametrize("operator,target,value", [
    ("prompt.query.replace.v1", "query", "reembolso"),
    ("retrieval.top_k.set.v1", "top_k", 3),
    ("index.document.replace.v1", "refund.md", None),
    ("tool.catalog.field.set.v1", "item.stock", 10),
])
def test_identity_or_invalid_replacement_fails(source, operator, target, value):
    with pytest.raises((SystemTreatmentError, ValidationError, V2Error)):
        stage_system_treatment(source, make_request(source, operator, target, value))


@pytest.mark.parametrize("operator,target,value", [
    ("retrieval.top_k.set.v1", "top_k", True),
    ("retrieval.top_k.set.v1", "top_k", 0),
    ("retrieval.top_k.set.v1", "top_k", 33),
    ("tool.catalog.field.set.v1", "item.stock", True),
    ("tool.catalog.field.set.v1", "item.stock", -1),
    ("tool.catalog.field.set.v1", "item.discount_eligible", 1),
    ("prompt.query.replace.v1", "query", " "),
    ("index.document.replace.v1", "refund.md", "x" * 17000),
])
def test_wrong_types_and_limits_rejected(source, operator, target, value):
    with pytest.raises((SystemTreatmentError, ValidationError, V2Error)):
        stage_system_treatment(source, make_request(source, operator, target, value))


@pytest.mark.parametrize("operator,target", [
    ("index.document.replace.v1", "../catalog.json"),
    ("index.document.replace.v1", "/tmp/exfil.md"),
    ("index.document.replace.v1", "nested/file.md"),
    ("index.document.replace.v1", "nonexistent.md"),
    ("tool.catalog.field.set.v1", "item.admin_override"),
    ("tool.catalog.field.set.v1", "item.stock/../../x"),
    ("prompt.query.replace.v1", "system_message"),
])
def test_unknown_or_path_traversal_rejected(source, operator, target):
    with pytest.raises((SystemTreatmentError, ValidationError, V2Error)):
        make_request(source, operator, target, "texto")


def test_sha_precondition_rejects_stale_target(source):
    request = make_request(source, "retrieval.top_k.set.v1", "top_k", 4)
    with pytest.raises(SystemTreatmentError, match="precondición"):
        stage_system_treatment(source, request.model_copy(update={"expected_before_hash": "a" * 64}))


def test_unknown_operator_rejected(source):
    with pytest.raises(SystemTreatmentError):
        make_request(source, "tool.deactivate-all.v1", "item.stock", 0)


def test_snapshot_rejects_noncanonical_numeric(source):
    data = source.model_dump(mode="python")
    data["catalog"]["item"]["price_units"] = 1.25
    with pytest.raises((V2Error, ValidationError, ValueError)):
        SystemSnapshotM2.model_validate(data)


def test_source_directory_rejects_link_and_unexpected_files(tmp_path):
    link = tmp_path / "alias"
    link.symlink_to(DEFAULT_INPUTS, target_is_directory=True)
    with pytest.raises(SystemTreatmentError):
        read_system_snapshot(link)
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "catalog.json").write_bytes((DEFAULT_INPUTS / "catalog.json").read_bytes())
    (folder / "refund.md").write_text("Prueba", encoding="utf-8")
    (folder / "evil.py").write_text("x")
    with pytest.raises(SystemTreatmentError):
        read_system_snapshot(folder)


def test_catalog_duplicate_keys_rejected(tmp_path):
    (tmp_path / "refund.md").write_text("Hola")
    (tmp_path / "catalog.json").write_text('{"item":{},"item":{}}')
    with pytest.raises(SystemTreatmentError, match="claves duplicadas"):
        read_system_snapshot(tmp_path)


def test_materialized_candidate_isolated_and_new_only(tmp_path, source):
    before_hash = source.snapshot_hash
    request = make_request(source, "tool.catalog.field.set.v1", "item.stock", 0)
    candidate, receipt = stage_system_treatment(source, request)
    dst = tmp_path / "sandbox"
    documents, catalog = materialize_snapshot(candidate, dst)
    assert catalog.is_file()
    assert read_system_snapshot(documents).snapshot_hash != before_hash
    assert source.snapshot_hash == before_hash
    with pytest.raises(SystemTreatmentError):
        materialize_snapshot(candidate, dst)


@pytest.mark.parametrize("app,operator,target,value,expected", [
    (AppId.A2, "prompt.query.replace.v1", "query", "entrega", "functional_observed"),
    (AppId.A2, "retrieval.top_k.set.v1", "top_k", 4, "structural_only"),
    (AppId.A2, "index.document.replace.v1", "refund.md", "Documento sin coincidencias léxicas.", "functional_observed"),
    (AppId.A3, "tool.catalog.field.set.v1", "item.stock", 0, "functional_observed"),
    (AppId.A3, "tool.catalog.field.set.v1", "item.price_units", 200, "payload_only"),
])
def test_real_local_workload_observes_or_classifies_silences(source, app, operator, target, value, expected):
    req = make_request(source, operator, target, value)
    result = run_local_smoke_m2(source_dir=DEFAULT_INPUTS, request=req, app_id=app)
    assert result["impact"] == expected
    assert result["confirmatory_execution"] is False
    assert result["scientific_evidence"] == "not_admissible"
    assert result["staged_snapshot_changed"] is True
    assert not any(k in result for k in ("mutation_id", "operator_id", "operator_class", "target", "parameters", "staged_source_hash", "staged_candidate_hash"))
    if expected == "payload_only":
        assert result["silent_functional"] is True
        assert result["payload_only"] >= 1
        assert result["observed_functional"] == 0
    if expected == "structural_only":
        assert result["silent_functional"] is True
        assert result["structural_changes"] >= 1
    if expected == "functional_observed":
        assert result["observed_functional"] >= 1
        assert result["silent_functional"] is False


def test_propagation_does_not_count_all_descendants_as_changed():
    study = demo_study()
    baseline = run_rag_dynamic(study=study, run_id="p2-base", top_k=3)
    candidate = run_rag_dynamic(study=study, run_id="p2-new", top_k=4)
    first = project_trace_v2(list(baseline.events))
    second = project_trace_v2(list(candidate.events))
    policy = comparison_policy(AppId.A2)
    delta = compare_graphs_v21(first, second, policy)
    report = audit_propagation_m2(first, second, delta, policy=policy, root_invocation_key="query:refund")
    summary = public_propagation_summary(report)
    assert summary["potential_descendants"] >= 3
    assert summary["observed_descendants"] == 0
    assert summary["structural_changes"] >= 1
    assert summary["silent_functional"] is True
    assert "root_invocation_key" not in summary


def test_wrong_root_rejected():
    study = demo_study()
    baseline = run_rag_dynamic(study=study, run_id="test-b")
    candidate = run_rag_dynamic(study=study, run_id="test-c")
    first = project_trace_v2(list(baseline.events))
    second = project_trace_v2(list(candidate.events))
    policy = comparison_policy(AppId.A2)
    delta = compare_graphs_v21(first, second, policy)
    with pytest.raises(V2Error, match="raíz"):
        audit_propagation_m2(first, second, delta, policy=policy, root_invocation_key="unknown")


def test_contradictory_delta_rejected():
    study = demo_study()
    baseline = run_rag_dynamic(study=study, run_id="test-b")
    candidate = run_rag_dynamic(study=study, run_id="test-c", top_k=4)
    first = project_trace_v2(list(baseline.events))
    second = project_trace_v2(list(candidate.events))
    policy = comparison_policy(AppId.A2)
    delta = compare_graphs_v21(first, second, policy)
    wrong = delta.model_dump(mode="json", exclude={"delta_hash"})
    wrong["added_events"] = []
    wrong["delta_hash"] = sha256_hex(canonical_v2(wrong))
    forged = type(delta).model_validate(wrong)
    with pytest.raises(V2Error, match="no corresponde"):
        audit_propagation_m2(first, second, forged, policy=policy, root_invocation_key="query:refund")


def test_full_demo_returns_all_scenarios_without_exclusions():
    reports = evaluate_local_examples()
    assert len(reports) == 5
    assert sum(r["impact"] == "payload_only" for r in reports) == 1
    assert all(r["confirmatory_execution"] is False for r in reports)

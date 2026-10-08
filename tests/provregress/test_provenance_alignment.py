"""Gate R0.8-I3: alineamiento semántico conservador sin cálculo de DeltaG."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from provregress.provenance.alignment import (
    AlignedNode,
    AlignmentError,
    AmbiguousGroup,
    GraphAlignment,
    GraphComparisonError,
    UnmatchedNode,
    align_graphs,
    semantic_key,
)
from provregress.provenance.projector import project_trace
from provregress.schema.events import EventEnvelope
from provregress.schema.graph import ProvenanceGraph
from provregress.storage.hashing import canonical_json_bytes, sha256_hex

ROOT = Path(__file__).resolve().parents[1] / "fixtures/provenance/r0_8"
INPUTS = json.loads((ROOT / "inputs.json").read_bytes())
EXPECTED = json.loads((ROOT / "expected.json").read_bytes())
SOURCES = {(item["id"], item["variant"]): item for item in INPUTS["cases"]}
OUTPUTS = {(item["id"], item["variant"]): item for item in EXPECTED["cases"]}
PAIRED = tuple(key for key, item in OUTPUTS.items() if item.get("delta") is not None)


def graphs(case_id: str) -> tuple[ProvenanceGraph, ProvenanceGraph]:
    """Carga grafos golden estrictos sin derivarlos de un algoritmo de alineamiento."""
    item = next(item for item in OUTPUTS.values() if item["id"] == case_id and "delta" in item)
    both = item["graphs"]
    return (ProvenanceGraph.model_validate_json(canonical_json_bytes(both["baseline"])),
            ProvenanceGraph.model_validate_json(canonical_json_bytes(both["candidate"])))


def key_order(keys: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    """Orden de claves semánticas declarado en el contrato F2."""
    return sorted(keys, key=lambda key: canonical_json_bytes(list(key)))


@pytest.mark.parametrize("case", [key[0] for key in PAIRED])
def test_golden_pairing_partitions_each_graph_exactly(case: str) -> None:
    before, after = graphs(case)
    result = align_graphs(before, after)
    assert isinstance(result, GraphAlignment)
    assert result.baseline_run_id == before.run_id
    assert result.candidate_run_id == after.run_id
    left_ids = ([p.baseline_node_id for p in result.pairs] +
                [n.node_id for n in result.baseline_only] +
                [node_id for g in result.ambiguous for node_id in g.baseline_node_ids])
    right_ids = ([p.candidate_node_id for p in result.pairs] +
                 [n.node_id for n in result.candidate_only] +
                 [node_id for g in result.ambiguous for node_id in g.candidate_node_ids])
    assert len(left_ids) == len(set(left_ids)) == len(before.nodes)
    assert len(right_ids) == len(set(right_ids)) == len(after.nodes)
    assert set(left_ids) == {node.node_id for node in before.nodes}
    assert set(right_ids) == {node.node_id for node in after.nodes}
    assert len({pair.key for pair in result.pairs}) == len(result.pairs)
    assert [p.key for p in result.pairs] == key_order([p.key for p in result.pairs])
    for attr in ("baseline_only", "candidate_only", "ambiguous"):
        entries = getattr(result, attr)
        assert [x.key for x in entries] == key_order([x.key for x in entries])


@pytest.mark.parametrize("case", [key[0] for key in PAIRED])
def test_golden_classes_match_precomputed_delta_keys(case: str) -> None:
    before, after = graphs(case)
    result = align_graphs(before, after)
    expected = next(x["delta"] for x in OUTPUTS.values() if x["id"] == case)
    matching = {tuple(x) for x in expected["node_unchanged"]} | {
        tuple(x["key"]) for x in expected["node_changed"]
    }
    assert {p.key for p in result.pairs} == matching
    assert {n.key for n in result.baseline_only} == {tuple(x) for x in expected["node_removed"]}
    assert {n.key for n in result.candidate_only} == {tuple(x) for x in expected["node_added"]}
    assert [dict(key=list(g.key), baseline_count=g.baseline_count,
                 candidate_count=g.candidate_count) for g in result.ambiguous] == expected["node_ambiguous"]


def test_g02_equal_observables_with_different_run_and_clock() -> None:
    left, right = graphs("G02")
    assert left.run_id != right.run_id
    result = align_graphs(left, right)
    assert len(result.pairs) == 3
    assert not result.baseline_only and not result.candidate_only and not result.ambiguous
    assert all(p.baseline_node_id != p.candidate_node_id for p in result.pairs)


def test_g03_payload_change_does_not_pair_by_similarity() -> None:
    left, right = graphs("G03")
    result = align_graphs(left, right)
    assert {p.key[0] for p in result.pairs} == {"component", "event"}
    assert len(result.baseline_only) == len(result.candidate_only) == 1
    assert result.baseline_only[0].key[0] == "payload"
    assert result.candidate_only[0].key[0] == "payload"
    assert not result.ambiguous


def test_g04_topology_does_not_change_node_pairing() -> None:
    left, right = graphs("G04")
    result = align_graphs(left, right)
    assert len(result.pairs) == len(left.nodes) == len(right.nodes)
    assert not result.baseline_only and not result.candidate_only and not result.ambiguous


def test_g05_independent_event_order_is_not_a_key() -> None:
    left, right = graphs("G05")
    alignment = align_graphs(left, right)
    assert len(alignment.pairs) == len(left.nodes) == len(right.nodes)
    assert not alignment.ambiguous
    assert not alignment.baseline_only and not alignment.candidate_only


def test_g06_repeated_event_is_ambiguous_without_ordinal_pairing() -> None:
    left, right = graphs("G06")
    alignment = align_graphs(left, right)
    assert len(alignment.ambiguous) == 1
    group = alignment.ambiguous[0]
    assert group.key == ("event", "model", "same-model", "model.invoked")
    assert group.baseline_count == group.candidate_count == 2
    assert len(set(group.baseline_node_ids)) == len(set(group.candidate_node_ids)) == 2
    assert all(pair.key != group.key for pair in alignment.pairs)
    assert all(item.key != group.key for item in alignment.baseline_only)
    assert all(item.key != group.key for item in alignment.candidate_only)


def test_g06_ambiguous_even_when_only_candidate_repeats() -> None:
    """Una única llamada baseline no se asigna a dos candidatas por azar."""
    source = SOURCES[("G06", "ambiguous-repeated-event")]["traces"]
    baseline = project_trace([EventEnvelope.model_validate_json(canonical_json_bytes(e)) for e in source["baseline"][:1]])
    candidate = graphs("G06")[1]
    result = align_graphs(baseline, candidate)
    assert len(result.ambiguous) == 1
    assert result.ambiguous[0].baseline_count == 1
    assert result.ambiguous[0].candidate_count == 2


def test_g06_ambiguous_when_baseline_only_has_repeats() -> None:
    source = SOURCES[("G06", "ambiguous-repeated-event")]["traces"]
    baseline = graphs("G06")[0]
    candidate = project_trace([EventEnvelope.model_validate_json(canonical_json_bytes(e)) for e in source["candidate"][:1]])
    result = align_graphs(baseline, candidate)
    assert len(result.ambiguous) == 1
    assert result.ambiguous[0].baseline_count == 2
    assert result.ambiguous[0].candidate_count == 1


def test_ambiguous_group_with_absent_candidate_is_not_removed() -> None:
    left, right = graphs("G06")
    original = SOURCES[("G06", "ambiguous-repeated-event")]["traces"]["candidate"]
    base_events = [EventEnvelope.model_validate_json(canonical_json_bytes(e)) for e in original]
    altered = [event for event in base_events if event.component_id != "same-model"]
    if not altered:
        # Un grafo válido necesita al menos un evento; se usa uno de otra familia.
        altered = [EventEnvelope.model_validate_json(canonical_json_bytes(x)) for x in
                   SOURCES[("G03", "payload-change")]["traces"]["candidate"]]
    right = project_trace(altered)
    result = align_graphs(left, right)
    repeated = next(g for g in result.ambiguous if g.key == ("event", "model", "same-model", "model.invoked"))
    assert repeated.baseline_count == 2 and repeated.candidate_count == 0
    assert repeated.key not in {n.key for n in result.baseline_only}


@pytest.mark.parametrize("field,code", [
    ("case_id", "case_mismatch"),
    ("app_id", "app_mismatch"),
    ("repeat_index", "repeat_mismatch"),
])
def test_rejects_incompatible_graphs(field: str, code: str) -> None:
    left, right = graphs("G02")
    payload = right.model_dump(mode="json", exclude={"graph_hash"})
    value: Any = "other-case" if field == "case_id" else "a2_rag" if field == "app_id" else 1
    payload[field] = value
    payload["graph_hash"] = sha256_hex(canonical_json_bytes(payload))
    incompatible = ProvenanceGraph.model_validate_json(canonical_json_bytes(payload))
    with pytest.raises(GraphComparisonError) as error:
        align_graphs(left, incompatible)
    assert error.value.code == code


@pytest.mark.parametrize("case,code", [("case-mismatch", "case_mismatch"),
                                       ("app-mismatch", "app_mismatch")])
def test_g08_comparison_failures_match_frozen_error_codes(case: str, code: str) -> None:
    source = SOURCES[("G08", case)]["traces"]
    before = project_trace([EventEnvelope.model_validate_json(canonical_json_bytes(e)) for e in source["baseline"]])
    after = project_trace([EventEnvelope.model_validate_json(canonical_json_bytes(e)) for e in source["candidate"]])
    with pytest.raises(GraphComparisonError) as error:
        align_graphs(before, after)
    assert error.value.code == code


def test_rejects_schema_valid_but_cyclic_graph() -> None:
    altered = SOURCES[("G07", "explicit-dag-cycle")]["graph_to_validate"]
    graph = ProvenanceGraph.model_validate_json(canonical_json_bytes(altered))
    with pytest.raises(AlignmentError, match="estructural"):
        align_graphs(graph, graphs("G04")[0])


def test_rejects_forged_graph_hash() -> None:
    baseline, candidate = graphs("G02")
    forged = baseline.model_copy(update={"graph_hash": "0" * 64})
    with pytest.raises(AlignmentError, match="estructural"):
        align_graphs(forged, candidate)


def test_rejects_other_input_types() -> None:
    _, candidate = graphs("G02")
    for wrong in ({}, 0, None):
        with pytest.raises(AlignmentError):
            align_graphs(wrong, candidate)  # type: ignore[arg-type]


def test_semantic_key_uses_only_frozen_fields() -> None:
    baseline, _ = graphs("G02")
    for node in baseline.nodes:
        key = semantic_key(node)
        assert isinstance(key, tuple)
        assert key[0] in {"component", "event", "payload"}
        assert len(key) in {2, 3, 4}
        serialized = canonical_json_bytes(list(key))
        assert baseline.run_id.encode() not in serialized


def test_semantic_key_does_not_accept_arbitrary_models() -> None:
    with pytest.raises(AlignmentError):
        semantic_key(object())  # type: ignore[arg-type]


def test_output_models_are_immutable_snapshots() -> None:
    left, right = graphs("G02")
    result = align_graphs(left, right)
    assert isinstance(result.pairs[0], AlignedNode)
    with pytest.raises(FrozenInstanceError):
        result.baseline_run_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.pairs[0].key = ("forged",)  # type: ignore[misc]
    assert not result.ambiguous


def test_exposes_unmatched_and_ambiguous_records_separately() -> None:
    before, after = graphs("G03")
    comparison = align_graphs(before, after)
    assert isinstance(comparison.baseline_only[0], UnmatchedNode)
    assert isinstance(comparison.candidate_only[0], UnmatchedNode)
    left, right = graphs("G06")
    assert isinstance(align_graphs(left, right).ambiguous[0], AmbiguousGroup)


def test_alignment_deterministic_in_multiple_calls() -> None:
    for case in ("G02", "G03", "G04", "G05", "G06"):
        left, right = graphs(case)
        first = align_graphs(left, right)
        assert first == align_graphs(left, right)
        assert first == align_graphs(left, right)


def test_inputs_are_not_mutated_by_alignment() -> None:
    left, right = graphs("G03")
    before = canonical_json_bytes(left)
    after = canonical_json_bytes(right)
    align_graphs(left, right)
    assert canonical_json_bytes(left) == before
    assert canonical_json_bytes(right) == after


def test_different_system_versions_and_conditions_do_not_block_pairing() -> None:
    left, right = graphs("G02")
    assert left.condition_id != right.condition_id
    assert left.system_version_id != right.system_version_id
    assert len(align_graphs(left, right).pairs) == 3


def test_alignment_does_not_compute_delta_or_import_legacy() -> None:
    import inspect
    import provregress.provenance.alignment as module
    source = inspect.getsource(module)
    assert "import llmtestlab" not in source
    assert "from llmtestlab" not in source
    assert not hasattr(module, "diff_graphs")
    assert not hasattr(module, "DeltaG")

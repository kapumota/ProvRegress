"""Gate R0.8-I4: DeltaG tipado, hashes reproducibles y oráculos congelados."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from provregress.provenance import diff_graphs
from provregress.provenance.alignment import GraphComparisonError, align_graphs
from provregress.provenance.diff import GraphDiffError
from provregress.provenance.projector import project_trace
from provregress.schema.events import EventEnvelope
from provregress.schema.graph import DeltaG, EventNode, ProvenanceGraph
from provregress.storage.hashing import canonical_json_bytes, sha256_hex

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/provenance/r0_8"
OUTPUTS = json.loads((FIXTURES / "expected.json").read_bytes())
INPUTS = json.loads((FIXTURES / "inputs.json").read_bytes())
GOLDEN = {(item["id"], item["variant"]): item for item in OUTPUTS["cases"]}
SOURCES = {(item["id"], item["variant"]): item for item in INPUTS["cases"]}
PAIRED = [case for case in GOLDEN.values() if case.get("delta") is not None]


def graphs(scenario: str) -> tuple[ProvenanceGraph, ProvenanceGraph]:
    """Carga grafos precomputados, sin llamar al proyector de producción."""
    item = next(item for item in PAIRED if item["id"] == scenario)
    return tuple(ProvenanceGraph.model_validate_json(canonical_json_bytes(item["graphs"][side]))
                 for side in ("baseline", "candidate"))  # type: ignore[return-value]


def rehashed(graph: ProvenanceGraph, *, changes: dict[str, Any]) -> ProvenanceGraph:
    """Materializa un grafo estructuralmente válido con cambios controlados."""
    content = graph.model_dump(mode="json", exclude={"graph_hash"})
    for key, value in changes.items():
        content[key] = value
    content["graph_hash"] = sha256_hex(canonical_json_bytes(content))
    return ProvenanceGraph.model_validate_json(canonical_json_bytes(content))


def altered_event(graph: ProvenanceGraph, **updates: Any) -> ProvenanceGraph:
    """Modifica solo observables sin adulterar nodos/IDs semánticos."""
    content = graph.model_dump(mode="json", exclude={"graph_hash"})
    events = [node for node in content["nodes"] if node["node_kind"] == "event"]
    assert len(events) == 1
    events[0].update(updates)
    content["graph_hash"] = sha256_hex(canonical_json_bytes(content))
    return ProvenanceGraph.model_validate_json(canonical_json_bytes(content))


@pytest.mark.parametrize("scenario", [item["id"] for item in PAIRED])
def test_all_frozen_deltas_are_exact_including_hash(scenario: str) -> None:
    """El resultado es byte a byte el oráculo, no solo un conteo agregado."""
    left, right = graphs(scenario)
    calculated = diff_graphs(left, right)
    expected = next(item["delta"] for item in PAIRED if item["id"] == scenario)
    assert isinstance(calculated, DeltaG)
    assert calculated.model_dump(mode="json") == expected
    assert canonical_json_bytes(calculated) == canonical_json_bytes(expected)
    assert calculated.delta_hash == sha256_hex(canonical_json_bytes(
        calculated.model_dump(mode="json", exclude={"delta_hash"})
    ))


@pytest.mark.parametrize("scenario", [item["id"] for item in PAIRED])
def test_frozen_deltas_are_idempotent(scenario: str) -> None:
    left, right = graphs(scenario)
    first = canonical_json_bytes(diff_graphs(left, right))
    assert all(canonical_json_bytes(diff_graphs(left, right)) == first for _ in range(3))


def test_g02_ignores_different_runs_clocks_and_versions() -> None:
    left, right = graphs("G02")
    assert left.run_id != right.run_id
    assert left.system_version_id != right.system_version_id
    assert left.condition_id != right.condition_id
    result = diff_graphs(left, right)
    assert len(result.node_unchanged) == 3
    assert not (result.node_added or result.node_removed or result.node_changed)
    assert not (result.edge_added or result.edge_removed or result.edge_ambiguous)


def test_g03_marks_payload_and_produces_edge_changes() -> None:
    result = diff_graphs(*graphs("G03"))
    assert [item.key for item in result.node_changed] == [["event", "model", "llm", "model.returned"]]
    assert [item.changed_fields for item in result.node_changed] == [["payload_hash"]]
    assert len(result.node_added) == len(result.node_removed) == 1
    assert result.node_added[0][0] == result.node_removed[0][0] == "payload"
    assert [edge.edge_kind.value for edge in result.edge_added] == ["produces"]
    assert [edge.edge_kind.value for edge in result.edge_removed] == ["produces"]


def test_g04_only_explicit_parent_is_added() -> None:
    result = diff_graphs(*graphs("G04"))
    assert not (result.node_added or result.node_removed or result.node_changed)
    assert len(result.edge_added) == 1
    assert result.edge_added[0].edge_kind.value == "observed_parent"
    assert not result.edge_removed


def test_g05_reordering_does_not_change_topology() -> None:
    result = diff_graphs(*graphs("G05"))
    assert not (result.node_added or result.node_removed or result.node_changed)
    assert not (result.edge_added or result.edge_removed or result.edge_ambiguous)
    assert result.node_unchanged


def test_g06_repetitions_do_not_invent_pairs() -> None:
    result = diff_graphs(*graphs("G06"))
    assert len(result.node_ambiguous) == 1
    group = result.node_ambiguous[0]
    assert group.key == ["event", "model", "same-model", "model.invoked"]
    assert (group.baseline_count, group.candidate_count) == (2, 2)
    assert len(result.edge_ambiguous) == 4
    assert {edge.side for edge in result.edge_ambiguous} == {"baseline", "candidate"}
    assert all(edge.count == 2 for edge in result.edge_ambiguous)
    assert not (result.node_added or result.node_removed or result.node_changed)
    assert not (result.edge_added or result.edge_removed)


@pytest.mark.parametrize("field,value,expected", [
    ("attributes", {"ok": False}, ["attributes"]),
    ("error", {"category": "runtime", "message": "Error temporal.",
               "retryable": False, "details": {}}, ["error"]),
])
def test_unique_event_changes_only_observed_fields(field: str, value: Any,
                                                    expected: list[str]) -> None:
    baseline, candidate = graphs("G02")
    candidate = altered_event(candidate, **{field: value})
    result = diff_graphs(baseline, candidate)
    assert len(result.node_changed) == 1
    assert result.node_changed[0].changed_fields == expected
    assert not (result.edge_added or result.edge_removed)


def test_unique_event_reports_multiple_changes_in_canonical_order() -> None:
    baseline, candidate = graphs("G02")
    candidate = altered_event(
        candidate, attributes={"ok": False},
        error={"category": "runtime", "message": "Error temporal.",
               "retryable": True, "details": {"attempt": 1}},
    )
    result = diff_graphs(baseline, candidate)
    assert result.node_changed[0].changed_fields == ["attributes", "error"]
    assert not (result.edge_added or result.edge_removed)


def test_timestamp_sequence_and_event_id_not_observable_changes() -> None:
    baseline, candidate = graphs("G02")
    assert next(n.event_id for n in baseline.nodes if isinstance(n, EventNode)) != (
        next(n.event_id for n in candidate.nodes if isinstance(n, EventNode))
    )
    altered = altered_event(candidate, timestamp_utc="2026-11-01T08:00:00Z")
    result = diff_graphs(baseline, altered)
    assert not result.node_changed
    assert len(result.node_unchanged) == 3


def test_extra_comparison_metadata_alone_does_not_create_change() -> None:
    baseline, candidate = graphs("G02")
    rebuilt = rehashed(candidate, changes={"system_version_id": "sys-unrelated",
                                            "condition_id": "other-condition"})
    assert diff_graphs(baseline, candidate).model_dump(mode="json") == (
        diff_graphs(baseline, rebuilt).model_dump(mode="json")
    )


@pytest.mark.parametrize("field,value,code", [
    ("case_id", "another-pilot", "case_mismatch"),
    ("app_id", "a2_rag", "app_mismatch"),
    ("repeat_index", 2, "repeat_mismatch"),
])
def test_fail_closed_when_graphs_are_not_comparable(field: str, value: Any,
                                                      code: str) -> None:
    baseline, candidate = graphs("G02")
    candidate = rehashed(candidate, changes={field: value})
    with pytest.raises(GraphComparisonError) as error:
        diff_graphs(baseline, candidate)
    assert error.value.code == code


@pytest.mark.parametrize("variant,code", [
    ("case-mismatch", "case_mismatch"),
    ("app-mismatch", "app_mismatch"),
])
def test_g08_rejects_incompatible_frozen_inputs(variant: str, code: str) -> None:
    sources = SOURCES[("G08", variant)]["traces"]
    before = project_trace([EventEnvelope.model_validate_json(canonical_json_bytes(event))
                            for event in sources["baseline"]])
    after = project_trace([EventEnvelope.model_validate_json(canonical_json_bytes(event))
                           for event in sources["candidate"]])
    with pytest.raises(GraphComparisonError) as error:
        diff_graphs(before, after)
    assert error.value.code == code


@pytest.mark.parametrize("invalid", [None, {}, object(), "no es grafo"])
def test_invalid_graph_arguments_are_rejected(invalid: Any) -> None:
    baseline, candidate = graphs("G02")
    with pytest.raises(GraphDiffError):
        diff_graphs(invalid, candidate)
    with pytest.raises(GraphDiffError):
        diff_graphs(baseline, invalid)


def test_rejects_forged_graph_digest_without_returning_delta() -> None:
    baseline, candidate = graphs("G02")
    forged = baseline.model_copy(update={"graph_hash": "a" * 64})
    with pytest.raises(GraphDiffError, match="estructurales"):
        diff_graphs(forged, candidate)


def test_g07_rejects_cyclic_graph_even_if_hash_is_valid() -> None:
    payload = SOURCES[("G07", "explicit-dag-cycle")]["graph_to_validate"]
    forged = ProvenanceGraph.model_validate_json(canonical_json_bytes(payload))
    with pytest.raises(GraphDiffError, match="estructurales"):
        diff_graphs(forged, graphs("G04")[0])


def test_input_data_is_not_mutated() -> None:
    before, after = graphs("G03")
    encoded_before = canonical_json_bytes(before)
    encoded_after = canonical_json_bytes(after)
    diff_graphs(before, after)
    assert canonical_json_bytes(before) == encoded_before
    assert canonical_json_bytes(after) == encoded_after


def test_output_is_compatible_with_strict_deltag_schema() -> None:
    calculated = diff_graphs(*graphs("G06"))
    restored = DeltaG.model_validate_json(canonical_json_bytes(calculated))
    assert restored == calculated
    with pytest.raises(ValidationError):
        DeltaG.model_validate_json(canonical_json_bytes(
            calculated.model_dump(mode="json") | {"privileged": 1}))


def test_public_api_is_exported_and_no_legacy_or_mutation_import() -> None:
    import provregress.provenance.diff as module
    source = inspect.getsource(module)
    assert callable(diff_graphs)
    assert "import llmtestlab" not in source
    assert "from llmtestlab" not in source
    assert "MutationManifest" not in source


def test_frozen_fixtures_unchanged_and_checksums() -> None:
    from hashlib import sha256
    rows = (FIXTURES / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    for row in rows:
        checksum, name = row.split("  ")
        assert sha256((FIXTURES / name).read_bytes()).hexdigest() == checksum


def test_alignment_is_still_usable_as_independent_gate() -> None:
    for item in PAIRED:
        baseline, candidate = graphs(item["id"])
        assert align_graphs(baseline, candidate).baseline_run_id == baseline.run_id
        assert diff_graphs(baseline, candidate).baseline_run_id == baseline.run_id

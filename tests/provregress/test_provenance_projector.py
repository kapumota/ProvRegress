"""R0.8-I2: proyección P2, DAG independiente e integridad de payloads."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.provenance.projector import (
    GraphValidationError,
    ProjectionError,
    project_trace,
    validate_graph,
)
from provregress.schema.common import AppId, ArtifactRef, ComponentType, HashRef
from provregress.schema.events import EventEnvelope, EventType
from provregress.schema.graph import ComponentNode, EventNode, PayloadNode, ProvenanceGraph
from provregress.storage.artifacts import ArtifactIntegrityError, ArtifactStore, ArtifactStoreError
from provregress.storage.hashing import canonical_json_bytes, sha256_hex


ROOT = Path(__file__).resolve().parents[1] / "fixtures/provenance/r0_8"
INPUTS = json.loads((ROOT / "inputs.json").read_bytes())
EXPECTED = json.loads((ROOT / "expected.json").read_bytes())
CASES = {(case["id"], case["variant"]): case for case in INPUTS["cases"]}
RESULTS = {(case["id"], case["variant"]): case for case in EXPECTED["cases"]}
POSITIVES = [(case_id, variant, role) for (case_id, variant), result in RESULTS.items()
             if "graphs" in result for role in result["graphs"]]


def _events(case_id: str, variant: str, role: str = "baseline") -> list[EventEnvelope]:
    """Lee entrada golden como objetos R0.7 ya validados."""
    return [EventEnvelope.model_validate_json(canonical_json_bytes(event)) for event in
            CASES[(case_id, variant)]["traces"][role]]


def _dummy_event(**changes: object) -> EventEnvelope:
    """Evento sintético para tests de invariantes no cubiertos por F2."""
    payload: dict[str, object] = {
        "run_id": "run-test", "event_id": "evt-0", "sequence": 0,
        "timestamp_utc": datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc),
        "app_id": AppId.A1, "system_version_id": "v1",
        "case_id": "pilot-a", "condition_id": "baseline", "repeat_index": 0,
        "event_type": EventType.MODEL_RETURNED,
        "component_type": ComponentType.MODEL, "component_id": "llm",
        "parent_event_ids": [],
        "payload_hash": HashRef(algorithm="sha256", value=sha256_hex(b"payload")),
        "payload_ref": None, "attributes": {}, "error": None,
    }
    payload.update(changes)
    return EventEnvelope.model_validate(payload)


@pytest.mark.parametrize("key", POSITIVES, ids=lambda item: "-".join(item))
def test_project_trace_matches_frozen_graph_byte_for_byte(key: tuple[str, str, str]) -> None:
    """Ningún hash ni oráculo F2 se recalcula para acomodar el proyector."""
    case_id, variant, role = key
    graph = project_trace(_events(case_id, variant, role))
    frozen = RESULTS[(case_id, variant)]["graphs"][role]
    assert isinstance(graph, ProvenanceGraph)
    assert graph.model_dump(mode="json") == frozen
    assert canonical_json_bytes(graph) == canonical_json_bytes(frozen)
    assert graph.graph_hash == frozen["graph_hash"]
    assert graph.trace_hash is None
    validate_graph(graph)
    validate_graph(frozen)


def test_reprojection_is_identical_and_input_is_unchanged() -> None:
    events = _events("G01", "reproject-and-deduplicate")
    originals = [canonical_json_bytes(event) for event in events]
    first, second = project_trace(events), project_trace(iter(events))
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert [canonical_json_bytes(event) for event in events] == originals
    assert sum(isinstance(node, PayloadNode) for node in first.nodes) == 1
    assert sum(isinstance(node, EventNode) for node in first.nodes) == 2


@pytest.mark.parametrize("variant", ["future-parent", "sequence-gap", "cycle-via-future-parent"])
def test_project_trace_rejects_invalid_history(variant: str) -> None:
    events = _events("G07", variant)
    with pytest.raises(ProjectionError, match="R0.7"):
        project_trace(events)


@pytest.mark.parametrize("variant", ["reserved-attribute", "nested-reserved-attribute"])
def test_schema_rejects_reserved_fields_before_projection(variant: str) -> None:
    source = CASES[("G09", variant)]["traces"]["baseline"][0]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(canonical_json_bytes(source))


def test_validate_graph_rejects_frozen_explicit_cycle() -> None:
    graph = CASES[("G07", "explicit-dag-cycle")]["graph_to_validate"]
    with pytest.raises(GraphValidationError, match="ciclo"):
        validate_graph(graph)
    with pytest.raises(GraphValidationError, match="ciclo"):
        validate_graph(ProvenanceGraph.model_validate_json(canonical_json_bytes(graph)))


def test_project_trace_does_not_infer_parent_from_sequence() -> None:
    graph = project_trace(_events("G05", "independent-reorder"))
    assert not any(edge.edge_kind.value == "observed_parent" for edge in graph.edges)


def test_project_trace_rejects_empty_and_non_event_input() -> None:
    with pytest.raises(ProjectionError):
        project_trace([])
    with pytest.raises(ProjectionError):
        project_trace([{"event_id": "ev-0"}])  # type: ignore[list-item]


def test_project_trace_rejects_forged_event() -> None:
    corrupted = _dummy_event().model_copy(update={"attributes": {"mutation_id": "secret"}})
    with pytest.raises(ProjectionError):
        project_trace([corrupted])


def test_project_trace_rejects_mixed_run_identities() -> None:
    first = _dummy_event()
    second = _dummy_event(event_id="evt-1", sequence=1, run_id="other-run")
    with pytest.raises(ProjectionError):
        project_trace([first, second])


def test_project_trace_rejects_non_artifact_store() -> None:
    with pytest.raises(ProjectionError, match="ArtifactStore"):
        project_trace([_dummy_event()], artifact_store=object())  # type: ignore[arg-type]


def test_project_trace_validates_real_artifact_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.put_bytes(b"payload", media_type="text/plain")
    event = _dummy_event(payload_hash=ref.hash, payload_ref=ref)
    result = project_trace([event], artifact_store=store)
    assert result.trace_hash is None
    assert store.get_bytes(ref) == b"payload"
    target = store.root / ref.relative_path
    target.write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError):
        project_trace([event], artifact_store=store)
    # Sin almacén, únicamente se valida la declaración, no los bytes.
    assert project_trace([event]).graph_hash == result.graph_hash


def test_project_trace_rejects_missing_stored_artifact(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    digest = sha256_hex(b"payload")
    ref = ArtifactRef(
        hash=HashRef(algorithm="sha256", value=digest),
        relative_path=f"sha256/{digest[:2]}/{digest}",
        size_bytes=7,
    )
    event = _dummy_event(payload_hash=ref.hash, payload_ref=ref)
    with pytest.raises(FileNotFoundError):
        project_trace([event], artifact_store=store)


def test_project_trace_rejects_incompatible_references_for_shared_digest() -> None:
    events = _events("G01", "reproject-and-deduplicate")
    digest = events[0].payload_hash.value
    ref = ArtifactRef(
        hash=events[0].payload_hash,
        relative_path=f"sha256/{digest[:2]}/{digest}",
        size_bytes=5,
    )
    corrupted = EventEnvelope.model_validate(
        events[1].model_dump(mode="python") | {"payload_ref": ref}
    )
    with pytest.raises(ProjectionError, match="incompatibles"):
        project_trace([events[0], corrupted])


def test_project_trace_allows_equal_references_for_shared_digest() -> None:
    events = _events("G01", "reproject-and-deduplicate")
    digest = events[0].payload_hash.value
    ref = ArtifactRef(
        hash=events[0].payload_hash,
        relative_path=f"sha256/{digest[:2]}/{digest}",
        size_bytes=5,
    )
    enriched = [EventEnvelope.model_validate(
        e.model_dump(mode="python") | {"payload_ref": ref}
    ) for e in events]
    graph = project_trace(enriched)
    payload = next(node for node in graph.nodes if isinstance(node, PayloadNode))
    assert payload.payload_ref == ref


def test_validate_graph_rejects_forged_hash_even_if_model_copy_skips_validation() -> None:
    graph = project_trace([_dummy_event()])
    forged = graph.model_copy(update={"graph_hash": "0" * 64})
    with pytest.raises(GraphValidationError):
        validate_graph(forged)


def test_validate_graph_rejects_missing_endpoint() -> None:
    graph = project_trace([_dummy_event()]).model_dump(mode="json")
    graph["nodes"] = [node for node in graph["nodes"] if node["node_kind"] != "component"]
    graph["graph_hash"] = sha256_hex(canonical_json_bytes({k: v for k, v in graph.items() if k != "graph_hash"}))
    with pytest.raises(GraphValidationError, match="inexistente"):
        validate_graph(graph)


def test_validate_graph_rejects_wrong_orientation() -> None:
    graph = project_trace([_dummy_event()]).model_dump(mode="json")
    edge = next(x for x in graph["edges"] if x["edge_kind"] == "emits")
    edge["source_node_id"], edge["target_node_id"] = edge["target_node_id"], edge["source_node_id"]
    edge["edge_id"] = sha256_hex(canonical_json_bytes([
        "r0.8.edge.v1", edge["edge_kind"], edge["source_node_id"], edge["target_node_id"]
    ]))
    graph["edges"].sort(key=lambda x: x["edge_id"])
    graph["graph_hash"] = sha256_hex(canonical_json_bytes({k: v for k, v in graph.items() if k != "graph_hash"}))
    with pytest.raises(GraphValidationError, match="orientación"):
        validate_graph(graph)


def test_validate_graph_rejects_missing_required_emits_edge() -> None:
    graph = project_trace([_dummy_event()]).model_dump(mode="json")
    graph["edges"] = [x for x in graph["edges"] if x["edge_kind"] != "emits"]
    graph["graph_hash"] = sha256_hex(canonical_json_bytes({k: v for k, v in graph.items() if k != "graph_hash"}))
    with pytest.raises(GraphValidationError):
        validate_graph(graph)


def test_validate_graph_rejects_wrong_payload_connection() -> None:
    graph = project_trace([_dummy_event(), _dummy_event(
        event_id="evt-1", sequence=1, payload_hash=HashRef(
            algorithm="sha256", value=sha256_hex(b"another")),
    )]).model_dump(mode="json")
    edge = next(x for x in graph["edges"] if x["edge_kind"] == "produces")
    payload_nodes = [x["node_id"] for x in graph["nodes"] if x["node_kind"] == "payload"]
    edge["target_node_id"] = next(n for n in payload_nodes if n != edge["target_node_id"])
    edge["edge_id"] = sha256_hex(canonical_json_bytes([
        "r0.8.edge.v1", edge["edge_kind"], edge["source_node_id"], edge["target_node_id"]
    ]))
    graph["edges"].sort(key=lambda x: x["edge_id"])
    graph["graph_hash"] = sha256_hex(canonical_json_bytes({k: v for k, v in graph.items() if k != "graph_hash"}))
    with pytest.raises(GraphValidationError, match="digest"):
        validate_graph(graph)


def test_validate_graph_rejects_non_contiguous_sequence() -> None:
    graph = project_trace([_dummy_event()]).model_dump(mode="json")
    event = next(x for x in graph["nodes"] if x["node_kind"] == "event")
    event["sequence"] = 2
    graph["graph_hash"] = sha256_hex(canonical_json_bytes({k: v for k, v in graph.items() if k != "graph_hash"}))
    with pytest.raises(GraphValidationError, match="contigua"):
        validate_graph(graph)


def test_public_module_has_no_alignment_or_legacy_imports() -> None:
    import inspect
    import provregress.provenance.projector as module
    source = inspect.getsource(module)
    assert "llmtestlab" not in source
    assert "MutationManifest" not in source
    assert not hasattr(module, "align_graphs")
    assert not hasattr(module, "diff_graphs")

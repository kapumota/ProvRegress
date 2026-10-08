"""R0.8-I1: schemas P2/P3 conformes con el corpus golden congelado."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from provregress.schema.graph import (
    ComponentNode, DeltaG, EdgeAmbiguous, EdgeChange, EdgeKind,
    EventNode, GraphEdge, GraphNode, NodeAmbiguous, NodeChanged,
    NodeKind, PayloadNode, ProvenanceGraph,
)
from provregress.storage.hashing import canonical_json_bytes, sha256_hex


ROOT = Path(__file__).resolve().parents[1] / "fixtures/provenance/r0_8"
EXPECTED = json.loads((ROOT / "expected.json").read_bytes())
GRAPHS = [g for item in EXPECTED["cases"] for g in item.get("graphs", {}).values()]
DELTAS = [item["delta"] for item in EXPECTED["cases"] if item.get("delta")]


def changed(original: dict, **updates: object) -> dict:
    """Recalcula el hash solo para aislar la condición que se está probando."""
    payload = original | updates
    name = "graph_hash" if "graph_hash" in original else "delta_hash"
    payload[name] = sha256_hex(canonical_json_bytes({k: v for k, v in payload.items() if k != name}))
    return payload


def rehash_node(graph: dict, *, nodes: list[dict] | None = None,
                edges: list[dict] | None = None) -> dict:
    return changed(graph, nodes=graph["nodes"] if nodes is None else nodes,
                   edges=graph["edges"] if edges is None else edges)


@pytest.mark.parametrize("graph", GRAPHS, ids=lambda x: x["run_id"])
def test_every_frozen_graph_roundtrips_exactly(graph: dict) -> None:
    instance = ProvenanceGraph.model_validate_json(canonical_json_bytes(graph))
    assert instance.model_dump(mode="json") == graph
    assert ProvenanceGraph.model_validate_json(instance.model_dump_json()) == instance
    assert canonical_json_bytes(instance) == canonical_json_bytes(graph)


@pytest.mark.parametrize("delta", DELTAS, ids=lambda x: x["baseline_run_id"])
def test_every_frozen_delta_roundtrips_exactly(delta: dict) -> None:
    instance = DeltaG.model_validate_json(canonical_json_bytes(delta))
    assert instance.model_dump(mode="json") == delta
    assert DeltaG.model_validate_json(instance.model_dump_json()) == instance
    assert canonical_json_bytes(instance) == canonical_json_bytes(delta)


def test_closed_vocabulary_and_explicit_fields() -> None:
    assert {v.value for v in NodeKind} == {"component", "event", "payload"}
    assert {v.value for v in EdgeKind} == {"emits", "produces", "observed_parent"}
    for model in [ComponentNode, EventNode, PayloadNode, GraphEdge,
                  ProvenanceGraph, NodeChanged, NodeAmbiguous,
                  EdgeChange, EdgeAmbiguous, DeltaG]:
        assert model.model_json_schema()["additionalProperties"] is False
    assert set(ProvenanceGraph.model_fields) == {
        "schema_version", "run_id", "app_id", "case_id", "condition_id",
        "repeat_index", "system_version_id", "trace_hash", "nodes", "edges", "graph_hash",
    }
    assert set(DeltaG.model_fields) == {
        "schema_version", "baseline_run_id", "candidate_run_id", "node_added",
        "node_removed", "node_unchanged", "node_changed", "node_ambiguous",
        "edge_added", "edge_removed", "edge_ambiguous", "delta_hash",
    }


def test_graph_node_is_a_discriminated_union() -> None:
    adapter = TypeAdapter(GraphNode)
    nodes = GRAPHS[0]["nodes"]
    classes = {"component": ComponentNode, "event": EventNode, "payload": PayloadNode}
    for raw in nodes:
        result = adapter.validate_json(canonical_json_bytes(raw))
        assert isinstance(result, classes[raw["node_kind"]])
        assert result.model_dump(mode="json") == raw
    with pytest.raises(ValidationError):
        adapter.validate_python({"node_kind": "root", "node_id": "a" * 64})


@pytest.mark.parametrize("bad", ["bad", "A" * 64, "a" * 63, None, 2])
def test_node_id_rejects_invalid_digests(bad: object) -> None:
    raw = next(n for n in GRAPHS[0]["nodes"] if n["node_kind"] == "component")
    with pytest.raises(ValidationError):
        TypeAdapter(GraphNode).validate_python(raw | {"node_id": bad})


def test_graph_rejects_miscomputed_node_identity_even_if_graph_rehashed() -> None:
    graph = GRAPHS[0]
    nodes = [dict(node) for node in graph["nodes"]]
    nodes[0]["node_id"] = "b" * 64
    nodes.sort(key=lambda x: x["node_id"])
    with pytest.raises(ValidationError, match="ID de nodo"):
        ProvenanceGraph.model_validate_json(canonical_json_bytes(rehash_node(graph, nodes=nodes)))


def test_graph_rejects_miscomputed_edge_identity() -> None:
    graph = GRAPHS[0]
    edges = [dict(e) for e in graph["edges"]]
    edges[0]["edge_id"] = "0" * 64
    edges.sort(key=lambda e: e["edge_id"])
    with pytest.raises(ValidationError, match="ID de arista"):
        ProvenanceGraph.model_validate_json(canonical_json_bytes(rehash_node(graph, edges=edges)))


@pytest.mark.parametrize("field", ["nodes", "edges"])
def test_graph_rejects_unsorted_or_repeated_elements(field: str) -> None:
    graph = GRAPHS[0]
    elements = graph[field]
    assert len(elements) >= 2
    for values in [list(reversed(elements)), [*elements, elements[0]]]:
        with pytest.raises(ValidationError):
            ProvenanceGraph.model_validate_json(canonical_json_bytes(changed(graph, **{field: values})))


def test_graph_rejects_tampered_hash_and_extra_fields() -> None:
    graph = GRAPHS[0]
    for broken in [graph | {"graph_hash": "a" * 64}, graph | {"extra": 3}]:
        with pytest.raises(ValidationError):
            ProvenanceGraph.model_validate_json(canonical_json_bytes(broken))


def test_graph_schema_does_not_implement_dag_validation_yet() -> None:
    inputs = json.loads((ROOT / "inputs.json").read_bytes())["cases"]
    forged = next(x["graph_to_validate"] for x in inputs
                  if x["variant"] == "explicit-dag-cycle")
    assert ProvenanceGraph.model_validate_json(canonical_json_bytes(forged)).graph_hash == forged["graph_hash"]


@pytest.mark.parametrize("bad", [-1, True, "1", 1.5])
def test_graph_counters_are_strict(bad: object) -> None:
    with pytest.raises(ValidationError):
        ProvenanceGraph.model_validate_json(canonical_json_bytes(
            changed(GRAPHS[0], repeat_index=bad)))


def test_event_node_rejects_naive_datetime_and_reserved_attributes() -> None:
    node = next(n for n in GRAPHS[0]["nodes"] if n["node_kind"] == "event")
    adapter = TypeAdapter(GraphNode)
    with pytest.raises(ValidationError):
        adapter.validate_json(canonical_json_bytes(node | {"timestamp_utc": "2026-10-08T17:00:00"}))
    with pytest.raises(ValidationError):
        adapter.validate_json(canonical_json_bytes(node | {"attributes": {"nested": [{"severity": "high"}]}}))
    with pytest.raises(ValidationError):
        adapter.validate_python(node | {"attributes": {"score": float("nan")},
                                        "timestamp_utc": datetime(2026, 10, 8, 17, tzinfo=timezone.utc)})


def test_payload_node_rejects_wrong_artifact_digest() -> None:
    node = next(n for g in GRAPHS for n in g["nodes"] if n["node_kind"] == "payload")
    fake = dict(node)
    fake["payload_ref"] = {
        "hash": {"algorithm": "sha256", "value": "a" * 64},
        "relative_path": "sha256/aa/" + "a" * 64,
        "size_bytes": 8,
    }
    if fake["payload_hash"]["value"] == "a" * 64:
        fake["payload_ref"]["hash"]["value"] = "b" * 64
    with pytest.raises(ValidationError, match="referencia"):
        TypeAdapter(GraphNode).validate_json(canonical_json_bytes(fake))


def test_delta_rejects_bad_hash_and_undeclared_fields() -> None:
    delta = DELTAS[0]
    for broken in [delta | {"delta_hash": "a" * 64}, delta | {"unexpected": 1}]:
        with pytest.raises(ValidationError):
            DeltaG.model_validate_json(canonical_json_bytes(broken))


def test_delta_rejects_unordered_entries_with_recomputed_hash() -> None:
    delta = next(d for d in DELTAS if len(d["node_unchanged"]) > 1)
    with pytest.raises(ValidationError, match="node_unchanged"):
        DeltaG.model_validate_json(canonical_json_bytes(changed(
            delta, node_unchanged=list(reversed(delta["node_unchanged"])))))


def test_delta_rejects_duplicate_or_cross_group_keys() -> None:
    delta = DELTAS[0]
    duplicate = changed(delta, node_unchanged=[*delta["node_unchanged"], delta["node_unchanged"][0]])
    with pytest.raises(ValidationError):
        DeltaG.model_validate_json(canonical_json_bytes(duplicate))
    crossing = changed(delta, node_added=[delta["node_unchanged"][0]])
    with pytest.raises(ValidationError, match="dos clases"):
        DeltaG.model_validate_json(canonical_json_bytes(crossing))


def test_delta_rejects_invalid_semantic_keys() -> None:
    delta = DELTAS[0]
    for bad_key in (["event", "model", "x"], ["payload", "ABC"],
                    ["component", "unknown", "id"], ["event", "model", "x", "wrong"]):
        with pytest.raises(ValidationError):
            DeltaG.model_validate_json(canonical_json_bytes(changed(delta, node_added=[bad_key])))


def test_node_changed_only_allows_event_fields_and_sorted_unique_changes() -> None:
    source = {"key": ["event", "model", "llm", "model.returned"],
              "changed_fields": ["payload_hash"]}
    assert NodeChanged.model_validate(source).changed_fields == ["payload_hash"]
    for bad in (
        {"key": ["component", "model", "llm"]},
        {"changed_fields": []},
        {"changed_fields": ["payload_hash", "payload_hash"]},
        {"changed_fields": ["payload_hash", "error"]},
        {"changed_fields": ["event_id"]},
    ):
        with pytest.raises(ValidationError):
            NodeChanged.model_validate(source | bad)


def test_node_ambiguous_requires_repeated_event_key() -> None:
    valid = {"key": ["event", "model", "llm", "model.returned"],
             "baseline_count": 2, "candidate_count": 0}
    assert NodeAmbiguous.model_validate(valid).baseline_count == 2
    for bad in ({"baseline_count": 1}, {"baseline_count": True},
                {"key": ["component", "model", "llm"]}):
        with pytest.raises(ValidationError):
            NodeAmbiguous.model_validate(valid | bad)


def test_edge_change_enforces_semantic_orientation() -> None:
    valid = {"edge_kind": "produces",
             "source_key": ["event", "model", "llm", "model.returned"],
             "target_key": ["payload", "a" * 64]}
    assert EdgeChange.model_validate_json(canonical_json_bytes(valid)).edge_kind == EdgeKind.PRODUCES
    with pytest.raises(ValidationError):
        EdgeChange.model_validate_json(canonical_json_bytes(valid | {"source_key": ["component", "model", "llm"]}))
    with pytest.raises(ValidationError):
        EdgeAmbiguous.model_validate_json(canonical_json_bytes(valid | {"side": "unknown", "count": 2}))
    with pytest.raises(ValidationError):
        EdgeAmbiguous.model_validate_json(canonical_json_bytes(valid | {"side": "baseline", "count": 0}))


def test_graph_extra_fields_on_node_are_rejected() -> None:
    graph = GRAPHS[0]
    nodes = [dict(node) for node in graph["nodes"]]
    nodes[0]["mutation_id"] = "forbidden"
    with pytest.raises(ValidationError):
        ProvenanceGraph.model_validate_json(canonical_json_bytes(rehash_node(graph, nodes=nodes)))


def test_reference_module_has_no_projector_or_legacy_import() -> None:
    import inspect
    import provregress.schema.graph as module
    source = inspect.getsource(module)
    assert "from llmtestlab" not in source
    assert "import llmtestlab" not in source
    assert not hasattr(module, "project_graph")
    assert not hasattr(module, "align_graphs")
    assert not hasattr(module, "diff_graphs")

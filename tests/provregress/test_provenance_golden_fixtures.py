"""Verifica las fixtures congelables de R0.8-F2 sin implementar P2/P3."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from provregress.schema.events import EventEnvelope
from provregress.storage.jsonl import EventLogIntegrityError, validate_event_log


ROOT = Path(__file__).resolve().parents[1] / "fixtures/provenance/r0_8"


def _canonical(value: Any) -> bytes:
    """Oráculo auxiliar de bytes JSON, independiente del futuro proyector."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _data(name: str) -> dict[str, Any]:
    return json.loads((ROOT / name).read_bytes())


INPUTS = _data("inputs.json")
EXPECTED = _data("expected.json")
CASES = {(case["id"], case["variant"]): case for case in INPUTS["cases"]}
RESULTS = {(case["id"], case["variant"]): case for case in EXPECTED["cases"]}


def _node_key(node: dict[str, Any]) -> tuple[str, ...]:
    if node["node_kind"] == "component":
        return ("component", node["component_type"], node["component_id"])
    if node["node_kind"] == "event":
        return (
            "event", node["component_type"], node["component_id"], node["event_type"]
        )
    return ("payload", node["payload_hash"]["value"])


def test_fixture_index_is_complete_and_stable() -> None:
    assert INPUTS["schema_version"] == "r0.8-golden-inputs-v1"
    assert EXPECTED["schema_version"] == "r0.8-golden-expected-v1"
    assert set(CASES) == set(RESULTS)
    assert len(CASES) == len(INPUTS["cases"]) == len(EXPECTED["cases"]) == 15
    assert {case_id for case_id, _ in CASES} == {f"G{i:02d}" for i in range(1, 11)}
    assert all(case["traces"] for case in CASES.values())


def test_fixture_files_match_recorded_sha256_checksums() -> None:
    entries = (ROOT / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    assert len(entries) == 2
    for row, expected_name in zip(entries, ("inputs.json", "expected.json")):
        recorded, filename = row.split("  ", maxsplit=1)
        assert filename == expected_name
        assert recorded == hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        assert (ROOT / filename).read_bytes() == _canonical(_data(filename)) + b"\n"


@pytest.mark.parametrize("fixture_id", list(CASES), ids=lambda x: "-".join(x))
def test_input_validity_matches_explicit_stage(fixture_id: tuple[str, str]) -> None:
    incoming = CASES[fixture_id]
    output = RESULTS[fixture_id]
    stage = output.get("error", {}).get("stage")
    for role, source in incoming["traces"].items():
        if stage == "schema":
            with pytest.raises(ValidationError):
                EventEnvelope.model_validate_json(_canonical(source[0]))
            continue
        events = [EventEnvelope.model_validate_json(_canonical(item)) for item in source]
        assert all(ev.model_dump(mode="json") == raw for ev, raw in zip(events, source))
        if stage == "projection":
            with pytest.raises(EventLogIntegrityError):
                validate_event_log(events)
        else:
            summary = validate_event_log(events)
            assert summary.event_count == len(source)
            assert summary.run_id == source[0]["run_id"]
    if stage == "graph_validation":
        forged = incoming["graph_to_validate"]
        assert forged["graph_hash"] == _digest({k: v for k, v in forged.items() if k != "graph_hash"})
        with pytest.raises(AssertionError, match="ciclo"):
            _assert_dag(forged)
    if stage == "comparison":
        baseline = incoming["traces"]["baseline"][0]
        candidate = incoming["traces"]["candidate"][0]
        field = "case_id" if output["error"]["code"] == "case_mismatch" else "app_id"
        assert baseline[field] != candidate[field]


def _assert_dag(graph: dict[str, Any]) -> None:
    """Comprueba las aristas esperadas sin utilizar algoritmos de producción."""
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    assert len(nodes) == len(graph["nodes"])
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    assert len(edges) == len(graph["edges"])
    assert list(nodes) == sorted(nodes)
    assert list(edges) == sorted(edges)
    in_degree = {node_id: 0 for node_id in nodes}
    next_nodes: dict[str, list[str]] = defaultdict(list)
    allowed = {
        "emits": ("component", "event"),
        "observed_parent": ("event", "event"),
        "produces": ("event", "payload"),
    }
    for edge in graph["edges"]:
        source, target, kind = edge["source_node_id"], edge["target_node_id"], edge["edge_kind"]
        assert source in nodes and target in nodes and source != target
        assert (nodes[source]["node_kind"], nodes[target]["node_kind"]) == allowed[kind]
        assert edge["edge_id"] == _digest(["r0.8.edge.v1", kind, source, target])
        next_nodes[source].append(target)
        in_degree[target] += 1
    queue = deque(node for node in nodes if in_degree[node] == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for child in next_nodes[current]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    assert visited == len(nodes), "La fixture contiene un ciclo no permitido."


def _assert_projection_graph(graph: dict[str, Any], events: list[dict[str, Any]]) -> None:
    sample = events[0]
    assert graph["schema_version"] == "provenance-graph-v1"
    assert graph["trace_hash"] is None  # Solo eventos en memoria; no hay hash JSONL acreditado.
    for name in ("run_id", "app_id", "case_id", "condition_id", "repeat_index", "system_version_id"):
        assert graph[name] == sample[name]
    assert graph["graph_hash"] == _digest({k: v for k, v in graph.items() if k != "graph_hash"})
    _assert_dag(graph)
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    edges = {(edge["edge_kind"], edge["source_node_id"], edge["target_node_id"]) for edge in graph["edges"]}
    assert len([n for n in nodes.values() if n["node_kind"] == "event"]) == len(events)
    expected_edge_count = 2 * len(events) + sum(len(e["parent_event_ids"]) for e in events)
    assert len(edges) == expected_edge_count
    previous: dict[str, str] = {}
    for event in events:
        run = event["run_id"]
        component_id = _digest(["r0.8.node.v1", run, "component", event["component_type"], event["component_id"]])
        event_id = _digest(["r0.8.node.v1", run, "event", event["event_id"]])
        payload_id = _digest(["r0.8.node.v1", run, "payload", event["payload_hash"]["value"]])
        assert nodes[event_id]["event_id"] == event["event_id"]
        assert nodes[event_id]["sequence"] == event["sequence"]
        assert nodes[event_id]["payload_hash"] == event["payload_hash"]
        assert nodes[event_id]["attributes"] == event["attributes"]
        assert nodes[event_id]["error"] == event["error"]
        assert nodes[payload_id]["payload_ref"] == event["payload_ref"]
        assert ("emits", component_id, event_id) in edges
        assert ("produces", event_id, payload_id) in edges
        for parent in event["parent_event_ids"]:
            assert ("observed_parent", previous[parent], event_id) in edges
        previous[event["event_id"]] = event_id


@pytest.mark.parametrize(
    "fixture_id", [key for key in CASES if "graphs" in RESULTS[key]],
    ids=lambda x: "-".join(x),
)
def test_expected_graphs_have_exact_canonical_identities(fixture_id: tuple[str, str]) -> None:
    incoming = CASES[fixture_id]
    outcome = RESULTS[fixture_id]
    assert set(incoming["traces"]) == set(outcome["graphs"])
    for role, graph in outcome["graphs"].items():
        _assert_projection_graph(graph, incoming["traces"][role])
        # Las salidas se pueden reproducir byte a byte sin campos no deterministas.
        assert _canonical(graph) == _canonical(json.loads(_canonical(graph)))


@pytest.mark.parametrize(
    "fixture_id", [key for key in CASES if RESULTS[key].get("delta") is not None],
    ids=lambda x: "-".join(x),
)
def test_expected_deltas_have_exact_hashes_and_disjoint_groups(fixture_id: tuple[str, str]) -> None:
    outcome = RESULTS[fixture_id]
    graphs = outcome["graphs"]
    result = outcome["delta"]
    assert result["schema_version"] == "provenance-delta-v1"
    assert result["baseline_run_id"] == graphs["baseline"]["run_id"]
    assert result["candidate_run_id"] == graphs["candidate"]["run_id"]
    assert result["delta_hash"] == _digest({k: v for k, v in result.items() if k != "delta_hash"})
    names = ("node_added", "node_removed", "node_changed", "node_unchanged", "node_ambiguous")
    groups = [result[name] for name in names]
    keys = []
    for name, group in zip(names, groups):
        assert group == sorted(group, key=_canonical)
        for record in group:
            keys.append(tuple(record["key"] if name in {"node_changed", "node_ambiguous"} else record))
    assert len(keys) == len(set(keys))
    for name in ("edge_added", "edge_removed", "edge_ambiguous"):
        assert result[name] == sorted(result[name], key=_canonical)


@pytest.mark.parametrize(
    "scenario,expected_counts",
    [
        ("G02", (0, 0, 0, 0, 0, 0)),
        ("G03", (1, 1, 1, 0, 1, 1)),
        ("G04", (0, 0, 0, 0, 1, 0)),
        ("G05", (0, 0, 0, 0, 0, 0)),
        ("G06", (0, 0, 0, 1, 0, 0)),
    ],
)
def test_delta_discriminating_counts(
    scenario: str, expected_counts: tuple[int, int, int, int, int, int]
) -> None:
    result = next(x["delta"] for x in EXPECTED["cases"] if x["id"] == scenario)
    keys = ("node_added", "node_removed", "node_changed", "node_ambiguous", "edge_added", "edge_removed")
    assert tuple(len(result[key]) for key in keys) == expected_counts
    if scenario == "G06":
        assert len(result["edge_ambiguous"]) == 4
        assert result["node_ambiguous"][0]["baseline_count"] == 2
        assert result["node_ambiguous"][0]["candidate_count"] == 2
    if scenario == "G04":
        assert result["edge_added"][0]["edge_kind"] == "observed_parent"
    if scenario == "G03":
        assert result["node_changed"][0]["changed_fields"] == ["payload_hash"]


def test_no_byte_verification_is_claimed_without_artifact_store() -> None:
    expected = RESULTS[("G10", "hash-without-artifact-ref")]
    payload_nodes = [node for node in expected["graphs"]["baseline"]["nodes"] if node["node_kind"] == "payload"]
    assert len(payload_nodes) == 1
    assert payload_nodes[0]["payload_ref"] is None
    assert "verified" not in _canonical(expected).decode("utf-8")


def test_g01_reuses_single_payload_node_and_is_reprojectable() -> None:
    result = RESULTS[("G01", "reproject-and-deduplicate")]
    graph = result["graphs"]["baseline"]
    assert result["reprojections"] == 2
    assert sum(n["node_kind"] == "payload" for n in graph["nodes"]) == 1
    assert sum(e["edge_kind"] == "produces" for e in graph["edges"]) == 2
    assert _digest({k: v for k, v in graph.items() if k != "graph_hash"}) == graph["graph_hash"]

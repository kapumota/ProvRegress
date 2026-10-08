"""Auditoría independiente del contrato y los oráculos golden congelados en F3."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/provenance/r0_8"
FROZEN_SHA256 = {
    "research/preregistration/R0.8-P2-P3-contract.md": "bfb953563fdeb259660fdb1a792c9cd6dc512123534d922bdccd45d21ea8e690",
    "research/preregistration/R0.8-P2-P3-golden-fixtures.md": "0b0510da11cc70ad4d8860453a6d1921187a37aedae674877473d7077d37ef06",
    "tests/fixtures/provenance/r0_8/inputs.json": "9d2be2dd2d894e7c4c7508cad0bb6160147dc01d82e3d1090e7903a69d9eb242",
    "tests/fixtures/provenance/r0_8/expected.json": "47fd5e198f25704ee0fbc6363ea3621754397aad9ca72507be4a68752fa4be50",
    "tests/fixtures/provenance/r0_8/SHA256SUMS": "77afade80cad9ea95050cda679b496b45c4abc926d471581f1fff7901362e446",
    "tests/provregress/test_provenance_golden_fixtures.py": "484f7c1f847d9ecff715dffb25eaff540e436ff6a488438a504b8dbcfde3e55e",
}


def canonical(value: Any) -> bytes:
    """Usa JSON estándar, sin importar código de grafos de producción."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


INPUTS = json.loads((FIXTURES / "inputs.json").read_bytes())
EXPECTED = json.loads((FIXTURES / "expected.json").read_bytes())
CASES = {(c["id"], c["variant"]): c for c in INPUTS["cases"]}
RESULTS = {(c["id"], c["variant"]): c for c in EXPECTED["cases"]}


def semantic_key(node: dict[str, Any]) -> tuple[str, ...]:
    """Obtiene la clave comparable sin identificadores de ejecución."""
    kind = node["node_kind"]
    if kind == "component":
        return kind, node["component_type"], node["component_id"]
    if kind == "event":
        return kind, node["component_type"], node["component_id"], node["event_type"]
    assert kind == "payload"
    return kind, node["payload_hash"]["value"]


def _sorted_entries(items: list[Any]) -> list[Any]:
    return sorted(items, key=canonical)


def independent_delta(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Contrasta grupos del oráculo por conjuntos, sin usar el diferenciador P3."""
    maps: list[dict[tuple[str, ...], list[dict[str, Any]]]] = []
    for graph in (baseline, candidate):
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for node in graph["nodes"]:
            grouped[semantic_key(node)].append(node)
        maps.append(grouped)
    before, after = maps
    ambiguous = {key for key in before.keys() | after.keys()
                 if len(before.get(key, ())) > 1 or len(after.get(key, ())) > 1}
    summary: dict[str, list[Any]] = {name: [] for name in (
        "node_added", "node_removed", "node_changed", "node_unchanged",
        "node_ambiguous", "edge_added", "edge_removed", "edge_ambiguous"
    )}
    for key in before.keys() | after.keys():
        if key in ambiguous:
            summary["node_ambiguous"].append({
                "key": list(key), "baseline_count": len(before.get(key, ())),
                "candidate_count": len(after.get(key, ())),
            })
        elif key not in before:
            summary["node_added"].append(list(key))
        elif key not in after:
            summary["node_removed"].append(list(key))
        elif key[0] == "event":
            changed = [field for field in ("payload_hash", "attributes", "error")
                       if before[key][0][field] != after[key][0][field]]
            if changed:
                summary["node_changed"].append({"key": list(key),
                                                "changed_fields": sorted(changed)})
            else:
                summary["node_unchanged"].append(list(key))
        else:
            summary["node_unchanged"].append(list(key))

    edge_sets: list[set[tuple[str, tuple[str, ...], tuple[str, ...]]]] = []
    for side, graph in (("baseline", baseline), ("candidate", candidate)):
        nodes = {node["node_id"]: node for node in graph["nodes"]}
        comparable: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
        unresolved: Counter[tuple[str, tuple[str, ...], tuple[str, ...]]] = Counter()
        for edge in graph["edges"]:
            src = semantic_key(nodes[edge["source_node_id"]])
            dst = semantic_key(nodes[edge["target_node_id"]])
            item = (edge["edge_kind"], src, dst)
            if src in ambiguous or dst in ambiguous:
                unresolved[item] += 1
            else:
                assert item not in comparable, "Arista comparable duplicada."
                comparable.add(item)
        for (kind, src, dst), count in unresolved.items():
            summary["edge_ambiguous"].append({
                "edge_kind": kind, "source_key": list(src),
                "target_key": list(dst), "side": side, "count": count,
            })
        edge_sets.append(comparable)
    for name, differences in (("edge_removed", edge_sets[0] - edge_sets[1]),
                              ("edge_added", edge_sets[1] - edge_sets[0])):
        for kind, src, dst in differences:
            summary[name].append({"edge_kind": kind, "source_key": list(src),
                                  "target_key": list(dst)})
    return {key: _sorted_entries(value) for key, value in summary.items()}


@pytest.mark.parametrize("path,sha", sorted(FROZEN_SHA256.items()))
def test_normative_files_match_the_freeze_manifest(path: str, sha: str) -> None:
    """Impide cambiar los oráculos o contratos sin versionar un nuevo freeze."""
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha


def test_freeze_index_and_serialization_are_exact() -> None:
    """El índice congelado tiene 15 variantes y salidas canónicas completas."""
    assert set(CASES) == set(RESULTS)
    assert len(CASES) == 15
    assert {key[0] for key in CASES} == {f"G{x:02d}" for x in range(1, 11)}
    for filename in ("inputs.json", "expected.json"):
        data = json.loads((FIXTURES / filename).read_bytes())
        assert (FIXTURES / filename).read_bytes() == canonical(data) + b"\n"


@pytest.mark.parametrize("key", [key for key in RESULTS if "graphs" in RESULTS[key]],
                         ids=lambda key: "-".join(key))
def test_expected_graphs_have_complete_projection_structure(key: tuple[str, str]) -> None:
    """Contrasta nodos, aristas y procedencia con entradas de F2."""
    incoming, result = CASES[key], RESULTS[key]
    for role, graph in result["graphs"].items():
        assert set(graph) == {
            "schema_version", "run_id", "app_id", "case_id", "condition_id",
            "repeat_index", "system_version_id", "trace_hash", "nodes", "edges", "graph_hash",
        }
        assert graph["trace_hash"] is None
        assert graph["graph_hash"] == digest({k: v for k, v in graph.items() if k != "graph_hash"})
        events = incoming["traces"][role]
        assert events
        assert graph["run_id"] == events[0]["run_id"]
        nodes = {node["node_id"]: node for node in graph["nodes"]}
        seen_payload_refs: dict[str, dict[str, Any] | None] = {}
        constructed_edges: set[tuple[str, str, str]] = set()
        event_node_by_id: dict[str, str] = {}
        for event in events:
            run = event["run_id"]
            component_id = digest(["r0.8.node.v1", run, "component",
                                   event["component_type"], event["component_id"]])
            event_id = digest(["r0.8.node.v1", run, "event", event["event_id"]])
            payload = event["payload_hash"]["value"]
            payload_id = digest(["r0.8.node.v1", run, "payload", payload])
            assert nodes[component_id] == {
                "node_id": component_id, "node_kind": "component",
                "component_type": event["component_type"],
                "component_id": event["component_id"],
            }
            assert nodes[event_id] == {
                "node_id": event_id, "node_kind": "event",
                **{name: event[name] for name in (
                    "event_id", "sequence", "timestamp_utc", "event_type", "component_type",
                    "component_id", "payload_hash", "attributes", "error")},
            }
            assert nodes[payload_id] == {
                "node_id": payload_id, "node_kind": "payload",
                "payload_hash": event["payload_hash"], "payload_ref": event["payload_ref"],
            }
            if payload in seen_payload_refs:
                assert seen_payload_refs[payload] == event["payload_ref"]
            seen_payload_refs[payload] = event["payload_ref"]
            constructed_edges.add(("emits", component_id, event_id))
            constructed_edges.add(("produces", event_id, payload_id))
            for parent in event["parent_event_ids"]:
                assert parent in event_node_by_id
                constructed_edges.add(("observed_parent", event_node_by_id[parent], event_id))
            event_node_by_id[event["event_id"]] = event_id
        assert len(nodes) == len({x for e in constructed_edges for x in e[1:]})
        actual_edges = {(e["edge_kind"], e["source_node_id"], e["target_node_id"])
                        for e in graph["edges"]}
        assert actual_edges == constructed_edges
        assert len(graph["edges"]) == len(actual_edges)


@pytest.mark.parametrize("key", [key for key in RESULTS if RESULTS[key].get("delta")],
                         ids=lambda key: "-".join(key))
def test_expected_delta_matches_independent_semantic_audit(key: tuple[str, str]) -> None:
    """Audita grupos P3 sin apoyarse en una implementación de R0.8-I."""
    result = RESULTS[key]
    expected_delta = result["delta"]
    independent = independent_delta(result["graphs"]["baseline"],
                                    result["graphs"]["candidate"])
    for name, items in independent.items():
        assert expected_delta[name] == items, f"Diferencial incorrecto en {key}: {name}."
    assert expected_delta["delta_hash"] == digest({k: v for k, v in expected_delta.items()
                                                   if k != "delta_hash"})


def test_ambiguous_group_never_uses_position_as_correspondence() -> None:
    """Las llamadas repetidas G06 deben permanecer sin emparejamiento arbitrario."""
    result = RESULTS[("G06", "ambiguous-repeated-event")]["delta"]
    assert result["node_ambiguous"] == [{
        "baseline_count": 2, "candidate_count": 2,
        "key": ["event", "model", "same-model", "model.invoked"],
    }]
    assert len(result["edge_ambiguous"]) == 4
    assert all(edge["count"] == 2 for edge in result["edge_ambiguous"])


def test_negative_cases_remain_explicit_and_stage_qualified() -> None:
    """Los resultados inválidos nunca contienen grafos o deltas parciales."""
    negative = [item for item in RESULTS.values() if "error" in item]
    assert len(negative) == 8
    assert {item["error"]["stage"] for item in negative} == {
        "projection", "comparison", "schema", "graph_validation",
    }
    for item in negative:
        assert set(item) == {"id", "variant", "error"}
        assert set(item["error"]) == {"stage", "code"}


def test_r07_legacy_imports_remain_outside_the_reference_audit() -> None:
    """F3 no introduce dependencias en el paquete heredado."""
    from provregress.schema.events import EventEnvelope
    from provregress.storage.jsonl import validate_event_log
    assert EventEnvelope is not None
    assert callable(validate_event_log)

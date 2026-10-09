"""Gate F2: oráculos adversariales completos, con testigos lógicos externos.

Los archivos esperados se fijaron mediante una referencia aislada de stdlib,
con clasificación de casos escrita antes de invocar el motor de producción.
No se regeneran estas expectativas desde project_trace_v2/compare_graphs_v2.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from provregress.provenance_v2 import (
    ComparisonPolicyV2, DeltaV2, EventV2, V2Error,
    assert_pilot_alignment_v2, canonical_v2, compare_graphs_v2,
    project_trace_v2, sequential_baseline_view_v2, topology_profile_v2,
)

ROOT = Path(__file__).resolve().parents[1] / "fixtures/provenance/r0_10_f2"
CASES = json.loads((ROOT / "cases.json").read_bytes())["cases"]
EXPECTED = json.loads((ROOT / "expected.json").read_bytes())["cases"]
SCENARIOS = {record["id"]: record for record in CASES}
ORACLES = {record["id"]: record for record in EXPECTED}
GOOD = [record for record in CASES if record["verdict"]["stage"] == "ok"]

# Huellas fijas e independientes del código de producción: cambiar los JSON
# sin revisar este gate es una alteración detectable del oráculo.
PINNED = {
    "cases.json": "ef2b1f3445866f8f639a5f3ccac38fc32aa2f762516584590ed7291cd55f73e2",
    "expected.json": "a4b66f6025f2036cdad3636881c03bdeddd93a95afb93bc81e100f58d0cb9c99",
}


def _models(identifier: str):
    scenario = SCENARIOS[identifier]
    graphs = tuple(project_trace_v2([
        EventV2.model_validate_json(canonical_v2(event))
        for event in scenario[side]
    ]) for side in ("baseline", "candidate"))
    policy = ComparisonPolicyV2.model_validate_json(canonical_v2(scenario["policy"]))
    return graphs[0], graphs[1], policy


def _key(raw: dict) -> tuple[str, ...]:
    return ("event", raw["component_type"], raw["component_id"],
            *raw["scope_path"], raw["invocation_key"], raw["event_type"])


def _logical_witness_error(record: dict) -> str | None:
    """Juez externo: utiliza IDs de operaciones definidos fuera del evento v2.

    Esta comprobación es posible en fixtures instrumentadas; en A2/A3 reales
    hará falta registrar el origen de estos testigos antes de la ejecución.
    """
    by_side: dict[str, dict[tuple[str, ...], str]] = {}
    by_logical: dict[str, dict[str, tuple[str, ...]]] = {}
    for side in ("baseline", "candidate"):
        values = record["witness"][side]
        events = record[side]
        if set(values) != {event["event_id"] for event in events}:
            return "incomplete_witness"
        by_side[side] = {}
        by_logical[side] = {}
        for event in events:
            key = _key(event)
            identity = values[event["event_id"]]
            if key in by_side[side] and by_side[side][key] != identity:
                return "duplicate_invocation_key"
            if identity in by_logical[side] and by_logical[side][identity] != key:
                return "inconsistent_logical_identity"
            by_side[side][key] = identity
            by_logical[side][identity] = key
    for key in by_side["baseline"].keys() & by_side["candidate"].keys():
        if by_side["baseline"][key] != by_side["candidate"][key]:
            return "unstable_invocation_key"
    for identity in by_logical["baseline"].keys() & by_logical["candidate"].keys():
        if by_logical["baseline"][identity] != by_logical["candidate"][identity]:
            return "unstable_invocation_key"
    return None


def test_complete_oracle_index_and_immutability() -> None:
    assert [item["id"] for item in CASES] == [f"V{i:03d}" for i in range(205, 214)]
    assert [item["id"] for item in EXPECTED] == [item["id"] for item in CASES]
    rows = (ROOT / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    assert len(rows) == 2
    for row in rows:
        checksum, name = row.split("  ", maxsplit=1)
        assert PINNED[name] == checksum
        data = (ROOT / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == checksum
        assert data == canonical_v2(json.loads(data)) + b"\n"


@pytest.mark.parametrize("identifier", list(SCENARIOS))
@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_golden_projection_bytes_and_hash_exact(identifier: str, side: str) -> None:
    before, after, _ = _models(identifier)
    observed = before if side == "baseline" else after
    golden = ORACLES[identifier]["graphs"][side]
    assert canonical_v2(observed) == canonical_v2(golden)
    assert observed.graph_hash == golden["graph_hash"]
    assert topology_profile_v2(observed) == ORACLES[identifier]["profiles"][side]


@pytest.mark.parametrize("identifier", [item["id"] for item in GOOD])
def test_exact_golden_delta_for_positive_cases(identifier: str) -> None:
    before, after, policy = _models(identifier)
    actual = compare_graphs_v2(before, after, policy)
    expected = ORACLES[identifier]["delta"]
    assert isinstance(actual, DeltaV2)
    assert canonical_v2(actual) == canonical_v2(expected)
    assert actual.delta_hash == expected["delta_hash"]
    assert canonical_v2(compare_graphs_v2(before, after, policy)) == canonical_v2(actual)


@pytest.mark.parametrize("identifier", ["V205", "V206", "V207", "V210", "V211", "V212", "V213"])
def test_external_witness_preserves_stable_logical_identity(identifier: str) -> None:
    assert _logical_witness_error(SCENARIOS[identifier]) is None
    for side in ("baseline", "candidate"):
        # La identidad privilegiada no forma parte de los bytes observables.
        assert all("logical_id" not in event and "witness" not in event
                   for event in SCENARIOS[identifier][side])


def test_ordinal_rekey_would_false_match_but_external_witness_blocks_it() -> None:
    case = SCENARIOS["V208"]
    assert _logical_witness_error(case) == "unstable_invocation_key"
    before, after, policy = _models("V208")
    # La comparación local no puede detectar el desplazamiento ordinal sin
    # testigo semántico: se documenta como fallo esperado, no como PASS científico.
    untrusted = compare_graphs_v2(before, after, policy)
    assert len(untrusted.unchanged_events) == 2
    assert len(untrusted.added_events) == 1
    assert len(untrusted.changed_events) == 0
    assert ORACLES["V208"]["stage"] == "identity_witness"
    assert "delta" not in ORACLES["V208"]


def test_key_collision_remains_ambiguous_and_blocks_pilot() -> None:
    assert _logical_witness_error(SCENARIOS["V209"]) == "duplicate_invocation_key"
    before, after, policy = _models("V209")
    delta = compare_graphs_v2(before, after, policy)
    assert len(delta.ambiguous_events) == 1
    assert (delta.ambiguous_events[0].baseline_count,
            delta.ambiguous_events[0].candidate_count) == (2, 1)
    assert Decimal(delta.ambiguous_event_rate) == 1
    with pytest.raises(V2Error, match="ambigüedad"):
        assert_pilot_alignment_v2(before, after, delta, policy=policy)


def test_missing_policy_signal_rejected_without_imputation() -> None:
    before, after, policy = _models("V211")
    with pytest.raises(V2Error, match="Falta señal"):
        compare_graphs_v2(before, after, policy)
    assert ORACLES["V211"]["stage"] == "comparison"
    assert "delta" not in ORACLES["V211"]


def test_insertion_before_preserves_old_keys_and_old_parent_edges() -> None:
    case = SCENARIOS["V205"]
    b, a, policy = _models("V205")
    delta = compare_graphs_v2(b, a, policy)
    old_keys = {_key(event) for event in case["baseline"]}
    assert old_keys == {tuple(key) for key in delta.unchanged_events}
    assert len(delta.added_events) == 1 and not delta.removed_events
    assert not delta.changed_events and not delta.ambiguous_events
    assert len(delta.edges_added) == 1 and not delta.edges_removed
    assert all(row["sequence"] >= 0 for row in sequential_baseline_view_v2(a))


def test_parallel_reorder_has_same_semantics_and_topology() -> None:
    b, a, policy = _models("V206")
    delta = compare_graphs_v2(b, a, policy)
    assert not (delta.added_events or delta.removed_events or delta.changed_events)
    assert not (delta.edges_added or delta.edges_removed or delta.edges_ambiguous)
    assert len(delta.unchanged_events) == 4
    assert topology_profile_v2(b)["forks"] == 1
    assert topology_profile_v2(a)["joins"] == 1
    expected_links = Counter((tuple(edge.source_key), tuple(edge.target_key))
                             for edge in delta.edges_added + delta.edges_removed)
    assert not expected_links


def test_new_retry_preserves_unrelated_old_invocations() -> None:
    b, a, policy = _models("V207")
    delta = compare_graphs_v2(b, a, policy)
    assert len(delta.added_events) == 1
    assert len(delta.unchanged_events) == 2
    assert (len(delta.edges_added), len(delta.edges_removed)) == (2, 1)


def test_topological_change_is_not_counted_as_functional_event_change() -> None:
    b, a, policy = _models("V210")
    delta = compare_graphs_v2(b, a, policy)
    assert len(delta.unchanged_events) == 4
    assert not delta.changed_events
    assert len(delta.edges_removed) == 1
    assert not delta.edges_added


def test_weighted_functional_magnitude_and_noise_are_not_multicounted() -> None:
    b, a, policy = _models("V212")
    delta = compare_graphs_v2(b, a, policy)
    assert len(delta.changed_events) == 1
    change = delta.changed_events[0]
    assert Decimal(change.magnitude) == Decimal("0.75") * Decimal("0.2") + Decimal("0.25")
    assert change.changed_signals == ["grounded", "relevant_evidence"]
    assert change.raw_payload_changed
    assert not (delta.edges_added or delta.edges_removed or delta.added_events)


def test_unassessed_target_must_not_pass_pilot_gate() -> None:
    b, a, policy = _models("V213")
    delta = compare_graphs_v2(b, a, policy)
    assert len(delta.unassessed_events) == 1
    with pytest.raises(V2Error, match="no expresable"):
        assert_pilot_alignment_v2(b, a, delta, policy=policy,
                                  target_keys=[tuple(delta.unassessed_events[0])])


def test_primary_sequential_baseline_has_all_parent_evidence() -> None:
    for case in CASES:
        before, after, _ = _models(case["id"])
        for side, graph in (("baseline", before), ("candidate", after)):
            parent_map = {row["event_id"]: row["parent_event_ids"]
                          for row in sequential_baseline_view_v2(graph)}
            assert parent_map == {event["event_id"]: sorted(event["parent_event_ids"])
                                  for event in case[side]}
            without_parents = sequential_baseline_view_v2(graph, include_parent_relations=False)
            assert all(not row["parent_event_ids"] for row in without_parents)


def test_f2_reference_oracle_runs_without_production_imports() -> None:
    independent = ROOT.parents[3] / "research/verification/r010_f2_reference_oracle.py"
    content = independent.read_text(encoding="utf-8")
    assert "from provregress" not in content and "import provregress" not in content
    completed = subprocess.run(
        [sys.executable, str(independent)], capture_output=True,
        text=True, check=True, timeout=15,
    )
    assert "9 escenarios, 18 grafos, 7 deltas, 2 rechazos" in completed.stdout


def test_existing_v1_and_candidate_fixtures_remain_unchanged() -> None:
    for directory in ("r0_8", "r0_10"):
        root = ROOT.parent / directory
        records = (root / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        for record in records:
            digest, filename = record.split("  ", maxsplit=1)
            assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == digest

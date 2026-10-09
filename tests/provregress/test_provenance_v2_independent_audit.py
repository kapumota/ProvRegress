"""Gate R0.10-F1: auditoría independiente de identidades y baselines v2.

Estos oráculos describen invariantes/escenarios sin generar expectativas a
partir del resultado de la implementación que se está auditando.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from provregress.provenance_v2 import (
    ComparisonPolicyV2, EventV2, SignalRule, V2Error,
    assert_pilot_alignment_v2, canonical_v2, compare_graphs_v2,
    project_trace_v2, sequential_baseline_view_v2, topology_profile_v2,
)
from provregress.schema.common import AppId
from provregress.schema.events import EventType
from provregress.storage.hashing import sha256_hex

ROOT = Path(__file__).resolve().parents[1] / "fixtures/provenance/r0_10"
CASE_DATA = json.loads((ROOT / "cases.json").read_bytes())
CASES = {record["id"]: record for record in CASE_DATA["cases"]}

# Especificación de señales hecha por un evaluador separado de compare_graphs_v2.
POLICIES = {
    "V201": (AppId.A3, EventType.TOOL_RETURNED, "quality", "decimal", "0.5"),
    "V202": (AppId.A2, EventType.RETRIEVAL_RETURNED, "relevant_evidence", "decimal", "5"),
    "V203": (AppId.A3, EventType.TOOL_RETURNED, "quality", "decimal", "0.5"),
    "V204": (AppId.A3, EventType.TOOL_RETURNED, "quality", "decimal", "0.5"),
}


def _policy(identifier: str) -> ComparisonPolicyV2:
    app, kind, field, metric, scale = POLICIES[identifier]
    # Para V202 también hay un outcome sin modificación funcional.
    rules = [SignalRule(event_type=kind, field=field, kind=metric, scale=scale, weight="1")]
    if identifier == "V202":
        rules.append(SignalRule(
            event_type=EventType.OUTCOME_RECORDED, field="result",
            kind="categorical", weight="1",
        ))
    return ComparisonPolicyV2(app_id=app, rules=rules)


def _graphs(identifier: str):
    source = CASES[identifier]
    return tuple(project_trace_v2([
        EventV2.model_validate_json(canonical_v2(event))
        for event in source[side]
    ]) for side in ("baseline", "candidate"))


def _event_key(row: dict) -> tuple[str, ...]:
    return ("event", row["component_type"], row["component_id"],
            *row["scope_path"], row["invocation_key"], row["event_type"])


def test_fixture_candidates_preserve_full_file_hashes() -> None:
    entries = (ROOT / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    assert len(entries) == 2
    for row in entries:
        digest, filename = row.split("  ", maxsplit=1)
        assert filename in {"cases.json", "expected.json"}
        assert sha256_hex((ROOT / filename).read_bytes()) == digest


def test_v201_precisely_identifies_one_added_invocation_without_ordinal_matching() -> None:
    left, right = _graphs("V201")
    delta = compare_graphs_v2(left, right, _policy("V201"))
    extra = _event_key(CASES["V201"]["candidate"][-1])
    assert [tuple(k) for k in delta.added_events] == [extra]
    assert {tuple(key) for key in delta.unchanged_events} == {
        _event_key(e) for e in CASES["V201"]["baseline"]
    }
    assert not delta.changed_events and not delta.ambiguous_events
    assert Decimal(delta.ambiguous_event_rate) == 0


def test_v202_one_located_retrieval_change_with_independent_distance() -> None:
    before, after = _graphs("V202")
    delta = compare_graphs_v2(before, after, _policy("V202"))
    changed = _event_key(CASES["V202"]["baseline"][2])
    assert [tuple(row.key) for row in delta.changed_events] == [changed]
    assert Decimal(delta.changed_events[0].magnitude) == abs(Decimal("4") - Decimal("3")) / Decimal("5")
    assert not delta.added_events and not delta.removed_events
    assert topology_profile_v2(before) == {
        "events": 4, "edges": 4, "forks": 1, "joins": 1, "branched": True,
    }


def test_v203_noise_only_preserves_functional_classification() -> None:
    before, after = _graphs("V203")
    delta = compare_graphs_v2(before, after, _policy("V203"))
    key = _event_key(CASES["V203"]["baseline"][0])
    assert [tuple(k) for k in delta.unchanged_events] == [key]
    assert [tuple(k) for k in delta.ignored_payload_changes] == [key]
    assert not delta.changed_events


def test_v204_collision_is_ambiguous_not_arbitrarily_paired() -> None:
    before, after = _graphs("V204")
    delta = compare_graphs_v2(before, after, _policy("V204"))
    assert len(delta.ambiguous_events) == 1
    group = delta.ambiguous_events[0]
    assert tuple(group.key) == _event_key(CASES["V204"]["baseline"][0])
    assert (group.baseline_count, group.candidate_count) == (2, 1)
    assert not delta.changed_events and not delta.added_events and not delta.removed_events
    with pytest.raises(V2Error, match="ambigüedad"):
        assert_pilot_alignment_v2(before, after, delta, policy=_policy("V204"))


@pytest.mark.parametrize("identifier", ["V201", "V202", "V203", "V204"])
def test_sequential_view_parent_links_use_visible_event_ids(identifier: str) -> None:
    before, _ = _graphs(identifier)
    view = sequential_baseline_view_v2(before)
    assert [row["event_id"] for row in view] == [
        event["event_id"] for event in CASES[identifier]["baseline"]
    ]
    expected_parents = {
        event["event_id"]: sorted(event["parent_event_ids"])
        for event in CASES[identifier]["baseline"]
    }
    assert {row["event_id"]: row["parent_event_ids"] for row in view} == expected_parents
    assert all(parent in expected_parents for row in view for parent in row["parent_event_ids"])
    no_parents = sequential_baseline_view_v2(before, include_parent_relations=False)
    assert all(row["parent_event_ids"] == [] for row in no_parents)
    assert [row["semantic_values"] for row in no_parents] == [row["semantic_values"] for row in view]


def test_metadata_containing_treatment_labels_cannot_be_ingested() -> None:
    raw = dict(CASES["V203"]["baseline"][0])
    raw["semantic_values"] = {"quality": "0.8", "sub": {"mutation_id": "hidden"}}
    with pytest.raises(ValueError):
        EventV2.model_validate_json(canonical_v2(raw))


def test_ambiguous_target_is_rejected_even_with_other_unique_events() -> None:
    before, after = _graphs("V204")
    delta = compare_graphs_v2(before, after, _policy("V204"))
    with pytest.raises(V2Error):
        assert_pilot_alignment_v2(before, after, delta, policy=_policy("V204"),
                                  target_keys=[tuple(delta.ambiguous_events[0].key)])


def test_manual_identity_collision_is_not_evidence_of_stability() -> None:
    """A key válida puede ser ordinal: probar sintaxis no certifica trazabilidad."""
    rows = CASES["V201"]["candidate"]
    assert [record["invocation_key"] for record in rows] == [
        "lookup-0", "lookup-1", "lookup-2", "lookup-3"
    ]
    assert len({record["invocation_key"] for record in rows}) == 4
    # Ausencia de evidencia del generador de claves: NO se declara freeze v2.

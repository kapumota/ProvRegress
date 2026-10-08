"""Pruebas del contrato de eventos P1, R0.7-C6."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from provregress.schema import AppId, ArtifactRef, ComponentType, HashRef
from provregress.schema.events import EventEnvelope, EventError, EventType
from provregress.storage.hashing import canonical_json_bytes, hash_model


HASH = HashRef(algorithm="sha256", value="a" * 64)


@pytest.fixture
def payload() -> dict[str, object]:
    """Proporciona un evento piloto independiente de un ejecutor."""
    return {
        "run_id": "run-pilot-1",
        "event_id": "evt-0",
        "sequence": 0,
        "timestamp_utc": datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc),
        "app_id": AppId.A1,
        "system_version_id": "v1",
        "case_id": "pilot-a",
        "condition_id": "baseline",
        "repeat_index": 0,
        "event_type": EventType.MODEL_RETURNED,
        "component_type": ComponentType.MODEL,
        "component_id": "model-primary",
        "parent_event_ids": [],
        "payload_hash": HASH,
        "attributes": {"latency_ms": 13, "cached": False},
    }


def test_event_types_match_frozen_p1_vocabulary() -> None:
    assert {item.value for item in EventType} == {
        "run.started", "run.finished", "prompt.issued", "model.invoked",
        "model.returned", "retrieval.started", "retrieval.returned",
        "tool.called", "tool.returned", "evaluator.invoked",
        "evaluator.scored", "outcome.recorded", "error.observed",
    }
    assert len(EventType) == 13


def test_event_envelope_roundtrip_and_default_version(payload: dict[str, object]) -> None:
    event = EventEnvelope.model_validate(payload)
    assert event.schema_version == "pilot-event-v1"
    assert event.payload_ref is None
    assert event.error is None
    assert EventEnvelope.model_validate_json(event.model_dump_json()) == event
    assert hash_model(event) == hash_model(EventEnvelope.model_validate(payload))
    assert b'"event_type":"model.returned"' in canonical_json_bytes(event)


def test_event_envelope_rejects_extra_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"mutation_id": "m1"})
    assert EventEnvelope.model_json_schema()["additionalProperties"] is False


def test_event_envelope_rejects_unknown_schema_version(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"schema_version": "pilot-event-v2"})


@pytest.mark.parametrize("name", [
    "run_id", "event_id", "system_version_id", "case_id",
    "condition_id", "component_id",
])
@pytest.mark.parametrize("invalid", ["", " \t", None, 42])
def test_event_identity_requires_nonblank_strings(
    payload: dict[str, object], name: str, invalid: object
) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {name: invalid})


@pytest.mark.parametrize("name", ["sequence", "repeat_index"])
@pytest.mark.parametrize("invalid", [-1, True, False, 1.2, "1", None])
def test_event_counters_must_be_nonnegative_strict_integers(
    payload: dict[str, object], name: str, invalid: object
) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {name: invalid})


def test_event_envelope_requires_utc_aware_timestamp(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"timestamp_utc": datetime(2026, 10, 8)})
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(
            EventEnvelope.model_validate(payload).model_dump_json().replace(
                "2026-10-08T17:00:00Z", "2026-10-08T17:00:00"
            )
        )


def test_timestamp_with_offset_is_normalized_to_utc(payload: dict[str, object]) -> None:
    local = datetime(2026, 10, 8, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    event = EventEnvelope.model_validate(payload | {"timestamp_utc": local})
    assert event.timestamp_utc == payload["timestamp_utc"]
    assert event.timestamp_utc.tzinfo is timezone.utc
    assert '"timestamp_utc":"2026-10-08T17:00:00Z"' in event.model_dump_json()


@pytest.mark.parametrize("parents", [["p", "p"], ["p", ""], [" "], [4]])
def test_event_envelope_rejects_duplicate_or_invalid_parent_ids(
    payload: dict[str, object], parents: list[object]
) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"parent_event_ids": parents})


def test_event_rejects_self_parent(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"parent_event_ids": ["evt-0"]})


def test_event_allows_multiple_distinct_parents(payload: dict[str, object]) -> None:
    event = EventEnvelope.model_validate(payload | {"parent_event_ids": ["evt-1", "evt-2"]})
    assert event.parent_event_ids == ["evt-1", "evt-2"]


@pytest.mark.parametrize("key", [
    "mutation_id", "operator_id", "target_component_id", "severity",
])
def test_event_attributes_cannot_use_reserved_mutation_keys(
    payload: dict[str, object], key: str
) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"attributes": {key: "label"}})


@pytest.mark.parametrize("attributes", [
    {"outer": {"mutation_id": "hidden"}},
    {"outer": [{"target_component_id": "model"}]},
    {"nested": {"metadata": [{"severity": "high"}]}},
])
def test_event_attributes_reject_nested_reserved_labels(
    payload: dict[str, object], attributes: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"attributes": attributes})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_event_attributes_reject_nonfinite_values(payload: dict[str, object], bad: float) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"attributes": {"score": bad}})


def test_event_attributes_reject_non_json_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"attributes": {"bytes": b"invalid"}})


def test_event_attributes_are_required_and_json_typed(payload: dict[str, object]) -> None:
    without = payload.copy()
    del without["attributes"]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(without)
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"attributes": ["not", "a", "mapping"]})


def test_payload_hash_is_required(payload: dict[str, object]) -> None:
    without = payload.copy()
    del without["payload_hash"]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(without)


def test_payload_reference_must_match_payload_hash(payload: dict[str, object]) -> None:
    ref = ArtifactRef(hash=HASH, relative_path="artifacts/a.json", size_bytes=12)
    event = EventEnvelope.model_validate(payload | {"payload_ref": ref})
    assert event.payload_ref == ref
    assert EventEnvelope.model_validate_json(event.model_dump_json()) == event
    wrong = ArtifactRef(
        hash=HashRef(algorithm="sha256", value="b" * 64),
        relative_path="artifacts/b.json",
        size_bytes=12,
    )
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"payload_ref": wrong})


def test_payload_reference_rejects_unsafe_path(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"payload_ref": {
            "hash": HASH.model_dump(), "relative_path": "../bad", "size_bytes": 0,
        }})


def test_structured_event_error_roundtrip(payload: dict[str, object]) -> None:
    event = EventEnvelope.model_validate(payload | {"error": {
        "category": "provider_timeout", "message": "El proveedor agotó el tiempo.",
        "retryable": True, "details": {"attempt": 2},
    }})
    assert event.error is not None
    assert event.error.retryable is True
    assert EventEnvelope.model_validate_json(event.model_dump_json()) == event


def test_event_error_defaults_are_independent() -> None:
    first = EventError(category="runtime", message="Fallo de ejecución.")
    second = EventError(category="runtime", message="Segundo fallo.")
    first.details["attempt"] = 1
    assert second.details == {}
    assert second.retryable is False
    assert EventError.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("bad", [
    {"category": "", "message": "error"},
    {"category": "runtime", "message": "   "},
    {"category": "runtime", "message": "error", "retryable": 1},
    {"category": "runtime", "message": "error", "extra": True},
    {"category": "runtime", "message": "error", "details": {"operator_id": "hidden"}},
    {"category": "runtime", "message": "error", "details": {"x": float("inf")}},
])
def test_event_error_rejects_invalid_details(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventError.model_validate(bad)


@pytest.mark.parametrize("name,invalid", [
    ("event_type", "invalid.event"),
    ("component_type", "made_up_component"),
    ("app_id", "a4_invalid"),
])
def test_event_rejects_unknown_enums(
    payload: dict[str, object], name: str, invalid: str
) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {name: invalid})


def test_event_requires_parent_id_list(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload | {"parent_event_ids": None})
    without = payload.copy()
    del without["parent_event_ids"]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(without)


def test_envelope_has_only_observable_fields() -> None:
    forbidden = {"mutation_id", "operator_id", "target_component_id", "severity", "root_cause"}
    assert forbidden.isdisjoint(EventEnvelope.model_fields)
    assert not ("llmtestlab" in __import__("inspect").getsource(EventEnvelope))

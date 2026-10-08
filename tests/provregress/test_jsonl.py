"""Pruebas de integridad del registro append-only JSONL, gate R0.7-C8."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.schema import AppId, ComponentType, HashRef
from provregress.schema.events import EventEnvelope, EventType
from provregress.storage.hashing import canonical_json_bytes, sha256_hex
from provregress.storage.jsonl import (
    EventLogError,
    EventLogFormatError,
    EventLogIntegrityError,
    EventLogSummary,
    append_event,
    iter_events,
    validate_event_log,
)


DIGEST = HashRef(algorithm="sha256", value="a" * 64)


def event(sequence: int, *, run_id: str = "run-1", parent_ids: list[str] | None = None,
          event_id: str | None = None, **changes: object) -> EventEnvelope:
    """Crea eventos observables mínimos con identidades controladas."""
    data = dict(
        run_id=run_id,
        event_id=event_id or f"evt-{sequence}",
        sequence=sequence,
        timestamp_utc=datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc),
        app_id=AppId.A1,
        system_version_id="v1",
        case_id="pilot-a",
        condition_id="baseline",
        repeat_index=0,
        event_type=EventType.MODEL_RETURNED,
        component_type=ComponentType.MODEL,
        component_id="model-1",
        parent_event_ids=parent_ids if parent_ids is not None else [],
        payload_hash=DIGEST,
        attributes={"size": sequence},
    )
    data.update(changes)
    return EventEnvelope.model_validate(data)


def test_append_event_writes_exact_canonical_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    first = event(0)
    second = event(1, parent_ids=[first.event_id])
    append_event(path, first)
    prior = path.read_bytes()
    append_event(path, second)
    assert prior == canonical_json_bytes(first) + b"\n"
    assert path.read_bytes() == prior + canonical_json_bytes(second) + b"\n"
    assert list(iter_events(path)) == [first, second]
    assert sha256_hex(path.read_bytes()) == sha256_hex(prior + canonical_json_bytes(second) + b"\n")


def test_append_event_creates_parent_folder(tmp_path: Path) -> None:
    path = tmp_path / "run" / "logs" / "events.jsonl"
    append_event(path, event(0))
    assert path.is_file()
    assert list(iter_events(path)) == [event(0)]


def test_append_event_can_start_from_existing_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.touch()
    append_event(path, event(0))
    assert list(iter_events(path)) == [event(0)]


def test_validator_reports_summary_and_expected_run() -> None:
    events = [event(0), event(1, parent_ids=["evt-0"]), event(2, parent_ids=["evt-1", "evt-0"])]
    summary = validate_event_log(iter(events), expected_run_id="run-1")
    assert summary == EventLogSummary(run_id="run-1", event_count=3, last_sequence=2, last_event_id="evt-2")
    assert summary.model_json_schema()["additionalProperties"] is False
    with pytest.raises(ValidationError):
        summary.event_count = 12


def test_validator_empty_log_without_expected_id() -> None:
    summary = validate_event_log([])
    assert summary.event_count == 0
    assert summary.run_id is None
    assert summary.last_sequence is None
    assert summary.last_event_id is None


def test_validator_rejects_empty_log_with_expected_run_id() -> None:
    with pytest.raises(EventLogIntegrityError, match="no contiene"):
        validate_event_log([], expected_run_id="run-1")


@pytest.mark.parametrize("bad", ["", "  ", 3, False])
def test_validator_rejects_invalid_expected_id(bad: object) -> None:
    with pytest.raises(EventLogIntegrityError):
        validate_event_log([event(0)], expected_run_id=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("events", [
    [event(1)],
    [event(0), event(2)],
    [event(0), event(1), event(3)],
    [event(0), event(0, event_id="other")],
])
def test_validate_event_log_requires_contiguous_sequence(events: list[EventEnvelope]) -> None:
    with pytest.raises(EventLogIntegrityError, match="secuencia"):
        validate_event_log(events)


def test_validator_rejects_duplicate_event_ids() -> None:
    with pytest.raises(EventLogIntegrityError, match="duplicado"):
        validate_event_log([event(0), event(1, event_id="evt-0")])


@pytest.mark.parametrize("parents", [["future"], ["evt-2"]])
def test_parent_must_reference_prior_event(parents: list[str]) -> None:
    with pytest.raises(EventLogIntegrityError, match="padre"):
        validate_event_log([event(0), event(1, parent_ids=parents)])


def test_multiple_prior_parents_are_allowed() -> None:
    events = [event(0), event(1), event(2, parent_ids=["evt-0", "evt-1"])]
    assert validate_event_log(events).event_count == 3


@pytest.mark.parametrize("changed", [
    {"run_id": "run-2"},
    {"app_id": AppId.A2},
    {"system_version_id": "v2"},
    {"case_id": "pilot-b"},
    {"condition_id": "candidate"},
    {"repeat_index": 1},
])
def test_validator_rejects_mixed_run_identity(changed: dict[str, object]) -> None:
    with pytest.raises(EventLogIntegrityError, match="identidad"):
        validate_event_log([event(0), event(1, **changed)])


def test_validator_rejects_unexpected_run_id() -> None:
    with pytest.raises(EventLogIntegrityError, match="run_id"):
        validate_event_log([event(0)], expected_run_id="other")


def test_validator_revalidates_mutated_event() -> None:
    forged = event(0).model_copy(update={"attributes": {"mutation_id": "secret"}})
    with pytest.raises(EventLogIntegrityError):
        validate_event_log([forged])


def test_validator_rejects_non_event() -> None:
    with pytest.raises(EventLogIntegrityError):
        validate_event_log([{"sequence": 0}])  # type: ignore[list-item]


@pytest.mark.parametrize("bad", [
    b"{bad}\n",
    b"\n",
    b'{}\n',
    b'"hello"\n',
    b'null\n',
    b'\xff\n',
])
def test_iter_events_reports_corrupted_json_with_line_number(tmp_path: Path, bad: bytes) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(canonical_json_bytes(event(0)) + b"\n" + bad)
    with pytest.raises(EventLogFormatError, match="Línea 2"):
        list(iter_events(path))


def test_iter_events_rejects_missing_final_newline(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(canonical_json_bytes(event(0)))
    with pytest.raises(EventLogFormatError, match="Línea 1"):
        list(iter_events(path))


@pytest.mark.parametrize("modify", [
    lambda text: json.dumps(json.loads(text), ensure_ascii=False, indent=2),
    lambda text: text.replace('"app_id":', '"app_id" :'),
    lambda text: text.replace('"sequence":0', '"sequence":0,"sequence":0'),
    lambda text: text.replace('"sequence":0', '"sequence": 0'),
])
def test_iter_events_rejects_noncanonical_json(tmp_path: Path, modify) -> None:
    original = canonical_json_bytes(event(0)).decode("utf-8")
    updated = modify(original)
    assert updated != original
    path = tmp_path / "events.jsonl"
    path.write_bytes(updated.encode("utf-8") + b"\n")
    with pytest.raises(EventLogFormatError, match="Línea 1"):
        list(iter_events(path))


def test_append_does_not_modify_existing_log_on_sequence_error(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_event(path, event(0))
    before = path.read_bytes()
    with pytest.raises(EventLogIntegrityError):
        append_event(path, event(2))
    assert path.read_bytes() == before


def test_append_rejects_mixed_run_and_duplicate_id_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_event(path, event(0))
    before = path.read_bytes()
    for bad in [event(1, run_id="run-other"), event(1, event_id="evt-0")]:
        with pytest.raises(EventLogIntegrityError):
            append_event(path, bad)
        assert path.read_bytes() == before


def test_append_rejects_parent_that_is_not_in_log(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_event(path, event(0))
    prior = path.read_bytes()
    with pytest.raises(EventLogIntegrityError, match="padre"):
        append_event(path, event(1, parent_ids=["never"] ))
    assert path.read_bytes() == prior


def test_append_rejects_corrupted_history_without_repair(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_event(path, event(0))
    path.write_bytes(path.read_bytes() + b"{wrong}\n")
    prior = path.read_bytes()
    with pytest.raises(EventLogFormatError, match="Línea 2"):
        append_event(path, event(1))
    assert path.read_bytes() == prior


def test_append_rejects_noncanonical_history_without_repair(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b" " + canonical_json_bytes(event(0)) + b"\n")
    original = path.read_bytes()
    with pytest.raises(EventLogFormatError, match="Línea 1"):
        append_event(path, event(1))
    assert path.read_bytes() == original


def test_append_rejects_mutated_event_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    forged = event(0).model_copy(update={"sequence": -1})
    with pytest.raises(EventLogIntegrityError):
        append_event(path, forged)
    assert not path.exists()


def test_iter_events_missing_log(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(iter_events(tmp_path / "unknown.jsonl"))


def test_append_and_read_reject_symlink_to_file(tmp_path: Path) -> None:
    external = tmp_path / "external.jsonl"
    external.write_bytes(b"original\n")
    link = tmp_path / "events.jsonl"
    link.symlink_to(external)
    with pytest.raises(EventLogError):
        append_event(link, event(0))
    with pytest.raises(EventLogError):
        list(iter_events(link))
    assert external.read_bytes() == b"original\n"


def test_append_and_read_reject_nonregular_file(tmp_path: Path) -> None:
    target = tmp_path / "events.jsonl"
    target.mkdir()
    with pytest.raises((EventLogError, IsADirectoryError)):
        append_event(target, event(0))
    with pytest.raises(EventLogError):
        list(iter_events(target))


def test_append_concurrent_writers_reject_duplicate_sequence(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    candidates = [event(0, event_id="zero-a"), event(0, event_id="zero-b")]
    def try_write(candidate: EventEnvelope) -> bool:
        try:
            append_event(path, candidate)
            return True
        except EventLogIntegrityError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        written = list(executor.map(try_write, candidates))
    assert written.count(True) == 1
    assert len(list(iter_events(path))) == 1
    assert validate_event_log(iter_events(path)).event_count == 1


def test_public_api_does_not_offer_rewrite_or_delete() -> None:
    import provregress.storage.jsonl as module
    assert not hasattr(module, "rewrite_event")
    assert not hasattr(module, "delete_event")
    assert issubclass(EventLogFormatError, EventLogError)
    assert issubclass(EventLogIntegrityError, EventLogError)

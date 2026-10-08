"""Pruebas de integración del sumidero piloto R0.7-C9."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.pilot.context import RunContext, build_run_context
from provregress.pilot.events import EventSinkError, JsonlEventSink, PilotEventSink
from provregress.schema import AppId, ComponentType, HashRef
from provregress.schema.events import EventError, EventType
from provregress.schema.manifests import (
    DatasetManifest,
    EnvironmentManifest,
    PilotStudyManifest,
    SystemManifest,
)
from provregress.storage.artifacts import ArtifactStore
from provregress.storage.hashing import canonical_json_bytes, hash_case_ids, hash_file, sha256_hex
from provregress.storage.jsonl import iter_events, validate_event_log

HASH = HashRef(algorithm="sha256", value="a" * 64)
UTC = datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc)


@pytest.fixture
def context() -> RunContext:
    study = PilotStudyManifest(
        pilot_id="p1", protocol_version="r0.5",
        pilot_case_ids=["pilot-a"], confirmatory_case_ids=["confirm-b"],
        pilot_case_ids_hash=hash_case_ids(["pilot-a"]),
        confirmatory_case_ids_hash=hash_case_ids(["confirm-b"]),
        analysis_plan_version="v1",
    )
    dataset = DatasetManifest(
        dataset_id="d1", app_id=AppId.A1, generator_version="v1",
        source_hashes=[HASH], split="pilot", case_ids=["pilot-a"],
        case_ids_hash=hash_case_ids(["pilot-a"]),
    )
    system = SystemManifest(
        system_id="s1", app_id=AppId.A1, version_id="sys-v1",
        components=[], orchestration_hash=HASH, config_hash=HASH,
    )
    environment = EnvironmentManifest(
        python_version="3.11.15", package_lock_hash=HASH, os_id="linux",
        hardware_class="cpu", git_commit="f26a185", dirty=False,
        timezone="UTC", runtime_flags={},
    )
    return build_run_context(
        study=study, dataset=dataset, system=system,
        environment=environment, case_id="pilot-a",
        condition_id="baseline", repeat_index=0,
    )


@pytest.fixture
def sink(tmp_path: Path, context: RunContext) -> JsonlEventSink:
    return JsonlEventSink(
        context, ArtifactStore(tmp_path / "artifacts"),
        tmp_path / "logs" / "events.jsonl", clock=lambda: UTC,
    )


def _emit(sink: JsonlEventSink, *, parents=(), payload=None, **kwargs):
    return sink.emit(
        event_type=kwargs.pop("event_type", EventType.MODEL_RETURNED),
        component_type=kwargs.pop("component_type", ComponentType.MODEL),
        component_id=kwargs.pop("component_id", "model-v1"),
        payload={} if payload is None else payload,
        parent_event_ids=parents,
        **kwargs,
    )


def test_protocol_contract_and_basic_emit(sink: JsonlEventSink, context: RunContext) -> None:
    assert isinstance(sink, PilotEventSink)
    event = _emit(sink, payload={"respuesta": "sí", "latencia": 3})
    assert event.sequence == 0
    assert event.event_id == "evt-00000000"
    assert event.run_id == context.run_id
    assert event.case_id == "pilot-a"
    assert event.app_id is AppId.A1
    assert event.system_version_id == "sys-v1"
    assert event.timestamp_utc == UTC
    assert event.payload_ref is not None
    assert event.payload_hash == event.payload_ref.hash
    assert event.payload_hash.value == sha256_hex(canonical_json_bytes({"respuesta": "sí", "latencia": 3}))
    assert list(iter_events(sink._path)) == [event]
    assert sink._store.get_bytes(event.payload_ref) == canonical_json_bytes({"respuesta": "sí", "latencia": 3})


def test_emit_assigns_sequence_and_parent_relationships(sink: JsonlEventSink) -> None:
    a = _emit(sink)
    b = _emit(sink, parents=[a.event_id], event_type=EventType.PROMPT_ISSUED)
    c = _emit(sink, parents=[a.event_id, b.event_id], event_type=EventType.RUN_FINISHED)
    assert [a.sequence, b.sequence, c.sequence] == [0, 1, 2]
    assert [a.event_id, b.event_id, c.event_id] == ["evt-00000000", "evt-00000001", "evt-00000002"]
    assert validate_event_log(iter_events(sink._path)).event_count == 3


def test_sink_close_returns_trace_hash(sink: JsonlEventSink) -> None:
    _emit(sink)
    _emit(sink, payload={"x": 2})
    ref = sink.close()
    assert ref == hash_file(sink._path)
    assert ref.value == sha256_hex(sink._path.read_bytes())
    assert sink.closed is True
    assert sink.close() == ref
    with pytest.raises(EventSinkError, match="después del cierre"):
        _emit(sink)


def test_identical_payloads_share_one_artifact(sink: JsonlEventSink) -> None:
    a = _emit(sink, payload={"b": 2, "a": 1})
    b = _emit(sink, payload={"a": 1, "b": 2})
    assert a.payload_ref == b.payload_ref
    assert len(list(sink._store.root.rglob(a.payload_hash.value))) == 1


def test_nullable_payload_is_canonical(sink: JsonlEventSink) -> None:
    result = sink.emit(event_type=EventType.RUN_STARTED, component_type=ComponentType.RUNTIME,
                       component_id="runtime", payload=None)
    assert sink._store.get_bytes(result.payload_ref) == b"null"


def test_error_event_with_structured_error(sink: JsonlEventSink) -> None:
    err = EventError(category="runtime", message="Error temporal.", details={"attempt": 2})
    event = _emit(sink, event_type=EventType.ERROR_OBSERVED, error=err)
    assert event.error == err
    assert list(iter_events(sink._path))[0].error == err


def test_timezone_conversion_of_clock(sink: JsonlEventSink) -> None:
    sink._clock = lambda: datetime(2026, 10, 8, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert _emit(sink).timestamp_utc == UTC


@pytest.mark.parametrize("bad", [
    {"mutation_id": "secret"}, {"nested": [{"operator_id": "hidden"}]},
    {"details": {"target_component_id": "model"}}, {"severity": "high"},
])
def test_payload_rejects_reserved_keys_without_writing(sink: JsonlEventSink, bad: dict) -> None:
    with pytest.raises(EventSinkError, match="reservadas"):
        _emit(sink, payload=bad)
    assert not sink._path.exists()


@pytest.mark.parametrize("bad", [
    {"attributes": {"mutation_id": "m1"}},
    {"attributes": {"nested": [{"severity": "high"}]}},
    {"component_id": "  "},
    {"parent_event_ids": ["unknown"]},
    {"component_type": "invalid"},
])
def test_preflight_validation_prevents_orphan_artifact(
    sink: JsonlEventSink, bad: dict
) -> None:
    inputs = {"event_type": EventType.MODEL_INVOKED, "component_type": ComponentType.MODEL,
              "component_id": "model", "payload": {"data": "not persisted"}}
    inputs.update(bad)
    with pytest.raises((EventSinkError, ValidationError)):
        sink.emit(**inputs)
    assert not list(sink._store.root.rglob("*"))
    assert not sink._path.exists()


def test_no_event_after_failed_parent_validation(sink: JsonlEventSink) -> None:
    _emit(sink)
    before = sink._path.read_bytes()
    with pytest.raises(EventSinkError):
        _emit(sink, parents=["future"], payload={"orphan": True})
    assert sink._path.read_bytes() == before
    assert len(list(iter_events(sink._path))) == 1


def test_no_close_without_any_events(sink: JsonlEventSink) -> None:
    with pytest.raises(EventSinkError, match="sin eventos"):
        sink.close()
    assert not sink.closed
    _emit(sink)
    assert sink.close()


def test_emit_before_close_then_reject_after(sink: JsonlEventSink) -> None:
    first = _emit(sink)
    sink.close()
    with pytest.raises(EventSinkError):
        _emit(sink, parents=[first.event_id])
    assert len(list(iter_events(sink._path))) == 1


def test_existing_nonempty_log_is_rejected(tmp_path: Path, context: RunContext) -> None:
    log = tmp_path / "events.jsonl"
    log.write_bytes(b"not our log")
    with pytest.raises(EventSinkError, match="vacío"):
        JsonlEventSink(context, ArtifactStore(tmp_path / "artifacts"), log)


def test_existing_empty_file_is_allowed(tmp_path: Path, context: RunContext) -> None:
    log = tmp_path / "events.jsonl"
    log.touch()
    sink = JsonlEventSink(context, ArtifactStore(tmp_path / "objects"), log, clock=lambda: UTC)
    _emit(sink)
    assert sink.close().value == sha256_hex(log.read_bytes())


def test_rejects_external_append_between_emissions(sink: JsonlEventSink) -> None:
    _emit(sink)
    before = sink._path.read_bytes()
    sink._path.write_bytes(before + b"garbage\n")
    with pytest.raises(ValueError):
        _emit(sink)
    assert sink.closed is False


def test_rejects_modified_canonical_history(sink: JsonlEventSink) -> None:
    original = _emit(sink)
    alternate = original.model_copy(update={"event_id": "externo"})
    sink._path.write_bytes(canonical_json_bytes(alternate) + b"\n")
    with pytest.raises(EventSinkError, match="bytes persistidos"):
        sink.close()


def test_rejects_missing_log_after_emit(sink: JsonlEventSink) -> None:
    _emit(sink)
    sink._path.unlink()
    with pytest.raises(EventSinkError, match="Desapareció"):
        sink.close()


def test_rejects_external_event_before_first_emit(sink: JsonlEventSink) -> None:
    sink._path.parent.mkdir(parents=True)
    sink._path.write_bytes(b"extraneous\n")
    with pytest.raises(ValueError):
        _emit(sink)


def test_rejects_invalid_context(tmp_path: Path, context: RunContext) -> None:
    with pytest.raises(EventSinkError):
        JsonlEventSink({}, ArtifactStore(tmp_path / "objs"), tmp_path / "events.jsonl")
    malformed = context.model_copy(update={"repeat_index": -1})
    with pytest.raises(EventSinkError):
        JsonlEventSink(malformed, ArtifactStore(tmp_path / "objs"), tmp_path / "events.jsonl")


def test_rejects_invalid_store(tmp_path: Path, context: RunContext) -> None:
    with pytest.raises(EventSinkError):
        JsonlEventSink(context, object(), tmp_path / "events.jsonl")


def test_rejects_invalid_clock(tmp_path: Path, context: RunContext) -> None:
    with pytest.raises(EventSinkError):
        JsonlEventSink(context, ArtifactStore(tmp_path), tmp_path / "events.jsonl", clock=3)


def test_rejects_naive_clock_timestamp(sink: JsonlEventSink) -> None:
    sink._clock = lambda: datetime(2026, 10, 8, 12, 0)
    with pytest.raises(EventSinkError):
        _emit(sink)
    assert not sink._path.exists()


def test_rejects_wrong_type_parent_container(sink: JsonlEventSink) -> None:
    with pytest.raises(EventSinkError):
        _emit(sink, parents="evt-00000000")


def test_symlink_log_rejected_at_construction(tmp_path: Path, context: RunContext) -> None:
    external = tmp_path / "external"
    external.write_bytes(b"")
    log = tmp_path / "events.jsonl"
    log.symlink_to(external)
    with pytest.raises(EventSinkError):
        JsonlEventSink(context, ArtifactStore(tmp_path / "store"), log)


def test_log_bytes_are_not_rewritten_by_close(sink: JsonlEventSink) -> None:
    _emit(sink)
    before = sink._path.read_bytes()
    sink.close()
    assert sink._path.read_bytes() == before


def test_user_mutating_returned_event_does_not_change_log(sink: JsonlEventSink) -> None:
    event = _emit(sink, payload={"value": 1})
    original = sink._path.read_bytes()
    event.attributes["mutation_id"] = "forged"
    assert sink._path.read_bytes() == original
    assert sink.close() == hash_file(sink._path)


def test_imports_do_not_depend_on_legacy() -> None:
    import inspect
    import provregress.pilot.events as module
    source = inspect.getsource(module)
    assert "import llmtestlab" not in source
    assert "from llmtestlab" not in source


def test_concurrent_emissions_share_contiguous_sequence(sink: JsonlEventSink) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        events = list(pool.map(lambda number: _emit(sink, payload={"n": number}), range(24)))
    assert len({event.event_id for event in events}) == 24
    assert sorted(event.sequence for event in events) == list(range(24))
    assert validate_event_log(iter_events(sink._path)).event_count == 24
    assert sink.close() == hash_file(sink._path)


def test_concurrent_close_and_emit_serializes_without_corruption(sink: JsonlEventSink) -> None:
    _emit(sink)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_close = pool.submit(sink.close)
        future_emit = pool.submit(_emit, sink)
        result_close = future_close.result()
        try:
            future_emit.result()
        except EventSinkError:
            pass
    assert validate_event_log(iter_events(sink._path)).event_count in (1, 2)
    if sink._path.read_bytes() and result_close != hash_file(sink._path):
        # Si la emisión ganó la carrera, close verificó esos mismos bytes.
        raise AssertionError("El cierre debe reflejar los bytes definitivos.")

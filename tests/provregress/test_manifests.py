"""Pruebas de integridad para los contratos P0 de R0.7-C3."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.schema import AppId, ComponentType, HashRef
from provregress.schema.manifests import (
    ComponentManifest, DatasetManifest, EnvironmentManifest,
    EvaluatorManifest, MutationManifest, PilotStudyManifest, RunManifest,
    RunManifestError, SystemManifest, build_run_manifest, finalize_run_manifest,
)
from provregress.storage.hashing import hash_case_ids, hash_file, hash_model
from provregress.pilot.context import RunContext, build_run_context
from provregress.pilot.events import EventSinkError, JsonlEventSink
from provregress.schema.common import RunStatus
from provregress.schema.events import EventType
from provregress.storage.artifacts import ArtifactStore

HASH = HashRef(algorithm="sha256", value="a" * 64)


def dataset() -> dict[str, object]:
    return dict(dataset_id="d1", app_id=AppId.A1, generator_version="g1",
                source_hashes=[HASH], split="pilot", case_ids=["a", "b"],
                case_ids_hash=hash_case_ids(["a", "b"]))


def component(component_id: str = "c1") -> dict[str, object]:
    return dict(component_id=component_id, component_type=ComponentType.MODEL,
                implementation_version="v1", config_hash=HASH)


def system() -> dict[str, object]:
    return dict(system_id="s1", app_id=AppId.A1, version_id="v1",
                components=[component()], orchestration_hash=HASH, config_hash=HASH)


def evaluator() -> dict[str, object]:
    return dict(evaluator_id="e1", evaluator_type="deterministic",
                position_config={"order": ["baseline", "candidate"], "seed": 1})


def environment() -> dict[str, object]:
    return dict(python_version="3.11.15", package_lock_hash=HASH, os_id="linux",
                hardware_class="cpu", git_commit="259f14b", dirty=False,
                timezone="UTC", runtime_flags={"repeat": 1, "stable": True})


def study() -> dict[str, object]:
    return dict(pilot_id="p1", protocol_version="r0.5",
                pilot_case_ids=["a", "b"], confirmatory_case_ids=["c", "d"],
                pilot_case_ids_hash=hash_case_ids(["a", "b"]),
                confirmatory_case_ids_hash=hash_case_ids(["c", "d"]),
                analysis_plan_version="v1")


MANIFESTS = [
    (DatasetManifest, dataset, "pilot-dataset-v1"),
    (SystemManifest, system, "pilot-system-v1"),
    (EvaluatorManifest, evaluator, "pilot-evaluator-v1"),
    (EnvironmentManifest, environment, "pilot-env-v1"),
    (PilotStudyManifest, study, "pilot-study-v1"),
]


@pytest.mark.parametrize("model,payload,version", MANIFESTS)
def test_manifest_roundtrip_and_version(model, payload, version) -> None:
    instance = model.model_validate(payload())
    assert instance.schema_version == version
    assert model.model_validate_json(instance.model_dump_json()) == instance
    assert hash_model(instance) == hash_model(instance)


@pytest.mark.parametrize("model,payload", [(a, b) for a, b, _ in MANIFESTS] + [(ComponentManifest, component)])
def test_manifests_reject_extra_fields(model, payload) -> None:
    params = payload()
    params["unexpected"] = "x"
    with pytest.raises(ValidationError):
        model.model_validate(params)
    assert model.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("model,payload,_", MANIFESTS)
def test_manifests_reject_unrecognized_versions(model, payload, _) -> None:
    params = payload()
    params["schema_version"] = "unknown"
    with pytest.raises(ValidationError):
        model.model_validate(params)


def test_dataset_accepts_confirmatory_split() -> None:
    params = dataset()
    params["split"] = "confirmatory"
    assert DatasetManifest.model_validate(params).split == "confirmatory"


@pytest.mark.parametrize("case_ids", [["b", "a"], ["a", "a"], ["a", " "]])
def test_dataset_rejects_noncanonical_case_ids(case_ids: list[str]) -> None:
    params = dataset()
    params["case_ids"] = case_ids
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(params)


def test_case_hashes_must_match_canonical_ids() -> None:
    params = dataset()
    params["case_ids_hash"] = HASH
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(params)


def test_dataset_rejects_unexpected_split() -> None:
    params = dataset()
    params["split"] = "training"
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(params)


def test_dataset_rejects_blank_id() -> None:
    params = dataset()
    params["dataset_id"] = "  "
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(params)


def test_component_accepts_optional_artifact_hash() -> None:
    params = component()
    params["artifact_hash"] = HASH
    assert ComponentManifest.model_validate(params).artifact_hash == HASH


def test_system_component_ids_are_unique() -> None:
    params = system()
    params["components"] = [component(), component()]
    with pytest.raises(ValidationError):
        SystemManifest.model_validate(params)


def test_component_rejects_unknown_type() -> None:
    params = component()
    params["component_type"] = "not-a-component"
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(params)


def test_evaluator_accepts_optional_provenance_hashes() -> None:
    params = evaluator()
    params["rubric_hash"] = HASH
    params["threshold_config_hash"] = HASH
    assert EvaluatorManifest.model_validate(params).rubric_hash == HASH


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_evaluator_rejects_nonfinite_position_config(bad: float) -> None:
    params = evaluator()
    params["position_config"] = {"score": bad}
    with pytest.raises(ValidationError):
        EvaluatorManifest.model_validate(params)


def test_environment_preserves_dirty_state() -> None:
    params = environment()
    params["dirty"] = True
    assert EnvironmentManifest.model_validate(params).dirty is True


@pytest.mark.parametrize("dirty", ["false", 0, 1])
def test_environment_rejects_nonstrict_dirty(dirty: object) -> None:
    params = environment()
    params["dirty"] = dirty
    with pytest.raises(ValidationError):
        EnvironmentManifest.model_validate(params)


def test_environment_rejects_nonfinite_runtime_flags() -> None:
    params = environment()
    params["runtime_flags"] = {"temperature": float("nan")}
    with pytest.raises(ValidationError):
        EnvironmentManifest.model_validate(params)


def test_pilot_and_confirmatory_case_sets_must_be_disjoint() -> None:
    params = study()
    params["confirmatory_case_ids"] = ["b", "d"]
    params["confirmatory_case_ids_hash"] = hash_case_ids(["b", "d"])
    with pytest.raises(ValidationError):
        PilotStudyManifest.model_validate(params)


@pytest.mark.parametrize("field", ["pilot_case_ids", "confirmatory_case_ids"])
def test_study_rejects_duplicate_case_ids(field: str) -> None:
    params = study()
    params[field] = ["a", "a"]
    with pytest.raises(ValidationError):
        PilotStudyManifest.model_validate(params)


@pytest.mark.parametrize("field", ["pilot_case_ids_hash", "confirmatory_case_ids_hash"])
def test_study_rejects_wrong_case_hash(field: str) -> None:
    params = study()
    params[field] = HASH
    with pytest.raises(ValidationError):
        PilotStudyManifest.model_validate(params)


def test_study_hash_is_independent_of_case_order() -> None:
    params = study()
    params["pilot_case_ids"] = ["b", "a"]
    assert PilotStudyManifest.model_validate(params).pilot_case_ids_hash == hash_case_ids(["a", "b"])


def test_study_requires_analysis_plan_version() -> None:
    params = study()
    del params["analysis_plan_version"]
    with pytest.raises(ValidationError):
        PilotStudyManifest.model_validate(params)


# R0.7-C10: cierre reproducible de una ejecución piloto.

START = datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 8, 17, 1, tzinfo=timezone.utc)


@pytest.fixture
def run_context() -> RunContext:
    study_obj = PilotStudyManifest.model_validate(study())
    dataset_obj = DatasetManifest.model_validate(dataset())
    system_obj = SystemManifest.model_validate(system())
    environment_obj = EnvironmentManifest.model_validate(environment())
    return build_run_context(
        study=study_obj, dataset=dataset_obj, system=system_obj,
        environment=environment_obj, case_id="a", condition_id="baseline",
        repeat_index=0, run_id="run-c10",
    )


@pytest.fixture
def run_sink(tmp_path: Path, run_context: RunContext) -> JsonlEventSink:
    return JsonlEventSink(
        run_context, ArtifactStore(tmp_path / "artifacts"),
        tmp_path / "events.jsonl", clock=lambda: START,
    )


def _emit_c10(sink: JsonlEventSink) -> None:
    sink.emit(
        event_type=EventType.RUN_STARTED,
        component_type=ComponentType.RUNTIME,
        component_id="runtime", payload={"fase": "piloto"},
    )


@pytest.fixture
def running_manifest(run_context: RunContext) -> RunManifest:
    return build_run_manifest(
        context=run_context, started_at=START,
        evaluators=[EvaluatorManifest.model_validate(evaluator())],
    )


def test_run_manifest_is_bound_to_run_context(
    running_manifest: RunManifest, run_context: RunContext,
) -> None:
    assert running_manifest.schema_version == "pilot-run-v1"
    assert running_manifest.run_id == run_context.run_id
    assert running_manifest.study_id == run_context.study_id
    assert running_manifest.app_id == run_context.app_id
    assert running_manifest.case_id == run_context.case_id
    assert running_manifest.condition_id == run_context.condition_id
    assert running_manifest.repeat_index == run_context.repeat_index
    assert running_manifest.system_manifest_hash == run_context.system_manifest_hash
    assert running_manifest.dataset_manifest_hash == run_context.dataset_manifest_hash
    assert running_manifest.environment_manifest_hash == run_context.environment_manifest_hash
    assert running_manifest.evaluator_manifest_hashes == [
        hash_model(EvaluatorManifest.model_validate(evaluator()))
    ]
    assert running_manifest.trace_hash is None
    assert running_manifest.ended_at is None
    assert running_manifest.status is RunStatus.RUNNING


def test_run_manifest_roundtrip_schema_is_strict(running_manifest: RunManifest) -> None:
    assert RunManifest.model_validate_json(running_manifest.model_dump_json()) == running_manifest
    assert RunManifest.model_json_schema()["additionalProperties"] is False
    assert hash_model(running_manifest) == hash_model(
        RunManifest.model_validate(running_manifest.model_dump(mode="python"))
    )


@pytest.mark.parametrize("field,value", [
    ("unexpected", "secret"),
    ("schema_version", "pilot-run-v2"),
    ("run_id", " "),
    ("study_id", ""),
    ("case_id", None),
    ("condition_id", 10),
    ("repeat_index", -1),
    ("repeat_index", True),
    ("repeat_index", "0"),
    ("app_id", "a4_unknown"),
    ("status", "succeeded"),
    ("evaluator_manifest_hashes", ["fake"]),
    ("dataset_manifest_hash", "invalid"),
])
def test_run_manifest_rejects_bad_fields(
    running_manifest: RunManifest, field: str, value: object,
) -> None:
    with pytest.raises(ValidationError):
        RunManifest.model_validate(running_manifest.model_dump(mode="python") | {field: value})


def test_run_manifest_end_cannot_precede_start(running_manifest: RunManifest) -> None:
    payload = running_manifest.model_dump(mode="python")
    payload.update({"status": RunStatus.FAILED, "ended_at": START - timedelta(seconds=1)})
    with pytest.raises(ValidationError, match="preceder"):
        RunManifest.model_validate(payload)


@pytest.mark.parametrize("field", ["started_at", "ended_at"])
def test_run_manifest_requires_aware_datetimes(
    running_manifest: RunManifest, field: str,
) -> None:
    payload = running_manifest.model_dump(mode="python")
    if field == "ended_at":
        payload["status"] = RunStatus.FAILED
    payload[field] = datetime(2026, 10, 8, 17, 0)
    with pytest.raises(ValidationError):
        RunManifest.model_validate(payload)


def test_run_manifest_normalizes_offsets_to_utc(running_manifest: RunManifest) -> None:
    payload = running_manifest.model_dump(mode="python")
    payload["started_at"] = datetime(2026, 10, 8, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    normalized = RunManifest.model_validate(payload)
    assert normalized.started_at == START
    assert normalized.started_at.tzinfo is timezone.utc


@pytest.mark.parametrize("status", [RunStatus.PLANNED, RunStatus.RUNNING])
def test_run_manifest_active_status_rejects_trace_or_end(
    running_manifest: RunManifest, status: RunStatus,
) -> None:
    for extra in ({"ended_at": END}, {"trace_hash": HASH}):
        with pytest.raises(ValidationError):
            RunManifest.model_validate(running_manifest.model_dump(mode="python") | {
                "status": status, **extra,
            })


@pytest.mark.parametrize("status", [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.REJECTED])
def test_terminal_status_requires_end(running_manifest: RunManifest, status: RunStatus) -> None:
    with pytest.raises(ValidationError):
        RunManifest.model_validate(running_manifest.model_dump(mode="python") | {"status": status})


def test_succeeded_requires_closed_trace_hash(running_manifest: RunManifest) -> None:
    with pytest.raises(ValidationError):
        RunManifest.model_validate(running_manifest.model_dump(mode="python") | {
            "status": RunStatus.SUCCEEDED, "ended_at": END,
        })


def test_failed_and_rejected_may_have_no_trace_before_logging(
    running_manifest: RunManifest,
) -> None:
    for status in (RunStatus.FAILED, RunStatus.REJECTED):
        candidate = RunManifest.model_validate(running_manifest.model_dump(mode="python") | {
            "status": status, "ended_at": END,
        })
        assert candidate.trace_hash is None


def test_finalization_closes_and_hashes_exact_jsonl(
    run_sink: JsonlEventSink, running_manifest: RunManifest,
) -> None:
    _emit_c10(run_sink)
    _emit_c10(run_sink)
    before = run_sink._path.read_bytes()
    finished = finalize_run_manifest(
        manifest=running_manifest, sink=run_sink,
        ended_at=END, status=RunStatus.SUCCEEDED,
    )
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.trace_hash == hash_file(run_sink._path)
    assert finished.trace_hash == run_sink.close()
    assert finished.ended_at == END
    assert run_sink._path.read_bytes() == before
    assert run_sink.closed
    assert running_manifest.status is RunStatus.RUNNING
    assert running_manifest.trace_hash is None
    assert RunManifest.model_validate_json(finished.model_dump_json()) == finished
    assert hash_model(finished) != hash_model(running_manifest)


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.REJECTED])
def test_finalization_of_terminal_error_runs_has_trace(
    run_sink: JsonlEventSink, running_manifest: RunManifest, status: RunStatus,
) -> None:
    _emit_c10(run_sink)
    final = finalize_run_manifest(manifest=running_manifest, sink=run_sink,
                                  ended_at=END, status=status)
    assert final.status is status
    assert final.trace_hash == hash_file(run_sink._path)


def test_finalization_end_equal_to_start_is_allowed(
    run_sink: JsonlEventSink, running_manifest: RunManifest,
) -> None:
    _emit_c10(run_sink)
    final = finalize_run_manifest(manifest=running_manifest, sink=run_sink,
                                  ended_at=START, status=RunStatus.SUCCEEDED)
    assert final.ended_at == START


def test_finalization_normalizes_ended_at_utc(
    run_sink: JsonlEventSink, running_manifest: RunManifest,
) -> None:
    _emit_c10(run_sink)
    end_local = datetime(2026, 10, 8, 12, 1, tzinfo=timezone(timedelta(hours=-5)))
    final = finalize_run_manifest(manifest=running_manifest, sink=run_sink,
                                  ended_at=end_local, status=RunStatus.SUCCEEDED)
    assert final.ended_at == END
    assert final.ended_at.tzinfo is timezone.utc


@pytest.mark.parametrize("status", [RunStatus.PLANNED, RunStatus.RUNNING, "failed", None])
def test_finalization_rejects_nonterminal_status_without_closing(
    run_sink: JsonlEventSink, running_manifest: RunManifest, status: object,
) -> None:
    _emit_c10(run_sink)
    with pytest.raises(RunManifestError):
        finalize_run_manifest(manifest=running_manifest, sink=run_sink,
                              ended_at=END, status=status)
    assert not run_sink.closed


@pytest.mark.parametrize("end", [START - timedelta(microseconds=1),
                                      datetime(2026, 10, 8, 17, 1), None, "later"])
def test_finalization_rejects_invalid_time_without_closing(
    run_sink: JsonlEventSink, running_manifest: RunManifest, end: object,
) -> None:
    _emit_c10(run_sink)
    with pytest.raises(RunManifestError):
        finalize_run_manifest(manifest=running_manifest, sink=run_sink,
                              ended_at=end, status=RunStatus.FAILED)
    assert not run_sink.closed


@pytest.mark.parametrize("change", [
    {"run_id": "other-run"}, {"case_id": "b"},
    {"condition_id": "candidate"}, {"repeat_index": 2},
    {"system_manifest_hash": HASH}, {"dataset_manifest_hash": HASH},
    {"environment_manifest_hash": HASH}, {"study_id": "wrong-study"},
    {"app_id": AppId.A2},
])
def test_finalization_rejects_identity_mismatch_before_closing(
    run_sink: JsonlEventSink, running_manifest: RunManifest, change: dict[str, object],
) -> None:
    _emit_c10(run_sink)
    forged = RunManifest.model_validate(running_manifest.model_dump(mode="python") | change)
    with pytest.raises(RunManifestError, match="otra identidad"):
        finalize_run_manifest(manifest=forged, sink=run_sink,
                              ended_at=END, status=RunStatus.SUCCEEDED)
    assert not run_sink.closed


def test_finalization_rejects_other_sink_without_closing(
    run_sink: JsonlEventSink, running_manifest: RunManifest,
) -> None:
    _emit_c10(run_sink)
    with pytest.raises(RunManifestError):
        finalize_run_manifest(manifest=running_manifest, sink=object(),
                              ended_at=END, status=RunStatus.SUCCEEDED)
    assert not run_sink.closed


def test_finalization_revalidates_forged_manifest(
    run_sink: JsonlEventSink, running_manifest: RunManifest,
) -> None:
    _emit_c10(run_sink)
    forged = running_manifest.model_copy(update={"repeat_index": -1})
    with pytest.raises(RunManifestError):
        finalize_run_manifest(manifest=forged, sink=run_sink,
                              ended_at=END, status=RunStatus.SUCCEEDED)
    assert not run_sink.closed


def test_finalization_rejects_empty_log_without_closing(
    run_sink: JsonlEventSink, running_manifest: RunManifest,
) -> None:
    with pytest.raises(EventSinkError):
        finalize_run_manifest(manifest=running_manifest, sink=run_sink,
                              ended_at=END, status=RunStatus.SUCCEEDED)
    assert not run_sink.closed
    assert running_manifest.trace_hash is None


def test_finalization_rejects_tampered_log(
    run_sink: JsonlEventSink, running_manifest: RunManifest,
) -> None:
    _emit_c10(run_sink)
    run_sink._path.write_bytes(run_sink._path.read_bytes() + b"not-json\n")
    with pytest.raises(ValueError):
        finalize_run_manifest(manifest=running_manifest, sink=run_sink,
                              ended_at=END, status=RunStatus.SUCCEEDED)
    assert not run_sink.closed
    assert running_manifest.trace_hash is None


def test_manifest_cannot_be_finalized_twice(
    run_sink: JsonlEventSink, running_manifest: RunManifest,
) -> None:
    _emit_c10(run_sink)
    finished = finalize_run_manifest(manifest=running_manifest, sink=run_sink,
                                     ended_at=END, status=RunStatus.SUCCEEDED)
    with pytest.raises(RunManifestError, match="running"):
        finalize_run_manifest(manifest=finished, sink=run_sink,
                              ended_at=END, status=RunStatus.SUCCEEDED)


def test_builder_accepts_optional_mutation_hash_without_leaking_it_to_events(
    run_context: RunContext,
) -> None:
    manifest = build_run_manifest(context=run_context, started_at=START,
                                  mutation_manifest_hash=HASH)
    assert manifest.mutation_manifest_hash == HASH
    assert "mutation_id" not in RunManifest.model_fields
    assert "mutation_manifest_hash" not in RunContext.model_fields


def test_builder_handles_multiple_evaluators(run_context: RunContext) -> None:
    first = EvaluatorManifest.model_validate(evaluator())
    second = first.model_copy(update={"evaluator_id": "e2"})
    manifest = build_run_manifest(context=run_context, started_at=START,
                                  evaluators=[first, second])
    assert manifest.evaluator_manifest_hashes == [hash_model(first), hash_model(second)]


def test_builder_rejects_duplicate_evaluator_ids(run_context: RunContext) -> None:
    first = EvaluatorManifest.model_validate(evaluator())
    with pytest.raises(RunManifestError, match="identificador"):
        build_run_manifest(context=run_context, started_at=START, evaluators=[first, first])


@pytest.mark.parametrize("evaluators", ["invalid", None, ["bad"], [object()]])
def test_builder_rejects_invalid_evaluators(
    run_context: RunContext, evaluators: object,
) -> None:
    with pytest.raises(RunManifestError):
        build_run_manifest(context=run_context, started_at=START, evaluators=evaluators)


def test_builder_rejects_forged_evaluator(run_context: RunContext) -> None:
    first = EvaluatorManifest.model_validate(evaluator())
    forged = first.model_copy(update={"evaluator_id": " "})
    with pytest.raises(RunManifestError):
        build_run_manifest(context=run_context, started_at=START, evaluators=[forged])


def test_builder_rejects_wrong_context_or_mutation_hash(run_context: RunContext) -> None:
    with pytest.raises(RunManifestError):
        build_run_manifest(context={}, started_at=START)
    with pytest.raises(RunManifestError):
        build_run_manifest(context=run_context, started_at=START,
                           mutation_manifest_hash="a" * 64)


def test_builder_rejects_naive_started_at(run_context: RunContext) -> None:
    with pytest.raises(RunManifestError):
        build_run_manifest(context=run_context,
                           started_at=datetime(2026, 10, 8, 17, 0))


def test_builder_no_new_events_or_providers(run_context: RunContext) -> None:
    import inspect
    from provregress.schema import manifests as module
    code = inspect.getsource(module)
    assert "import llmtestlab" not in code
    assert "from llmtestlab" not in code
    assert not any(s in RunManifest.model_fields for s in (
        "target_component_id", "severity", "root_cause", "evaluator_verdict",
    ))


# Cierre del conjunto de schemas R0.7: MutationManifest es solo declarativo.


def _mutation(severity: str = "identity", **extra: object) -> dict[str, object]:
    payload = dict(mutation_id="m1", operator_id="op1", operator_version="v1",
                   severity=severity, before_hash=HASH, after_hash=HASH,
                   parameters={"seed": 3, "enabled": True})
    payload.update(extra)
    return payload


def test_mutation_manifest_identity_allows_no_target() -> None:
    manifest = MutationManifest.model_validate(_mutation())
    assert manifest.target_component_id is None
    assert manifest.target_relation_id is None
    assert manifest.severity == "identity"
    assert manifest.schema_version == "pilot-mutation-v1"
    assert MutationManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_mutation_manifest_evaluator_control_allows_no_target() -> None:
    assert MutationManifest.model_validate(_mutation("evaluator_control")).target_relation_id is None


@pytest.mark.parametrize("severity", ["low", "medium", "high"])
def test_non_identity_mutation_requires_target(severity: str) -> None:
    with pytest.raises(ValidationError, match="objetivo"):
        MutationManifest.model_validate(_mutation(severity))


@pytest.mark.parametrize("key", ["target_component_id", "target_relation_id"])
def test_mutation_target_can_be_component_or_relation(key: str) -> None:
    manifest = MutationManifest.model_validate(_mutation("medium", **{key: "target-1"}))
    assert getattr(manifest, key) == "target-1"


@pytest.mark.parametrize("field,value", [
    ("severity", "critical"),
    ("schema_version", "pilot-mutation-v2"),
    ("target_component_id", "  "),
    ("parameters", {"temperature": float("nan")}),
    ("parameters", {"x": {"bad": float("inf")}}),
    ("extra", True),
])
def test_mutation_manifest_rejects_undeclared_or_invalid_fields(
    field: str, value: object,
) -> None:
    with pytest.raises(ValidationError):
        MutationManifest.model_validate(_mutation(**{field: value}))


def test_mutation_manifest_schema_is_strict_and_hashable() -> None:
    manifest = MutationManifest.model_validate(_mutation("low", target_component_id="model"))
    assert MutationManifest.model_json_schema()["additionalProperties"] is False
    assert hash_model(manifest) == hash_model(MutationManifest.model_validate(manifest.model_dump()))


def test_mutation_hash_can_be_bound_only_as_metadata(run_context: RunContext) -> None:
    mutation = MutationManifest.model_validate(_mutation("high", target_relation_id="r1"))
    manifest = build_run_manifest(
        context=run_context, started_at=START, mutation_manifest_hash=hash_model(mutation),
    )
    assert manifest.mutation_manifest_hash == hash_model(mutation)
    assert "mutation_id" not in RunContext.model_fields

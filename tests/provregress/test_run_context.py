"""Pruebas del gate R0.7-C5: identidad y procedencia sin contaminación."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from provregress.pilot import PilotContaminationError, UnknownPilotCaseError
from provregress.pilot.context import RunContext, RunContextError, build_run_context
from provregress.schema import AppId, ComponentType, HashRef
from provregress.schema.manifests import (
    ComponentManifest,
    DatasetManifest,
    EnvironmentManifest,
    PilotStudyManifest,
    SystemManifest,
)
from provregress.storage.hashing import hash_case_ids, hash_model

HASH = HashRef(algorithm="sha256", value="a" * 64)


@pytest.fixture
def study() -> PilotStudyManifest:
    return PilotStudyManifest(
        pilot_id="pilot-v1",
        protocol_version="r0.5",
        pilot_case_ids=["pilot-a", "pilot-b"],
        confirmatory_case_ids=["confirm-a"],
        pilot_case_ids_hash=hash_case_ids(["pilot-a", "pilot-b"]),
        confirmatory_case_ids_hash=hash_case_ids(["confirm-a"]),
        analysis_plan_version="v1",
    )


@pytest.fixture
def dataset() -> DatasetManifest:
    return DatasetManifest(
        dataset_id="data-v1",
        app_id=AppId.A1,
        generator_version="generator-v1",
        source_hashes=[HASH],
        split="pilot",
        case_ids=["pilot-a", "pilot-b"],
        case_ids_hash=hash_case_ids(["pilot-a", "pilot-b"]),
    )


@pytest.fixture
def system() -> SystemManifest:
    return SystemManifest(
        system_id="system-v1",
        app_id=AppId.A1,
        version_id="v1",
        components=[ComponentManifest(
            component_id="model", component_type=ComponentType.MODEL,
            implementation_version="1", config_hash=HASH,
        )],
        orchestration_hash=HASH,
        config_hash=HASH,
    )


@pytest.fixture
def environment() -> EnvironmentManifest:
    return EnvironmentManifest(
        python_version="3.11.15",
        package_lock_hash=HASH,
        os_id="linux",
        hardware_class="cpu",
        git_commit="259f14b",
        dirty=False,
        timezone="UTC",
        runtime_flags={"threads": 1, "seed": 13},
    )


@pytest.fixture
def inputs(study, dataset, system, environment) -> dict[str, object]:
    return dict(
        study=study,
        dataset=dataset,
        system=system,
        environment=environment,
        case_id="pilot-a",
        condition_id="baseline",
        repeat_index=0,
    )


def test_context_binds_identity_and_manifest_hashes(inputs: dict[str, object]) -> None:
    context = build_run_context(**inputs)
    assert context.study_id == "pilot-v1"
    assert context.app_id is AppId.A1
    assert context.case_id == "pilot-a"
    assert context.condition_id == "baseline"
    assert context.repeat_index == 0
    assert context.system_version_id == "v1"
    for name, manifest in [
        ("study", "study_manifest_hash"),
        ("dataset", "dataset_manifest_hash"),
        ("system", "system_manifest_hash"),
        ("environment", "environment_manifest_hash"),
    ]:
        assert getattr(context, manifest) == hash_model(inputs[name])
        assert hash_model(inputs[name]) == getattr(context, manifest)
    assert context.run_id.startswith("run-")
    assert len(context.run_id) == 68


def test_context_determinism(inputs: dict[str, object]) -> None:
    left = build_run_context(**inputs)
    right = build_run_context(**inputs)
    assert left == right
    assert hash_model(left) == hash_model(right)


def test_context_determinism_across_canonical_mapping_order(inputs: dict[str, object]) -> None:
    environment = inputs["environment"]
    alternate = environment.model_copy(
        update={"runtime_flags": {"seed": 13, "threads": 1}}
    )
    assert build_run_context(**inputs) == build_run_context(**(inputs | {"environment": alternate}))


@pytest.mark.parametrize("update", [
    {"case_id": "pilot-b"},
    {"condition_id": "candidate"},
    {"repeat_index": 1},
])
def test_distinct_runs_have_distinct_derived_ids(
    inputs: dict[str, object], update: dict[str, object]
) -> None:
    assert build_run_context(**inputs).run_id != build_run_context(**(inputs | update)).run_id


def test_changed_environment_changes_identity(inputs: dict[str, object]) -> None:
    environment = inputs["environment"]
    changed = environment.model_copy(update={"dirty": True})
    assert build_run_context(**inputs).run_id != build_run_context(
        **(inputs | {"environment": changed})
    ).run_id


def test_explicit_run_id_is_preserved(inputs: dict[str, object]) -> None:
    assert build_run_context(**inputs, run_id="pilot-run-007").run_id == "pilot-run-007"


@pytest.mark.parametrize("case_id,error", [
    ("confirm-a", PilotContaminationError),
    ("unknown", UnknownPilotCaseError),
    (" pilot-a", UnknownPilotCaseError),
    ("", UnknownPilotCaseError),
    (3, UnknownPilotCaseError),
])
def test_firewall_rejects_before_building_context(
    inputs: dict[str, object], case_id: object, error: type[Exception], monkeypatch
) -> None:
    calls: list[str] = []

    def blocked_hash(_manifest: object) -> None:
        calls.append("hash")
        raise AssertionError("No debe calcularse un hash para un caso prohibido.")

    monkeypatch.setattr("provregress.pilot.context.hash_model", blocked_hash)
    with pytest.raises(error):
        build_run_context(**(inputs | {"case_id": case_id}))
    assert calls == []


def test_dataset_rejects_confirmatory_split(inputs: dict[str, object]) -> None:
    dataset = inputs["dataset"].model_copy(update={"split": "confirmatory"})
    with pytest.raises(RunContextError, match="split piloto"):
        build_run_context(**(inputs | {"dataset": dataset}))


def test_dataset_requires_case_membership(inputs: dict[str, object]) -> None:
    dataset = inputs["dataset"].model_copy(update={
        "case_ids": ["pilot-b"],
        "case_ids_hash": hash_case_ids(["pilot-b"]),
    })
    with pytest.raises(RunContextError, match="no está incluido"):
        build_run_context(**(inputs | {"dataset": dataset}))


def test_dataset_must_not_contain_confirmatory_cases(inputs: dict[str, object]) -> None:
    dataset = inputs["dataset"].model_copy(update={
        "case_ids": ["confirm-a", "pilot-a"],
        "case_ids_hash": hash_case_ids(["confirm-a", "pilot-a"]),
    })
    with pytest.raises(RunContextError, match="no pertenecen"):
        build_run_context(**(inputs | {"dataset": dataset}))


def test_dataset_must_not_contain_unknown_cases(inputs: dict[str, object]) -> None:
    dataset = inputs["dataset"].model_copy(update={
        "case_ids": ["external", "pilot-a"],
        "case_ids_hash": hash_case_ids(["external", "pilot-a"]),
    })
    with pytest.raises(RunContextError, match="no pertenecen"):
        build_run_context(**(inputs | {"dataset": dataset}))


def test_dataset_and_system_app_id_must_agree(inputs: dict[str, object]) -> None:
    system = inputs["system"].model_copy(update={"app_id": AppId.A2})
    with pytest.raises(RunContextError, match="aplicación"):
        build_run_context(**(inputs | {"system": system}))


@pytest.mark.parametrize("condition_id", ["", "  ", "\n", None, 5, b"baseline"])
def test_condition_id_rejects_blanks_or_wrong_type(
    inputs: dict[str, object], condition_id: object
) -> None:
    with pytest.raises(RunContextError):
        build_run_context(**(inputs | {"condition_id": condition_id}))


@pytest.mark.parametrize("repeat_index", [-1, True, False, 1.0, "1", None])
def test_repeat_index_is_strict_nonnegative_integer(
    inputs: dict[str, object], repeat_index: object
) -> None:
    with pytest.raises(RunContextError):
        build_run_context(**(inputs | {"repeat_index": repeat_index}))


@pytest.mark.parametrize("run_id", ["", "  ", 0, b"run"])
def test_explicit_run_id_is_nonblank_text(
    inputs: dict[str, object], run_id: object
) -> None:
    with pytest.raises(RunContextError):
        build_run_context(**(inputs | {"run_id": run_id}))


@pytest.mark.parametrize("name", ["study", "dataset", "system", "environment"])
def test_revalidates_mutated_manifests(inputs: dict[str, object], name: str) -> None:
    original = inputs[name]
    if name == "study":
        changed = original.model_copy(update={"pilot_case_ids_hash": HASH})
    elif name == "dataset":
        changed = original.model_copy(update={"case_ids_hash": HASH})
    elif name == "system":
        changed = original.model_copy(update={"version_id": "  "})
    else:
        changed = original.model_copy(update={"python_version": "  "})
    with pytest.raises((RunContextError, ValueError)):
        build_run_context(**(inputs | {name: changed}))


@pytest.mark.parametrize("name", ["dataset", "system", "environment"])
def test_rejects_incorrect_manifest_type(inputs: dict[str, object], name: str) -> None:
    with pytest.raises(RunContextError):
        build_run_context(**(inputs | {name: inputs["study"]}))


def test_context_model_is_frozen(inputs: dict[str, object]) -> None:
    context = build_run_context(**inputs)
    with pytest.raises(ValidationError):
        context.condition_id = "candidate"
    with pytest.raises(ValidationError):
        context.dataset_manifest_hash.value = "0" * 64


def test_context_hashes_are_not_aliases_to_external_data(inputs: dict[str, object]) -> None:
    context = build_run_context(**inputs)
    stored_hash = context.environment_manifest_hash.value
    inputs["environment"].runtime_flags["threads"] = 8
    assert context.environment_manifest_hash.value == stored_hash


def test_run_context_json_roundtrip_is_strict(inputs: dict[str, object]) -> None:
    context = build_run_context(**inputs)
    assert RunContext.model_validate_json(context.model_dump_json()) == context
    assert RunContext.model_json_schema()["additionalProperties"] is False
    with pytest.raises(ValidationError):
        RunContext.model_validate(context.model_dump() | {"unexpected": True})


def test_context_excludes_mutation_and_outcome_labels(inputs: dict[str, object]) -> None:
    context = build_run_context(**inputs)
    forbidden = {
        "mutation_id", "operator_id", "target_component_id", "severity",
        "root_cause", "output_label", "evaluator_verdict", "outcome",
    }
    assert not forbidden.intersection(RunContext.model_fields)
    assert not forbidden.intersection(context.model_dump())


def test_no_runtime_or_provider_is_imported() -> None:
    import inspect
    import provregress.pilot.context as context_module

    source = inspect.getsource(context_module)
    assert "from llmtestlab" not in source
    assert "import llmtestlab" not in source

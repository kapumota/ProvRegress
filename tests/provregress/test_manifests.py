"""Pruebas de integridad para los contratos P0 de R0.7-C3."""

import pytest
from pydantic import ValidationError

from provregress.schema import AppId, ComponentType, HashRef
from provregress.schema.manifests import (
    ComponentManifest, DatasetManifest, EnvironmentManifest,
    EvaluatorManifest, PilotStudyManifest, SystemManifest,
)
from provregress.storage.hashing import hash_case_ids, hash_model

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

"""Pruebas de los contratos comunes de R0.7-C1."""

import pytest
from pydantic import ValidationError

from provregress.schema import AppId, ArtifactRef, ComponentType, HashRef, RunStatus


DIGEST = "a" * 64
COMPONENT_VALUES = {
    "input_case",
    "system_version",
    "prompt",
    "model",
    "retriever",
    "corpus",
    "chunk",
    "ranker",
    "agent",
    "tool",
    "tool_call",
    "tool_result",
    "schema",
    "generated_artifact",
    "claim",
    "citation",
    "evaluator",
    "evaluation",
    "outcome",
    "failure",
    "runtime",
}


def test_app_ids_match_frozen_vocabulary() -> None:
    assert {item.value for item in AppId} == {
        "a1_extraction",
        "a2_rag",
        "a3_tools",
    }


def test_component_types_match_all_21_frozen_values() -> None:
    assert len(ComponentType) == 21
    assert {item.value for item in ComponentType} == COMPONENT_VALUES


def test_run_status_matches_frozen_values() -> None:
    assert {item.value for item in RunStatus} == {
        "planned",
        "running",
        "succeeded",
        "failed",
        "rejected",
    }


def test_hash_ref_accepts_lowercase_sha256() -> None:
    ref = HashRef(algorithm="sha256", value=DIGEST)
    assert ref.value == DIGEST
    assert ref.model_dump() == {"algorithm": "sha256", "value": DIGEST}


@pytest.mark.parametrize(
    "payload",
    [
        {"algorithm": "sha1", "value": DIGEST},
        {"algorithm": "sha256", "value": "A" * 64},
        {"algorithm": "sha256", "value": "a" * 63},
        {"algorithm": "sha256", "value": "g" * 64},
        {"algorithm": "sha256", "value": DIGEST, "extra": True},
        {"algorithm": "sha256", "value": 123},
        {"value": DIGEST},
    ],
)
def test_hash_ref_rejects_invalid_payloads(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        HashRef.model_validate(payload)


def test_hash_ref_schema_forbids_additional_fields() -> None:
    schema = HashRef.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["value"]["pattern"] == "^[a-f0-9]{64}$"


def test_artifact_ref_accepts_relative_path_and_optional_media_type() -> None:
    ref = ArtifactRef(
        hash=HashRef(algorithm="sha256", value=DIGEST),
        relative_path="runs/pilot/events.jsonl",
        media_type="application/x-ndjson",
        size_bytes=0,
    )
    assert ref.relative_path == "runs/pilot/events.jsonl"
    assert ref.hash.value == DIGEST
    assert ref.size_bytes == 0


def test_artifact_ref_accepts_missing_optional_media_type() -> None:
    ref = ArtifactRef(
        hash=HashRef(algorithm="sha256", value=DIGEST),
        relative_path="artifacts/output.json",
        size_bytes=17,
    )
    assert ref.media_type is None


@pytest.mark.parametrize(
    "relative_path",
    [
        "",
        "/var/tmp/output.json",
        "C:/data/output.json",
        "C:output.json",
        r"C:\data\output.json",
        r"runs\output.json",
        "../output.json",
        "runs/../output.json",
        "runs/./output.json",
        "runs//output.json",
        "runs/output.json/",
        "runs/\x00output.json",
    ],
)
def test_artifact_ref_rejects_noncanonical_paths(relative_path: str) -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(
            hash=HashRef(algorithm="sha256", value=DIGEST),
            relative_path=relative_path,
            size_bytes=5,
        )


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"size_bytes": -1},
        {"size_bytes": True},
        {"size_bytes": "1"},
        {"hash": {"algorithm": "sha256", "value": "x" * 64}},
        {"extra": 1},
    ],
)
def test_artifact_ref_rejects_invalid_fields(invalid_fields: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "hash": {"algorithm": "sha256", "value": DIGEST},
        "relative_path": "artifacts/result.json",
        "size_bytes": 1,
    }
    payload.update(invalid_fields)
    with pytest.raises(ValidationError):
        ArtifactRef.model_validate(payload)


def test_artifact_ref_schema_forbids_additional_fields() -> None:
    assert ArtifactRef.model_json_schema()["additionalProperties"] is False

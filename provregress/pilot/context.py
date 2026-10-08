"""Contexto reproducible y sin etiquetas experimentales para ejecuciones piloto."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from provregress.pilot.firewall import PilotFirewall
from provregress.schema.common import AppId, HashRef
from provregress.schema.manifests import (
    DatasetManifest,
    EnvironmentManifest,
    NonBlankStr,
    PilotStudyManifest,
    SystemManifest,
)
from provregress.storage.hashing import canonical_json_bytes, hash_model, sha256_hex


class RunContextError(ValueError):
    """Incoherencia entre manifests o parámetros del contexto piloto."""


class _FrozenHashRef(HashRef):
    """Referencia SHA-256 inmutable almacenada dentro de RunContext."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    def __eq__(self, other: object) -> bool:
        """Conserva la igualdad por valor con el contrato público HashRef."""
        if isinstance(other, HashRef):
            return (self.algorithm, self.value) == (other.algorithm, other.value)
        return NotImplemented

    def __hash__(self) -> int:
        """Permite utilizar referencias inmutables como identidades estables."""
        return hash((self.algorithm, self.value))


class RunContext(BaseModel):
    """Identidad y procedencia inmutables de una ejecución piloto autorizada."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    run_id: NonBlankStr
    study_id: NonBlankStr
    app_id: AppId
    case_id: NonBlankStr
    condition_id: NonBlankStr
    repeat_index: int = Field(strict=True, ge=0)
    system_version_id: NonBlankStr
    study_manifest_hash: HashRef
    dataset_manifest_hash: HashRef
    system_manifest_hash: HashRef
    environment_manifest_hash: HashRef

    @field_validator(
        "study_manifest_hash",
        "dataset_manifest_hash",
        "system_manifest_hash",
        "environment_manifest_hash",
    )
    @classmethod
    def freeze_hash_ref(cls, value: HashRef) -> HashRef:
        """Evita modificar los digests a través de atributos anidados."""
        return _FrozenHashRef.model_validate(value.model_dump(mode="python"))


ManifestT = TypeVar(
    "ManifestT", DatasetManifest, SystemManifest, EnvironmentManifest, PilotStudyManifest
)


def _validated_snapshot(manifest: ManifestT, expected_type: type[ManifestT]) -> ManifestT:
    """Reconstruye una copia válida aunque el modelo original haya sido alterado."""
    if not isinstance(manifest, expected_type):
        raise RunContextError("El tipo de manifest no corresponde al contexto solicitado.")
    try:
        return expected_type.model_validate(manifest.model_dump(mode="python"))
    except (ValidationError, TypeError, ValueError) as exc:
        raise RunContextError("Un manifest del contexto no supera la validación.") from exc


def build_run_context(
    *,
    study: PilotStudyManifest,
    dataset: DatasetManifest,
    system: SystemManifest,
    environment: EnvironmentManifest,
    case_id: str,
    condition_id: str,
    repeat_index: int,
    run_id: str | None = None,
) -> RunContext:
    """Vincula manifests solamente después de autorizar el caso piloto."""
    # Esta comprobación precede a cualquier cálculo de identidad o ejecución.
    PilotFirewall(study).assert_pilot_case(case_id)

    checked_study = _validated_snapshot(study, PilotStudyManifest)
    checked_dataset = _validated_snapshot(dataset, DatasetManifest)
    checked_system = _validated_snapshot(system, SystemManifest)
    checked_environment = _validated_snapshot(environment, EnvironmentManifest)

    if checked_dataset.split != "pilot":
        raise RunContextError("El dataset debe pertenecer exclusivamente al split piloto.")
    if checked_dataset.app_id != checked_system.app_id:
        raise RunContextError("Los identificadores de aplicación de los manifests no coinciden.")
    if not set(checked_dataset.case_ids).issubset(checked_study.pilot_case_ids):
        raise RunContextError("El dataset contiene casos que no pertenecen al estudio piloto.")
    if case_id not in checked_dataset.case_ids:
        raise RunContextError("El caso autorizado no está incluido en el dataset piloto.")
    if not isinstance(condition_id, str) or not condition_id.strip():
        raise RunContextError("El identificador de condición no puede estar vacío.")
    if type(repeat_index) is not int or repeat_index < 0:
        raise RunContextError("El índice de repetición debe ser un entero no negativo.")
    if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
        raise RunContextError("El identificador de ejecución debe ser texto no vacío.")

    study_hash = hash_model(checked_study)
    dataset_hash = hash_model(checked_dataset)
    system_hash = hash_model(checked_system)
    environment_hash = hash_model(checked_environment)

    if run_id is None:
        # El ID se deriva de la identidad autorizada, nunca de etiquetas de resultado.
        identity = {
            "namespace": "provregress.pilot.run-context.v1",
            "study_manifest_hash": study_hash.value,
            "dataset_manifest_hash": dataset_hash.value,
            "system_manifest_hash": system_hash.value,
            "environment_manifest_hash": environment_hash.value,
            "app_id": checked_dataset.app_id.value,
            "case_id": case_id,
            "condition_id": condition_id,
            "repeat_index": repeat_index,
        }
        run_id = "run-" + sha256_hex(canonical_json_bytes(identity))

    return RunContext(
        run_id=run_id,
        study_id=checked_study.pilot_id,
        app_id=checked_dataset.app_id,
        case_id=case_id,
        condition_id=condition_id,
        repeat_index=repeat_index,
        system_version_id=checked_system.version_id,
        study_manifest_hash=study_hash,
        dataset_manifest_hash=dataset_hash,
        system_manifest_hash=system_hash,
        environment_manifest_hash=environment_hash,
    )

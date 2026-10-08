"""Manifests estrictos para la infraestructura piloto P0 de ProvRegress."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, JsonValue, field_validator, model_validator

from provregress.schema.common import AppId, ComponentType, HashRef
from provregress.storage.hashing import canonical_json_bytes, hash_case_ids


def _nonblank(value: str) -> str:
    """Rechaza campos de identidad vacíos sin normalizar su contenido."""
    if not value.strip():
        raise ValueError("El identificador no puede estar vacío.")
    return value


NonBlankStr = Annotated[str, AfterValidator(_nonblank)]


def _check_case_ids(case_ids: list[str], *, sorted_required: bool) -> None:
    """Comprueba unicidad y el orden exigido por el contrato."""
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Los identificadores de casos no pueden repetirse.")
    if sorted_required and case_ids != sorted(case_ids):
        raise ValueError("Los identificadores de casos deben estar ordenados.")


def _check_case_hash(case_ids: list[str], expected: HashRef) -> None:
    """Detecta la discrepancia entre casos declarados y su digest."""
    if hash_case_ids(case_ids) != expected:
        raise ValueError("El hash declarado no coincide con los identificadores de casos.")


class _StrictManifest(BaseModel):
    """Contrato común de validación estricta y campos cerrados."""

    model_config = ConfigDict(extra="forbid", strict=True)


class DatasetManifest(_StrictManifest):
    """Fija un conjunto de casos y su partición experimental."""

    schema_version: Literal["pilot-dataset-v1"] = "pilot-dataset-v1"
    dataset_id: NonBlankStr
    app_id: AppId
    generator_version: NonBlankStr
    source_hashes: list[HashRef]
    split: Literal["pilot", "confirmatory"]
    case_ids: list[NonBlankStr]
    case_ids_hash: HashRef
    license_note: str | None = None

    @model_validator(mode="after")
    def validate_case_identity(self) -> DatasetManifest:
        """Exige IDs ordenados, únicos y consistentes con SHA-256."""
        _check_case_ids(self.case_ids, sorted_required=True)
        _check_case_hash(self.case_ids, self.case_ids_hash)
        return self


class ComponentManifest(_StrictManifest):
    """Identifica un componente sin derivar ningún grafo."""

    component_id: NonBlankStr
    component_type: ComponentType
    implementation_version: NonBlankStr
    config_hash: HashRef
    artifact_hash: HashRef | None = None


class SystemManifest(_StrictManifest):
    """Describe una versión del sistema y sus componentes."""

    schema_version: Literal["pilot-system-v1"] = "pilot-system-v1"
    system_id: NonBlankStr
    app_id: AppId
    version_id: NonBlankStr
    components: list[ComponentManifest]
    orchestration_hash: HashRef
    config_hash: HashRef

    @model_validator(mode="after")
    def validate_components(self) -> SystemManifest:
        """Prohíbe componentes con identidades duplicadas."""
        ids = [component.component_id for component in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Los identificadores de componentes no pueden repetirse.")
        return self


class EvaluatorManifest(_StrictManifest):
    """Registra la configuración del instrumento de evaluación."""

    schema_version: Literal["pilot-evaluator-v1"] = "pilot-evaluator-v1"
    evaluator_id: NonBlankStr
    evaluator_type: NonBlankStr
    model_id: NonBlankStr | None = None
    snapshot: NonBlankStr | None = None
    rubric_hash: HashRef | None = None
    threshold_config_hash: HashRef | None = None
    position_config: dict[str, JsonValue]

    @field_validator("position_config")
    @classmethod
    def validate_position_config(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Rechaza configuraciones que no admiten serialización canónica."""
        canonical_json_bytes(value)
        return value


class EnvironmentManifest(_StrictManifest):
    """Registra el entorno y el estado dirty para reproducibilidad."""

    schema_version: Literal["pilot-env-v1"] = "pilot-env-v1"
    python_version: NonBlankStr
    package_lock_hash: HashRef
    os_id: NonBlankStr
    container_id: NonBlankStr | None = None
    hardware_class: NonBlankStr
    git_commit: NonBlankStr
    dirty: bool
    timezone: NonBlankStr
    runtime_flags: dict[str, JsonValue]

    @field_validator("runtime_flags")
    @classmethod
    def validate_runtime_flags(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Rechaza parámetros que no admiten serialización canónica."""
        canonical_json_bytes(value)
        return value


class PilotStudyManifest(_StrictManifest):
    """Congela los conjuntos disjuntos de casos piloto y confirmatorios."""

    schema_version: Literal["pilot-study-v1"] = "pilot-study-v1"
    pilot_id: NonBlankStr
    protocol_version: NonBlankStr
    pilot_case_ids: list[NonBlankStr]
    confirmatory_case_ids: list[NonBlankStr]
    pilot_case_ids_hash: HashRef
    confirmatory_case_ids_hash: HashRef
    operator_registry_hash: HashRef | None = None
    graph_schema_version: NonBlankStr | None = None
    analysis_plan_version: NonBlankStr

    @model_validator(mode="after")
    def validate_partition(self) -> PilotStudyManifest:
        """Impide solapamientos y hashes de casos inconsistentes."""
        _check_case_ids(self.pilot_case_ids, sorted_required=False)
        _check_case_ids(self.confirmatory_case_ids, sorted_required=False)
        if not set(self.pilot_case_ids).isdisjoint(self.confirmatory_case_ids):
            raise ValueError("Los conjuntos piloto y confirmatorio deben ser disjuntos.")
        _check_case_hash(self.pilot_case_ids, self.pilot_case_ids_hash)
        _check_case_hash(self.confirmatory_case_ids, self.confirmatory_case_ids_hash)
        return self

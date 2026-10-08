"""Manifests estrictos para la infraestructura piloto P0 de ProvRegress."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from provregress.schema.common import AppId, ComponentType, HashRef, RunStatus
from provregress.storage.hashing import canonical_json_bytes, hash_case_ids, hash_model


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


class MutationManifest(_StrictManifest):
    """Descripción de tratamiento experimental, sin operadores de ejecución."""

    schema_version: Literal["pilot-mutation-v1"] = "pilot-mutation-v1"
    mutation_id: NonBlankStr
    operator_id: NonBlankStr
    operator_version: NonBlankStr
    target_component_id: NonBlankStr | None = None
    target_relation_id: NonBlankStr | None = None
    severity: Literal["low", "medium", "high", "identity", "evaluator_control"]
    before_hash: HashRef
    after_hash: HashRef
    parameters: dict[str, JsonValue]

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Exige parámetros canónicos, sin números no finitos."""
        canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def validate_target(self) -> MutationManifest:
        """Las mutaciones no usadas como controles exigen un objetivo explícito."""
        if self.severity not in {"identity", "evaluator_control"} and not (
            self.target_component_id is not None or self.target_relation_id is not None
        ):
            raise ValueError("Una mutación experimental requiere un objetivo explícito.")
        return self


class RunManifestError(ValueError):
    """La identidad o finalización de una ejecución piloto no es válida."""


def _utc_datetime(value: datetime) -> datetime:
    """Normaliza a UTC y rechaza instantes sin información de zona horaria."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha de la ejecución debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


class RunManifest(_StrictManifest):
    """Procedencia y resultado de cierre de una ejecución piloto individual."""

    schema_version: Literal["pilot-run-v1"] = "pilot-run-v1"
    study_id: NonBlankStr
    run_id: NonBlankStr
    condition_id: NonBlankStr
    app_id: AppId
    case_id: NonBlankStr
    repeat_index: int = Field(strict=True, ge=0)
    system_manifest_hash: HashRef
    dataset_manifest_hash: HashRef
    mutation_manifest_hash: HashRef | None = None
    evaluator_manifest_hashes: list[HashRef]
    environment_manifest_hash: HashRef
    trace_hash: HashRef | None = None
    started_at: datetime
    ended_at: datetime | None = None
    status: RunStatus

    @field_validator("started_at", "ended_at")
    @classmethod
    def validate_utc(cls, value: datetime | None) -> datetime | None:
        """Exige instantes conscientes de zona horaria y los representa en UTC."""
        return None if value is None else _utc_datetime(value)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> RunManifest:
        """Impide cierres anteriores al inicio y trazas en ejecuciones activas."""
        active = {RunStatus.PLANNED, RunStatus.RUNNING}
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("El cierre de una ejecución no puede preceder a su inicio.")
        if self.status in active and (self.ended_at is not None or self.trace_hash is not None):
            raise ValueError("Una ejecución activa no puede declararse finalizada.")
        if self.status not in active and self.ended_at is None:
            raise ValueError("Una ejecución terminal necesita fecha de cierre.")
        if self.status is RunStatus.SUCCEEDED and self.trace_hash is None:
            raise ValueError("Una ejecución completada requiere la traza verificada.")
        if self.trace_hash is not None and self.ended_at is None:
            raise ValueError("El hash de la traza requiere una fecha de cierre.")
        return self


def build_run_manifest(
    *,
    context: "RunContext",
    started_at: datetime,
    evaluators: Sequence[EvaluatorManifest] = (),
    mutation_manifest_hash: HashRef | None = None,
) -> RunManifest:
    """Construye el manifest pendiente desde un contexto piloto ya autorizado."""
    # Importación local para no introducir un ciclo entre schema y pilot.
    from provregress.pilot.context import RunContext
    from pydantic import ValidationError

    if not isinstance(context, RunContext):
        raise RunManifestError("Se requiere un RunContext autorizado.")
    if isinstance(evaluators, (str, bytes)) or not isinstance(evaluators, Sequence):
        raise RunManifestError("Los evaluadores deben proporcionarse como una secuencia.")
    try:
        checked_context = RunContext.model_validate(context.model_dump(mode="python"))
        checked_evaluators = []
        for evaluator in evaluators:
            if not isinstance(evaluator, EvaluatorManifest):
                raise RunManifestError("Se requiere un EvaluatorManifest por evaluador.")
            checked_evaluators.append(
                EvaluatorManifest.model_validate(evaluator.model_dump(mode="python"))
            )
        ids = [e.evaluator_id for e in checked_evaluators]
        if len(ids) != len(set(ids)):
            raise RunManifestError("Los evaluadores no pueden compartir identificador.")
        mutation_hash = None
        if mutation_manifest_hash is not None:
            if not isinstance(mutation_manifest_hash, HashRef):
                raise RunManifestError("El hash de mutación no es válido.")
            mutation_hash = HashRef.model_validate(mutation_manifest_hash.model_dump(mode="python"))
        return RunManifest(
            study_id=checked_context.study_id,
            run_id=checked_context.run_id,
            condition_id=checked_context.condition_id,
            app_id=checked_context.app_id,
            case_id=checked_context.case_id,
            repeat_index=checked_context.repeat_index,
            system_manifest_hash=checked_context.system_manifest_hash,
            dataset_manifest_hash=checked_context.dataset_manifest_hash,
            mutation_manifest_hash=mutation_hash,
            evaluator_manifest_hashes=[hash_model(e) for e in checked_evaluators],
            environment_manifest_hash=checked_context.environment_manifest_hash,
            started_at=started_at,
            status=RunStatus.RUNNING,
        )
    except (ValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, RunManifestError):
            raise
        raise RunManifestError("El manifest inicial no supera la validación.") from exc


def finalize_run_manifest(
    *,
    manifest: RunManifest,
    sink: "JsonlEventSink",
    ended_at: datetime,
    status: RunStatus,
) -> RunManifest:
    """Cierra el sumidero y conserva el digest exacto del JSONL validado."""
    from pydantic import ValidationError
    from provregress.pilot.context import RunContext
    from provregress.pilot.events import JsonlEventSink

    if not isinstance(manifest, RunManifest):
        raise RunManifestError("Se requiere un RunManifest válido.")
    if not isinstance(sink, JsonlEventSink):
        raise RunManifestError("Se requiere un JsonlEventSink válido.")
    try:
        checked = RunManifest.model_validate(manifest.model_dump(mode="python"))
        sink_context = RunContext.model_validate(sink._context.model_dump(mode="python"))
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        raise RunManifestError("El manifest o el contexto del sumidero no es válido.") from exc
    if checked.status is not RunStatus.RUNNING:
        raise RunManifestError("Solo puede finalizarse un manifest en estado running.")
    if type(status) is not RunStatus or status not in {
        RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.REJECTED,
    }:
        raise RunManifestError("La finalización requiere un RunStatus terminal.")
    try:
        end = _utc_datetime(ended_at)
    except (TypeError, ValueError) as exc:
        raise RunManifestError("La fecha de cierre debe contener una zona horaria.") from exc
    if end < checked.started_at:
        raise RunManifestError("El cierre no puede preceder al inicio.")

    # El sumidero conserva internamente el RunContext verificado al construirse.
    for manifest_field, context_field in (
        ("study_id", "study_id"), ("run_id", "run_id"),
        ("condition_id", "condition_id"), ("app_id", "app_id"),
        ("case_id", "case_id"), ("repeat_index", "repeat_index"),
        ("system_manifest_hash", "system_manifest_hash"),
        ("dataset_manifest_hash", "dataset_manifest_hash"),
        ("environment_manifest_hash", "environment_manifest_hash"),
    ):
        if getattr(checked, manifest_field) != getattr(sink_context, context_field):
            raise RunManifestError("El sumidero corresponde a otra identidad de ejecución.")

    # Nunca se registra un trace_hash antes de que close verifique el JSONL.
    trace_hash = sink.close()
    return RunManifest.model_validate(
        checked.model_dump(mode="python") | {
            "status": status,
            "ended_at": end,
            "trace_hash": trace_hash,
        }
    )

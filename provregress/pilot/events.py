"""Instrumentación piloto: eventos observables y cierre verificable del registro."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import RLock
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from provregress.pilot.context import RunContext
from provregress.schema.common import ComponentType, HashRef
from provregress.schema.events import EventEnvelope, EventError, EventType
from provregress.storage.artifacts import ArtifactStore
from provregress.storage.hashing import canonical_json_bytes, hash_file, sha256_hex
from provregress.storage.jsonl import (
    EventLogIntegrityError,
    append_event,
    iter_events,
    validate_event_log,
)


class EventSinkError(ValueError):
    """El sumidero no puede aceptar o cerrar la ejecución solicitada."""


@runtime_checkable
class PilotEventSink(Protocol):
    """Contrato mínimo para emitir eventos de una ejecución piloto."""

    def emit(
        self,
        *,
        event_type: EventType,
        component_type: ComponentType,
        component_id: str,
        payload: Any,
        parent_event_ids: Sequence[str] = (),
        attributes: dict[str, Any] | None = None,
        error: EventError | None = None,
    ) -> EventEnvelope: ...

    def close(self) -> HashRef: ...


_RESERVED_PAYLOAD_KEYS = frozenset({
    "mutation_id", "operator_id", "target_component_id", "severity",
})


def _assert_observable(value: Any) -> None:
    """Bloquea etiquetas privilegiadas también dentro del payload anidado."""
    if isinstance(value, dict):
        if _RESERVED_PAYLOAD_KEYS.intersection(value):
            raise EventSinkError("El payload contiene etiquetas experimentales reservadas.")
        for nested in value.values():
            _assert_observable(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_observable(nested)


class JsonlEventSink:
    """Registra eventos piloto con payloads inmutables y orden verificable."""

    def __init__(
        self,
        context: RunContext,
        artifact_store: ArtifactStore,
        log_path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Requiere un contexto válido y un registro nuevo o vacío."""
        if not isinstance(context, RunContext):
            raise EventSinkError("Se requiere un RunContext válido.")
        if not isinstance(artifact_store, ArtifactStore):
            raise EventSinkError("Se requiere un ArtifactStore válido.")
        if clock is not None and not callable(clock):
            raise EventSinkError("El reloj debe ser una función invocable.")
        try:
            self._context = RunContext.model_validate(context.model_dump(mode="python"))
        except (ValidationError, ValueError, TypeError) as exc:
            raise EventSinkError("El contexto no supera la validación estricta.") from exc
        self._store = artifact_store
        self._path = Path(log_path)
        if self._path.is_symlink():
            raise EventSinkError("No se admite un enlace simbólico para el registro.")
        if self._path.exists() and (
            not self._path.is_file() or self._path.stat().st_size != 0
        ):
            raise EventSinkError("El registro debe ser nuevo o estar vacío.")
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        self._lock = RLock()
        self._closed = False
        self._count = 0
        self._last_hash: HashRef | None = None

    @property
    def closed(self) -> bool:
        """Informa si el sumidero ya fue finalizado."""
        return self._closed

    def _checked_history(self) -> list[EventEnvelope]:
        """Impide continuar cuando los bytes o eventos externos han cambiado."""
        if self._path.is_symlink():
            raise EventSinkError("El registro no puede ser un enlace simbólico.")
        if not self._path.exists():
            if self._count:
                raise EventSinkError("Desapareció el registro previamente escrito.")
            return []
        existing = list(iter_events(self._path))
        if existing:
            validate_event_log(existing, expected_run_id=self._context.run_id)
        if len(existing) != self._count:
            raise EventSinkError("El registro fue modificado por otro escritor.")
        current_hash = hash_file(self._path)
        if self._last_hash is not None and current_hash != self._last_hash:
            raise EventSinkError("Los bytes persistidos cambiaron desde la última emisión.")
        if self._count == 0 and self._path.stat().st_size != 0:
            raise EventSinkError("El registro inicial no está vacío.")
        return existing

    def emit(
        self,
        *,
        event_type: EventType,
        component_type: ComponentType,
        component_id: str,
        payload: Any,
        parent_event_ids: Sequence[str] = (),
        attributes: dict[str, Any] | None = None,
        error: EventError | None = None,
    ) -> EventEnvelope:
        """Serializa la emisión incluso con múltiples hilos del mismo proceso."""
        with self._lock:
            return self._emit_checked(
                event_type=event_type, component_type=component_type,
                component_id=component_id, payload=payload,
                parent_event_ids=parent_event_ids, attributes=attributes, error=error,
            )

    def _emit_checked(
        self,
        *,
        event_type: EventType,
        component_type: ComponentType,
        component_id: str,
        payload: Any,
        parent_event_ids: Sequence[str],
        attributes: dict[str, Any] | None,
        error: EventError | None,
    ) -> EventEnvelope:
        """Asigna identidad y UTC, persiste bytes y anexa el evento validado."""
        if self._closed:
            raise EventSinkError("No se pueden emitir eventos después del cierre.")
        if isinstance(parent_event_ids, (str, bytes)) or not isinstance(
            parent_event_ids, Sequence
        ):
            raise EventSinkError("Los padres deben ser una secuencia de identificadores.")
        existing = self._checked_history()
        try:
            # Convertir a JSON antes de comprobar claves evita modelos opacos.
            serialized = canonical_json_bytes(payload)
            _assert_observable(json.loads(serialized))
            now = self._clock()
            digest = HashRef(algorithm="sha256", value=sha256_hex(serialized))
            event = EventEnvelope(
                run_id=self._context.run_id,
                event_id=f"evt-{self._count:08d}",
                sequence=self._count,
                timestamp_utc=now,
                app_id=self._context.app_id,
                system_version_id=self._context.system_version_id,
                case_id=self._context.case_id,
                condition_id=self._context.condition_id,
                repeat_index=self._context.repeat_index,
                event_type=event_type,
                component_type=component_type,
                component_id=component_id,
                parent_event_ids=list(parent_event_ids),
                payload_hash=digest,
                attributes={} if attributes is None else attributes,
                error=error,
            )
            # Validación anticipada para no dejar artefactos huérfanos ante errores de esquema.
            validate_event_log([*existing, event], expected_run_id=self._context.run_id)
        except (ValidationError, ValueError, TypeError) as exc:
            if isinstance(exc, EventSinkError):
                raise
            raise EventSinkError("El evento no cumple el contrato de observabilidad.") from exc

        ref = self._store.put_bytes(serialized, media_type="application/json")
        if ref.hash != event.payload_hash:
            raise EventSinkError("La referencia del almacén no coincide con el contenido.")
        # Revalidar, sin utilizar model_copy(update=...) que omite validadores.
        complete = EventEnvelope.model_validate(
            event.model_dump(mode="python") | {"payload_ref": ref}
        )
        append_event(self._path, complete)
        self._count += 1
        self._last_hash = hash_file(self._path)
        return complete

    def close(self) -> HashRef:
        """Serializa el cierre con las emisiones todavía en curso."""
        with self._lock:
            return self._close_checked()

    def _close_checked(self) -> HashRef:
        """Verifica la traza completa y devuelve SHA-256 de los bytes exactos."""
        # Un segundo cierre también verifica el contenido, nunca devuelve un hash obsoleto.
        events = self._checked_history()
        if not events:
            raise EventSinkError("No se puede cerrar un registro sin eventos.")
        summary = validate_event_log(events, expected_run_id=self._context.run_id)
        if summary.event_count != self._count:
            raise EventLogIntegrityError("El recuento final del registro no coincide.")
        result = hash_file(self._path)
        if result != self._last_hash:
            raise EventSinkError("El hash final del registro ha cambiado.")
        self._closed = True
        return result

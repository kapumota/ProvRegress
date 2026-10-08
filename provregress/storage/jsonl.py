"""Registro JSONL canónico con escritura append-only y validación del historial."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable, Iterator
from itertools import chain
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from provregress.schema.events import EventEnvelope
from provregress.storage.hashing import canonical_json_bytes


class EventLogError(ValueError):
    """Error de formato o integridad de un registro de eventos."""


class EventLogFormatError(EventLogError):
    """Línea JSONL inválida, incompleta o no canónica."""


class EventLogIntegrityError(EventLogError):
    """El historial vulnera invariantes de ejecución o precedencia."""


class EventLogSummary(BaseModel):
    """Resultado inmutable de validar un registro de una sola ejecución."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    run_id: str | None = None
    event_count: int = Field(strict=True, ge=0)
    last_sequence: int | None = Field(default=None, strict=True, ge=0)
    last_event_id: str | None = None


def _validated_event(event: EventEnvelope) -> EventEnvelope:
    """Revalida eventos alterados con model_copy sin permitir coerciones."""
    if not isinstance(event, EventEnvelope):
        raise EventLogIntegrityError("Se requiere una instancia de EventEnvelope.")
    try:
        return EventEnvelope.model_validate(event.model_dump(mode="python"))
    except (ValidationError, TypeError, ValueError) as exc:
        raise EventLogIntegrityError("El evento no supera la validación estricta.") from exc


def _iter_decoded(source: BinaryIO) -> Iterator[EventEnvelope]:
    """Lee líneas físicas con su número y exige bytes JSON canónicos."""
    for lineno, line in enumerate(source, start=1):
        if not line.endswith(b"\n"):
            raise EventLogFormatError(f"Línea {lineno}: falta el salto de línea final.")
        payload = line[:-1]
        try:
            event = EventEnvelope.model_validate_json(payload)
            if canonical_json_bytes(event) != payload:
                raise ValueError("Representación JSON no canónica.")
        except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
            raise EventLogFormatError(f"Línea {lineno}: evento JSONL no válido o no canónico.") from exc
        yield event


def _open_readonly(path: Path) -> int:
    """Abre únicamente archivos regulares y no sigue enlaces de archivo."""
    if path.is_symlink():
        raise EventLogError("No se admiten enlaces simbólicos como registro JSONL.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise EventLogError("El registro JSONL debe ser un archivo regular.")
    return descriptor


def iter_events(path: Path | str) -> Iterator[EventEnvelope]:
    """Recorre eventos canónicos; informa el número de línea ante corrupción."""
    descriptor = _open_readonly(Path(path))
    with os.fdopen(descriptor, "rb") as source:
        yield from _iter_decoded(source)


def validate_event_log(
    events: Iterable[EventEnvelope], *, expected_run_id: str | None = None
) -> EventLogSummary:
    """Exige una ejecución, secuencias contiguas y padres ya observados."""
    if expected_run_id is not None and (
        not isinstance(expected_run_id, str) or not expected_run_id.strip()
    ):
        raise EventLogIntegrityError("El run_id esperado debe ser texto no vacío.")

    seen: set[str] = set()
    identity: tuple[object, ...] | None = None
    run_id: str | None = None
    last_event_id: str | None = None
    count = 0

    for position, incoming in enumerate(events):
        event = _validated_event(incoming)
        if event.sequence != position:
            raise EventLogIntegrityError(
                f"Evento {position}: secuencia esperada {position}, recibida {event.sequence}."
            )
        if event.event_id in seen:
            raise EventLogIntegrityError(
                f"Evento {position}: identificador de evento duplicado."
            )
        if any(parent not in seen for parent in event.parent_event_ids):
            raise EventLogIntegrityError(
                f"Evento {position}: un padre todavía no aparece en el registro."
            )

        current_identity = (
            event.run_id,
            event.app_id,
            event.system_version_id,
            event.case_id,
            event.condition_id,
            event.repeat_index,
        )
        if identity is None:
            identity = current_identity
            run_id = event.run_id
        elif current_identity != identity:
            raise EventLogIntegrityError(
                f"Evento {position}: la identidad de la ejecución no coincide."
            )
        if expected_run_id is not None and event.run_id != expected_run_id:
            raise EventLogIntegrityError(
                f"Evento {position}: el run_id no coincide con el esperado."
            )

        seen.add(event.event_id)
        last_event_id = event.event_id
        count += 1

    if count == 0 and expected_run_id is not None:
        raise EventLogIntegrityError("El registro no contiene la ejecución esperada.")
    return EventLogSummary(
        run_id=run_id,
        event_count=count,
        last_sequence=count - 1 if count else None,
        last_event_id=last_event_id,
    )


def append_event(path: Path | str, event: EventEnvelope) -> None:
    """Anexa una línea solo si el historial completo permanece consistente."""
    checked = _validated_event(event)
    encoded = canonical_json_bytes(checked) + b"\n"
    target = Path(path)
    if target.is_symlink():
        raise EventLogError("No se admiten enlaces simbólicos como registro JSONL.")
    target.parent.mkdir(parents=True, exist_ok=True)

    # El bloqueo cubre lectura, validación y append frente a otros escritores compatibles.
    import fcntl

    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise EventLogError("El registro JSONL debe ser un archivo regular.")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            with os.fdopen(os.dup(descriptor), "rb") as source:
                validate_event_log(chain(_iter_decoded(source), (checked,)))
            # O_APPEND impide reemplazar bytes anteriores. Se guarda la línea completa.
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("La escritura del registro JSONL fue incompleta.")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)

"""M2-P2: tratamientos locales sobre copias de entradas, no experimentos confirmatorios.

Las operaciones no modifican los insumos originales ni generan etiquetas de
tratamiento dentro de los eventos observables. El resultado es un nuevo snapshot
privilegiado; ejecutar sistemas sobre él es responsabilidad del piloto local.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from provregress.provenance_v2.schema import V2Error, _Strict, canonical_v2
from provregress.storage.hashing import sha256_hex

MAX_TEXT_BYTES = 16 * 1024
MAX_INPUT_BYTES = 128 * 1024
_OPERATORS = frozenset({
    "prompt.query.replace.v1", "retrieval.top_k.set.v1",
    "index.document.replace.v1", "tool.catalog.field.set.v1",
})
_TOOL_FIELDS: dict[str, type] = {
    "item.stock": int, "item.quantity": int, "item.price_units": int,
    "item.discount_eligible": bool, "enable_discount_step": bool,
}
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\.md\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class SystemTreatmentError(V2Error):
    """La intervención local no satisface sus precondiciones."""


class SystemSnapshotM2(_Strict):
    """Configuración privada completa, sin datos de resultado de un modelo."""

    schema_version: Literal["mutation-system-snapshot-m2-p2"] = "mutation-system-snapshot-m2-p2"
    query: str
    top_k: int = Field(strict=True, ge=1, le=32)
    documents: dict[str, str]
    catalog: dict[str, JsonValue]

    @model_validator(mode="after")
    def check_data(self) -> "SystemSnapshotM2":
        if not self.query.strip() or len(self.query.encode("utf-8")) > 2048:
            raise ValueError("Consulta vacía o excesiva.")
        if not self.documents or len(self.documents) > 32:
            raise ValueError("El corpus debe contener entre uno y 32 documentos.")
        for name, body in self.documents.items():
            if not _NAME.fullmatch(name) or len(body.encode("utf-8")) > MAX_TEXT_BYTES:
                raise ValueError("Nombre de documento o contenido inválido.")
        item = self.catalog.get("item")
        if not isinstance(item, dict) or any(k.split(".", 1)[1] not in item for k in _TOOL_FIELDS if k.startswith("item.")):
            raise ValueError("Catálogo de herramientas incompleto.")
        for field, kind in _TOOL_FIELDS.items():
            parts = field.split(".")
            value = self.catalog[parts[0]][parts[1]] if len(parts) == 2 else self.catalog.get(field, False)
            if type(value) is not kind:
                raise ValueError("Tipo incompatible con el contrato del catálogo.")
            if kind is int and (value < 0 or value > 100000000):
                raise ValueError("Cantidad fuera del dominio local.")
        canonical_v2(self.catalog)
        return self

    @property
    def snapshot_hash(self) -> str:
        return sha256_hex(canonical_v2(self))


class SystemRequestM2(_Strict):
    operator_id: Literal[
        "prompt.query.replace.v1", "retrieval.top_k.set.v1",
        "index.document.replace.v1", "tool.catalog.field.set.v1",
    ]
    target: str
    expected_before_hash: str
    value: JsonValue

    @field_validator("expected_before_hash")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not _HASH.fullmatch(value):
            raise ValueError("La precondición debe ser un SHA-256 exacto.")
        return value

    @model_validator(mode="after")
    def matching_target(self) -> "SystemRequestM2":
        if self.operator_id == "prompt.query.replace.v1" and self.target != "query":
            raise ValueError("La operación de prompt solo modifica query.")
        if self.operator_id == "retrieval.top_k.set.v1" and self.target != "top_k":
            raise ValueError("La operación de recuperador solo modifica top_k.")
        if self.operator_id == "index.document.replace.v1" and not _NAME.fullmatch(self.target):
            raise ValueError("La operación de índice exige nombre canónico de documento.")
        if self.operator_id == "tool.catalog.field.set.v1" and self.target not in _TOOL_FIELDS:
            raise ValueError("Campo de herramienta no autorizado.")
        return self


class StagedReceiptM2(_Strict):
    schema_version: Literal["mutation-stage-m2-p2"] = "mutation-stage-m2-p2"
    operator_class: Literal["prompt", "retrieval", "index", "tool"]
    source_snapshot_hash: str
    candidate_snapshot_hash: str
    before_value_hash: str
    after_value_hash: str
    confirmatory_execution: Literal[False] = False


def read_system_snapshot(source: Path, *, query: str = "reembolso", top_k: int = 3) -> SystemSnapshotM2:
    """Lee únicamente un corpus local acotado; prohíbe enlaces simbólicos."""
    source = Path(source)
    if not source.is_dir() or source.is_symlink():
        raise SystemTreatmentError("La fuente local no es un directorio ordinario.")
    entries = list(source.iterdir())
    if len(entries) > 33:
        raise SystemTreatmentError("Demasiados archivos para el piloto controlado.")
    documents: dict[str, str] = {}
    catalog: Any = None
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise SystemTreatmentError("Archivo inválido, simbólico o excesivo.")
        if path.name != "catalog.json" and not _NAME.fullmatch(path.name):
            raise SystemTreatmentError("Extensión o nombre no autorizado.")
        data = path.read_bytes()
        if path.name == "catalog.json":
            import json
            try:
                catalog = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
            except (ValueError, UnicodeError) as exc:
                raise SystemTreatmentError("Catálogo inválido o con claves duplicadas.") from exc
        else:
            documents[path.name] = data.decode("utf-8")
    if catalog is None:
        raise SystemTreatmentError("Falta catalog.json.")
    return SystemSnapshotM2(query=query, top_k=top_k, documents=documents, catalog=catalog)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Clave de catálogo duplicada.")
        result[key] = value
    return result


def _target_value(snapshot: SystemSnapshotM2, request: SystemRequestM2) -> Any:
    if request.operator_id == "prompt.query.replace.v1":
        return snapshot.query
    if request.operator_id == "retrieval.top_k.set.v1":
        return snapshot.top_k
    if request.operator_id == "index.document.replace.v1":
        if request.target not in snapshot.documents:
            raise SystemTreatmentError("Documento no presente en el snapshot.")
        return snapshot.documents[request.target]
    parts = request.target.split(".")
    return snapshot.catalog[parts[0]][parts[1]] if len(parts) == 2 else snapshot.catalog.get(parts[0], False)


def _checked_value(request: SystemRequestM2) -> Any:
    value = request.value
    if request.operator_id in {"prompt.query.replace.v1", "index.document.replace.v1"}:
        if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
            raise SystemTreatmentError("El texto de la intervención no es válido.")
    elif request.operator_id == "retrieval.top_k.set.v1":
        if type(value) is not int or not 1 <= value <= 32:
            raise SystemTreatmentError("top_k debe ser un entero entre 1 y 32.")
    else:
        kind = _TOOL_FIELDS[request.target]
        if type(value) is not kind or (kind is int and not 0 <= value <= 100000000):
            raise SystemTreatmentError("Tipo o rango incompatible con el campo de herramienta.")
    canonical_v2(value)
    return value


def stage_system_treatment(
    source: SystemSnapshotM2, request: SystemRequestM2,
) -> tuple[SystemSnapshotM2, StagedReceiptM2]:
    """Aplica una única intervención en memoria, preservando la fuente original."""
    source = SystemSnapshotM2.model_validate_json(canonical_v2(source))
    request = SystemRequestM2.model_validate(request.model_dump(mode="python"))
    before = _target_value(source, request)
    before_hash = sha256_hex(canonical_v2(before))
    if request.expected_before_hash != before_hash:
        raise SystemTreatmentError("La precondición del objetivo ya no coincide.")
    value = _checked_value(request)
    if canonical_v2(before) == canonical_v2(value):
        raise SystemTreatmentError("Una intervención sin cambio requiere control identity separado.")
    changed = source.model_dump(mode="python")
    if request.operator_id == "prompt.query.replace.v1":
        changed["query"] = value
    elif request.operator_id == "retrieval.top_k.set.v1":
        changed["top_k"] = value
    elif request.operator_id == "index.document.replace.v1":
        changed["documents"][request.target] = value
    else:
        bits = request.target.split(".")
        dest = changed["catalog"]
        if len(bits) == 2:
            dest[bits[0]][bits[1]] = value
        else:
            dest[bits[0]] = value
    candidate = SystemSnapshotM2.model_validate(changed)
    cls = request.operator_id.split(".", 1)[0]
    return candidate, StagedReceiptM2(
        operator_class=cls, source_snapshot_hash=source.snapshot_hash,
        candidate_snapshot_hash=candidate.snapshot_hash,
        before_value_hash=before_hash, after_value_hash=sha256_hex(canonical_v2(value)),
    )


def make_request(source: SystemSnapshotM2, operator_id: str, target: str, value: Any) -> SystemRequestM2:
    """Helper del piloto: fija el hash anterior sin exponer valores en el recibo."""
    if operator_id not in _OPERATORS:
        raise SystemTreatmentError("Operador de sistema desconocido.")
    provisional = SystemRequestM2(
        operator_id=operator_id, target=target,
        expected_before_hash="0" * 64, value=value,
    )
    return provisional.model_copy(update={
        "expected_before_hash": sha256_hex(canonical_v2(_target_value(source, provisional))),
    })


def materialize_snapshot(snapshot: SystemSnapshotM2, destination: Path) -> tuple[Path, Path]:
    """Materializa una COPIA NUEVA solo para pruebas piloto locales."""
    snapshot = SystemSnapshotM2.model_validate_json(canonical_v2(snapshot))
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise SystemTreatmentError("La carpeta de salida ya existe.")
    destination.mkdir(parents=True, exist_ok=False)
    for name, body in sorted(snapshot.documents.items()):
        (destination / name).write_bytes(body.encode("utf-8"))
    catalog = destination / "catalog.json"
    catalog.write_bytes(canonical_v2(snapshot.catalog))
    return destination, catalog

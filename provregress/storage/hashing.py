"""Serialización canónica y referencias SHA-256 reproducibles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel

from provregress.schema import HashRef


def _check_json_keys(value: Any, active: set[int]) -> None:
    """Comprueba que las claves sean texto y no existan ciclos."""
    if not isinstance(value, (dict, list)):
        return

    identity = id(value)
    if identity in active:
        raise ValueError("El contenido JSON no puede contener referencias circulares.")

    active.add(identity)
    try:
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("Las claves de un objeto JSON deben ser texto.")
                _check_json_keys(item, active)
        else:
            for item in value:
                _check_json_keys(item, active)
    finally:
        active.remove(identity)


def canonical_json_bytes(value: Any) -> bytes:
    """Codifica JSON en UTF-8 con claves ordenadas y sin espacios superfluos."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")

    _check_json_keys(value, set())
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("El valor no admite serialización JSON canónica.") from exc


def sha256_hex(data: bytes) -> str:
    """Calcula el digest SHA-256 de los bytes exactos recibidos."""
    if not isinstance(data, bytes):
        raise TypeError("El contenido para SHA-256 debe ser de tipo bytes.")
    return hashlib.sha256(data).hexdigest()


def hash_model(model: BaseModel) -> HashRef:
    """Calcula un identificador de contenido para un modelo Pydantic."""
    if not isinstance(model, BaseModel):
        raise TypeError("Se esperaba una instancia de BaseModel.")
    digest = sha256_hex(canonical_json_bytes(model.model_dump(mode="json")))
    return HashRef(algorithm="sha256", value=digest)


def hash_file(path: Path | str) -> HashRef:
    """Calcula SHA-256 sobre los bytes existentes sin modificar el archivo."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return HashRef(algorithm="sha256", value=digest.hexdigest())


def hash_case_ids(case_ids: Sequence[str]) -> HashRef:
    """Calcula un identificador estable para un conjunto de casos distintos."""
    if isinstance(case_ids, (str, bytes)) or not isinstance(case_ids, Sequence):
        raise TypeError("Los identificadores deben proporcionarse como una secuencia.")

    seen: set[str] = set()
    for case_id in case_ids:
        if not isinstance(case_id, str):
            raise TypeError("Cada identificador de caso debe ser texto.")
        if not case_id.strip():
            raise ValueError("Los identificadores de casos no pueden estar vacíos.")
        if case_id in seen:
            raise ValueError("Los identificadores de casos no pueden repetirse.")
        seen.add(case_id)

    digest = sha256_hex(canonical_json_bytes(sorted(seen)))
    return HashRef(algorithm="sha256", value=digest)

"""Operadores de diseño M1. No contienen implementaciones de tratamientos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from provregress.provenance_v2.schema import V2Error, canonical_v2


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    """Contrato de un operador pendiente de implementación en M2."""

    operator_id: str
    description: str
    requires_value: bool


OPERATORS = (
    OperatorSpec("json.scalar.replace.v1", "Sustitución proyectada de escalar JSON", True),
    OperatorSpec("json.field.remove.v1", "Supresión proyectada de campo JSON", False),
)
CATALOG = {item.operator_id: item for item in OPERATORS}
RESERVED_FIELDS = frozenset({"mutation_id", "operator_id", "target_component_id", "severity"})
MAX_POINTER_BYTES = 256


def check_pointer(pointer: str) -> None:
    """Admite exclusivamente rutas de objetos, sin índices o apéndices ordinales."""
    if (not isinstance(pointer, str) or not pointer.startswith("/")
            or len(pointer.encode("utf-8")) > MAX_POINTER_BYTES):
        raise V2Error("Se exige un JSON Pointer de objeto no vacío y acotado.")
    parts = pointer[1:].split("/")
    if len(parts) > 24:
        raise V2Error("El JSON Pointer supera la profundidad permitida.")
    for raw in parts:
        if not raw or any(raw[i] == "~" and (i + 1 == len(raw) or raw[i + 1] not in "01")
                          for i in range(len(raw))):
            raise V2Error("Escape de JSON Pointer no válido o segmento vacío.")
        part = raw.replace("~1", "/").replace("~0", "~")
        if (not part or part in RESERVED_FIELDS or part == "-" or part.isdecimal()
                or len(part.encode("utf-8")) > 96):
            raise V2Error("JSON Pointer reservado, ordinal o fuera de límites.")


def check_operator(operator_id: str, parameters: dict[str, Any]) -> OperatorSpec:
    """Rechaza operadores desconocidos y parámetros fuera del contrato canónico."""
    operator = CATALOG.get(operator_id)
    if operator is None:
        raise V2Error("Operador inexistente en el catálogo congelable de M1.")
    canonical_v2(parameters)
    if operator.requires_value:
        if set(parameters) != {"value"}:
            raise V2Error("El reemplazo escalar exige exactamente value.")
        value = parameters["value"]
        if value is not None and type(value) not in (str, int, bool):
            raise V2Error("El reemplazo solo admite valores JSON escalares.")
    elif parameters:
        raise V2Error("El operador de supresión no admite parámetros.")
    return operator

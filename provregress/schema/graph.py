"""Schemas estrictos de P2/P3, sin proyección ni alineamiento de grafos."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from provregress.schema.common import AppId, ArtifactRef, ComponentType, HashRef
from provregress.schema.events import EventError, EventType, _check_observable_metadata
from provregress.schema.manifests import NonBlankStr
from provregress.storage.hashing import canonical_json_bytes, sha256_hex


class NodeKind(str, Enum):
    """Clases de nodo de procedencia observada."""

    COMPONENT = "component"
    EVENT = "event"
    PAYLOAD = "payload"


class EdgeKind(str, Enum):
    """Relaciones respaldadas por eventos R0.7."""

    EMITS = "emits"
    OBSERVED_PARENT = "observed_parent"
    PRODUCES = "produces"


Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


class _StrictGraphModel(BaseModel):
    """Exige campos declarados y evita conversiones implícitas."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ComponentNode(_StrictGraphModel):
    """Identidad de componente concreta dentro de una ejecución."""

    node_id: Digest
    node_kind: Literal["component"]
    component_type: ComponentType
    component_id: NonBlankStr


class EventNode(_StrictGraphModel):
    """Evidencia observable de un evento, sin relaciones parentales embebidas."""

    node_id: Digest
    node_kind: Literal["event"]
    event_id: NonBlankStr
    sequence: int = Field(strict=True, ge=0)
    timestamp_utc: datetime
    event_type: EventType
    component_type: ComponentType
    component_id: NonBlankStr
    payload_hash: HashRef
    attributes: dict[str, JsonValue]
    error: EventError | None

    @field_validator("timestamp_utc")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        """Rechaza instantes sin zona horaria y normaliza a UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("El evento del grafo necesita timestamp con zona horaria.")
        return value.astimezone(timezone.utc)

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Conserva la barrera R0.7 de etiquetas privilegiadas."""
        canonical_json_bytes(value)
        _check_observable_metadata(value)
        return value


class PayloadNode(_StrictGraphModel):
    """Digest compartido entre eventos de una misma ejecución."""

    node_id: Digest
    node_kind: Literal["payload"]
    payload_hash: HashRef
    payload_ref: ArtifactRef | None

    @model_validator(mode="after")
    def validate_reference(self) -> PayloadNode:
        """La referencia del artefacto debe contener el mismo digest."""
        if self.payload_ref is not None and self.payload_ref.hash != self.payload_hash:
            raise ValueError("La referencia del payload no coincide con su digest.")
        return self


# La unión discriminada conserva exactamente los campos de cada clase de nodo.
GraphNode = Annotated[
    ComponentNode | EventNode | PayloadNode,
    Field(discriminator="node_kind"),
]


class GraphEdge(_StrictGraphModel):
    """Arista dirigida con ID y endpoints canónicos."""

    edge_id: Digest
    edge_kind: EdgeKind
    source_node_id: Digest
    target_node_id: Digest

    @model_validator(mode="after")
    def validate_identity(self) -> GraphEdge:
        """Impide IDs adulterados y autoaristas."""
        if self.source_node_id == self.target_node_id:
            raise ValueError("No se admiten autoaristas.")
        digest = sha256_hex(canonical_json_bytes([
            "r0.8.edge.v1", self.edge_kind.value, self.source_node_id, self.target_node_id,
        ]))
        if self.edge_id != digest:
            raise ValueError("El ID de arista no coincide con su identidad canónica.")
        return self


class ProvenanceGraph(_StrictGraphModel):
    """Grafo serializable; la validación topológica independiente es I2."""

    schema_version: Literal["provenance-graph-v1"]
    run_id: NonBlankStr
    app_id: AppId
    case_id: NonBlankStr
    condition_id: NonBlankStr
    repeat_index: int = Field(strict=True, ge=0)
    system_version_id: NonBlankStr
    trace_hash: HashRef | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    graph_hash: Digest

    @model_validator(mode="after")
    def validate_canonical_identity(self) -> ProvenanceGraph:
        """Verifica identidades, orden y digest sin afirmar que el grafo sea DAG."""
        ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        if ids != sorted(set(ids)):
            raise ValueError("Los nodos deben tener IDs únicos y estar ordenados.")
        if edge_ids != sorted(set(edge_ids)):
            raise ValueError("Las aristas deben tener IDs únicos y estar ordenadas.")
        for node in self.nodes:
            if isinstance(node, ComponentNode):
                identity = ["r0.8.node.v1", self.run_id, "component",
                            node.component_type.value, node.component_id]
            elif isinstance(node, EventNode):
                identity = ["r0.8.node.v1", self.run_id, "event", node.event_id]
            else:
                identity = ["r0.8.node.v1", self.run_id, "payload", node.payload_hash.value]
            if node.node_id != sha256_hex(canonical_json_bytes(identity)):
                raise ValueError("El ID de nodo no coincide con la identidad del run.")
        content = self.model_dump(mode="json", exclude={"graph_hash"})
        if self.graph_hash != sha256_hex(canonical_json_bytes(content)):
            raise ValueError("El hash del grafo no coincide con los bytes canónicos.")
        return self


_COMPONENT_VALUES = frozenset(item.value for item in ComponentType)
_EVENT_VALUES = frozenset(item.value for item in EventType)


def _check_semantic_key(value: list[str]) -> list[str]:
    """Valida claves de comparación sin contaminar con identificadores de run."""
    if not value or any(not item.strip() for item in value):
        raise ValueError("La clave semántica debe contener textos no vacíos.")
    kind = value[0]
    if kind == "component" and len(value) == 3 and value[1] in _COMPONENT_VALUES:
        return value
    if (kind == "event" and len(value) == 4 and value[1] in _COMPONENT_VALUES
            and value[3] in _EVENT_VALUES):
        return value
    if (kind == "payload" and len(value) == 2 and len(value[1]) == 64
            and all(character in "0123456789abcdef" for character in value[1])):
        return value
    raise ValueError("La clave semántica no coincide con el vocabulario P3.")


SemanticKey = Annotated[list[NonBlankStr], AfterValidator(_check_semantic_key)]


class NodeChanged(_StrictGraphModel):
    """Un evento comparable cambió sus observables permitidos."""

    key: SemanticKey
    changed_fields: list[Literal["payload_hash", "attributes", "error"]]

    @model_validator(mode="after")
    def validate_changed_fields(self) -> NodeChanged:
        if self.key[0] != "event":
            raise ValueError("Los únicos nodos modificables son eventos alineados.")
        if not self.changed_fields or self.changed_fields != sorted(set(self.changed_fields)):
            raise ValueError("Los campos cambiados deben ser no vacíos, únicos y ordenados.")
        return self


class NodeAmbiguous(_StrictGraphModel):
    """Grupo de eventos repetidos que no admite correspondencia inequívoca."""

    key: SemanticKey
    baseline_count: int = Field(strict=True, ge=0)
    candidate_count: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def validate_ambiguous_group(self) -> NodeAmbiguous:
        if self.key[0] != "event" or max(self.baseline_count, self.candidate_count) <= 1:
            raise ValueError("Solo eventos repetidos generan grupos ambiguos.")
        return self


class EdgeChange(_StrictGraphModel):
    """Arista comparable identificada por sus extremos semánticos."""

    edge_kind: EdgeKind
    source_key: SemanticKey
    target_key: SemanticKey

    @model_validator(mode="after")
    def validate_endpoint_kinds(self) -> EdgeChange:
        allowed = {
            EdgeKind.EMITS: ("component", "event"),
            EdgeKind.OBSERVED_PARENT: ("event", "event"),
            EdgeKind.PRODUCES: ("event", "payload"),
        }
        if (self.source_key[0], self.target_key[0]) != allowed[self.edge_kind]:
            raise ValueError("Los tipos de extremos no coinciden con la arista.")
        return self


class EdgeAmbiguous(EdgeChange):
    """Arista incidente en un grupo ambiguo, con lado y multiplicidad."""

    side: Literal["baseline", "candidate"]
    count: int = Field(strict=True, ge=1)


class DeltaG(_StrictGraphModel):
    """Diferencial tipado y canónico; su cálculo corresponde a I4."""

    schema_version: Literal["provenance-delta-v1"]
    baseline_run_id: NonBlankStr
    candidate_run_id: NonBlankStr
    node_added: list[SemanticKey]
    node_removed: list[SemanticKey]
    node_unchanged: list[SemanticKey]
    node_changed: list[NodeChanged]
    node_ambiguous: list[NodeAmbiguous]
    edge_added: list[EdgeChange]
    edge_removed: list[EdgeChange]
    edge_ambiguous: list[EdgeAmbiguous]
    delta_hash: Digest

    @model_validator(mode="after")
    def validate_canonical_identity(self) -> DeltaG:
        """Rechaza clasificaciones duplicadas, orden arbitrario y hashes falsos."""
        data = self.model_dump(mode="json", exclude={"delta_hash"})
        names = (
            "node_added", "node_removed", "node_unchanged", "node_changed",
            "node_ambiguous", "edge_added", "edge_removed", "edge_ambiguous",
        )
        for name in names:
            values = data[name]
            encoded = [canonical_json_bytes(value) for value in values]
            if encoded != sorted(set(encoded)):
                raise ValueError(f"{name} debe contener valores únicos y canónicos.")
        keys: list[tuple[str, ...]] = []
        for name in names[:5]:
            for value in data[name]:
                keys.append(tuple(value["key"] if isinstance(value, dict) else value))
        if len(keys) != len(set(keys)):
            raise ValueError("Un nodo no puede pertenecer a dos clases del diferencial.")
        added = {canonical_json_bytes(item) for item in data["edge_added"]}
        removed = {canonical_json_bytes(item) for item in data["edge_removed"]}
        if added.intersection(removed):
            raise ValueError("Una arista no puede estar añadida y retirada simultáneamente.")
        if self.delta_hash != sha256_hex(canonical_json_bytes(data)):
            raise ValueError("El digest del diferencial no coincide con su contenido.")
        return self

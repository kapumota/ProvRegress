"""Persistencia verificable de eventos v2 sin testigos ni etiquetas de mutación."""

from __future__ import annotations

from dataclasses import dataclass

from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import EventV2, V2Error, canonical_v2
from provregress.schema.common import ArtifactRef
from provregress.storage.artifacts import ArtifactStore
from provregress.storage.hashing import sha256_hex


@dataclass(frozen=True, slots=True)
class TraceReceiptV2:
    """Referencias direccionadas por contenido; no incluye el canal privilegiado."""

    trace_ref: ArtifactRef
    event_refs: tuple[ArtifactRef, ...]
    event_hashes: tuple[str, ...]
    graph_hash: str
    trace_hash: str


def _checked_events(events: tuple[EventV2, ...]) -> tuple[EventV2, ...]:
    if not isinstance(events, tuple) or not events:
        raise V2Error("La traza requiere eventos v2 no vacíos.")
    snapshots = tuple(
        EventV2.model_validate_json(canonical_v2(event))
        for event in events
    )
    project_trace_v2(snapshots)
    return snapshots


def persist_trace_v2(events: tuple[EventV2, ...], store: ArtifactStore) -> TraceReceiptV2:
    """Publica cada evento y el JSONL completo, después de validar DAG y dominio canónico."""
    if not isinstance(store, ArtifactStore):
        raise V2Error("Se requiere un ArtifactStore verificable.")
    checked = _checked_events(events)
    graph = project_trace_v2(checked)
    parts = [canonical_v2(event) for event in checked]
    # Rechaza explícitamente etiquetas privilegiadas y flotantes en cada evento.
    event_refs = tuple(store.put_bytes(data, media_type="application/json") for data in parts)
    content = b"".join(part + b"\n" for part in parts)
    trace_ref = store.put_bytes(content, media_type="application/x-ndjson")
    return TraceReceiptV2(
        trace_ref=trace_ref, event_refs=event_refs,
        event_hashes=tuple(sha256_hex(part) for part in parts),
        graph_hash=graph.graph_hash, trace_hash=sha256_hex(content),
    )


def replay_trace_v2(receipt: TraceReceiptV2, store: ArtifactStore) -> tuple[EventV2, ...]:
    """Relee bytes, revalida objetos y comprueba el DAG, sin confiar en hashes declarados."""
    if not isinstance(receipt, TraceReceiptV2) or not isinstance(store, ArtifactStore):
        raise V2Error("El recibo o el almacén son inválidos.")
    content = store.get_bytes(receipt.trace_ref)
    if sha256_hex(content) != receipt.trace_hash or not content.endswith(b"\n"):
        raise V2Error("Traza persistida corrupta o sin terminación canónica.")
    rows = content.splitlines(keepends=True)
    if len(rows) != len(receipt.event_refs) or len(rows) != len(receipt.event_hashes):
        raise V2Error("Cantidad de eventos distinta de las referencias.")
    events: list[EventV2] = []
    for row, ref, expected in zip(rows, receipt.event_refs, receipt.event_hashes):
        if not row.endswith(b"\n") or row.count(b"\n") != 1:
            raise V2Error("JSONL no canónico.")
        raw = row[:-1]
        if sha256_hex(raw) != expected or store.get_bytes(ref) != raw:
            raise V2Error("Evento almacenado inconsistente.")
        event = EventV2.model_validate_json(raw)
        if canonical_v2(event) != raw:
            raise V2Error("Los bytes JSONL no son canónicos.")
        events.append(event)
    checked = _checked_events(tuple(events))
    if project_trace_v2(checked).graph_hash != receipt.graph_hash:
        raise V2Error("Grafo reconstruido distinto del recibo.")
    return checked

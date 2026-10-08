"""R0.8-I5: conformidad integral del pipeline piloto y los oráculos P2/P3."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.pilot.context import build_run_context
from provregress.pilot.events import EventSinkError, JsonlEventSink
from provregress.pilot.firewall import PilotContaminationError, PilotFirewall
from provregress.provenance import align_graphs, diff_graphs, project_trace, validate_graph
from provregress.provenance.alignment import GraphComparisonError
from provregress.provenance.projector import GraphValidationError, ProjectionError
from provregress.schema.common import AppId, ComponentType, HashRef, RunStatus
from provregress.schema.events import EventEnvelope, EventType
from provregress.schema.graph import DeltaG, ProvenanceGraph
from provregress.schema.manifests import (
    DatasetManifest,
    EnvironmentManifest,
    PilotStudyManifest,
    SystemManifest,
    build_run_manifest,
    finalize_run_manifest,
)
from provregress.storage.artifacts import ArtifactIntegrityError, ArtifactStore
from provregress.storage.hashing import canonical_json_bytes, hash_case_ids, hash_file
from provregress.storage.jsonl import EventLogError, iter_events, validate_event_log


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/provenance/r0_8"
INPUTS = json.loads((FIXTURES / "inputs.json").read_bytes())
EXPECTED = json.loads((FIXTURES / "expected.json").read_bytes())
CASES = {(x["id"], x["variant"]): x for x in INPUTS["cases"]}
RESULTS = {(x["id"], x["variant"]): x for x in EXPECTED["cases"]}
GRAPH_ROLES = [(key, side) for key, value in RESULTS.items()
               if "graphs" in value for side in value["graphs"]]
PAIRED = [key for key, value in RESULTS.items() if value.get("delta") is not None]
UTC = datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc)
HASH = HashRef(algorithm="sha256", value="a" * 64)


def _events(key: tuple[str, str], role: str) -> list[EventEnvelope]:
    """Reconstruye eventos desde JSON canónico, respetando enums estrictos."""
    return [EventEnvelope.model_validate_json(canonical_json_bytes(item))
            for item in CASES[key]["traces"][role]]


def _pilot_models(version: str):
    """Construye manifests reales del piloto, sin proveedores externos."""
    study = PilotStudyManifest(
        pilot_id="study-i5", protocol_version="r0.8",
        pilot_case_ids=["pilot-a"], confirmatory_case_ids=["confirm-b"],
        pilot_case_ids_hash=hash_case_ids(["pilot-a"]),
        confirmatory_case_ids_hash=hash_case_ids(["confirm-b"]),
        analysis_plan_version="v1",
    )
    dataset = DatasetManifest(
        dataset_id="dataset-i5", app_id=AppId.A1, generator_version="g1",
        source_hashes=[HASH], split="pilot", case_ids=["pilot-a"],
        case_ids_hash=hash_case_ids(["pilot-a"]),
    )
    system = SystemManifest(
        system_id="system-i5", app_id=AppId.A1, version_id=version,
        components=[], orchestration_hash=HASH, config_hash=HASH,
    )
    environment = EnvironmentManifest(
        python_version="3.11.15", package_lock_hash=HASH, os_id="linux",
        hardware_class="cpu", git_commit="reproducible-i5", dirty=False,
        timezone="UTC", runtime_flags={},
    )
    return study, dataset, system, environment


def _record(tmp_path: Path, label: str, *, changed: bool):
    """Ejecuta una traza mínima mediante las API públicas C4-C10."""
    study, dataset, system, environment = _pilot_models(f"system-{label}")
    context = build_run_context(
        study=study, dataset=dataset, system=system, environment=environment,
        case_id="pilot-a", condition_id=label, repeat_index=0,
        run_id=f"run-i5-{label}",
    )
    folder = tmp_path / label
    store = ArtifactStore(folder / "objects")
    log = folder / "events.jsonl"
    sink = JsonlEventSink(context, store, log, clock=lambda: UTC)
    manifest = build_run_manifest(context=context, started_at=UTC - timedelta(seconds=1))
    started = sink.emit(
        event_type=EventType.RUN_STARTED,
        component_type=ComponentType.RUNTIME,
        component_id="runner",
        payload={"config": "estable"},
    )
    response = sink.emit(
        event_type=EventType.MODEL_RETURNED,
        component_type=ComponentType.MODEL,
        component_id="llm",
        payload={"respuesta": "alternativa" if changed else "original"},
        parent_event_ids=[started.event_id],
    )
    finished = finalize_run_manifest(
        manifest=manifest, sink=sink,
        ended_at=UTC + timedelta(seconds=1), status=RunStatus.SUCCEEDED,
    )
    assert finished.trace_hash == hash_file(log)
    assert finished.trace_hash.value == hashlib.sha256(log.read_bytes()).hexdigest()
    assert sink.closed
    with pytest.raises(EventSinkError):
        sink.emit(event_type=EventType.RUN_FINISHED,
                  component_type=ComponentType.RUNTIME, component_id="runner", payload={})
    readback = list(iter_events(log))
    assert readback == [started, response]
    assert validate_event_log(readback, expected_run_id=context.run_id).event_count == 2
    assert all(store.get_bytes(event.payload_ref) == canonical_json_bytes(value)
               for event, value in zip(readback, (
                   {"config": "estable"},
                   {"respuesta": "alternativa" if changed else "original"},
               )))
    graph = project_trace(iter_events(log), artifact_store=store)
    validate_graph(graph)
    assert graph.trace_hash is None  # Solo RunManifest acredita el archivo JSONL cerrado.
    assert graph.run_id == finished.run_id
    return graph, store, log, readback


@pytest.mark.parametrize("key,role", GRAPH_ROLES, ids=lambda x: str(x))
def test_e2e_golden_projection_exact_from_raw_events(key: tuple[str, str], role: str) -> None:
    """La ejecución real I2 coincide con los bytes congelados F2."""
    events = _events(key, role)
    graph = project_trace(iter(events))
    expected = RESULTS[key]["graphs"][role]
    assert canonical_json_bytes(graph) == canonical_json_bytes(expected)
    assert graph.graph_hash == expected["graph_hash"]
    assert canonical_json_bytes(graph) == canonical_json_bytes(project_trace(events))
    validate_graph(graph)


@pytest.mark.parametrize("key", PAIRED, ids=lambda key: "-".join(key))
def test_e2e_golden_delta_from_unmodified_events(key: tuple[str, str]) -> None:
    """La cadena proyector-alineador-diferenciador coincide con F2 byte a byte."""
    before = project_trace(_events(key, "baseline"))
    after = project_trace(_events(key, "candidate"))
    pairing = align_graphs(before, after)
    assert pairing.baseline_run_id == before.run_id
    assert pairing.candidate_run_id == after.run_id
    delta = diff_graphs(before, after)
    assert isinstance(delta, DeltaG)
    assert canonical_json_bytes(delta) == canonical_json_bytes(RESULTS[key]["delta"])
    assert delta.delta_hash == RESULTS[key]["delta"]["delta_hash"]
    assert canonical_json_bytes(diff_graphs(before, after)) == canonical_json_bytes(delta)


def test_e2e_pilot_jsonl_store_manifests_and_delta(tmp_path: Path) -> None:
    """Integra desde C4 hasta P3 con almacenamiento real y hashes comprobados."""
    before, _, _, _ = _record(tmp_path, "baseline", changed=False)
    after, _, _, _ = _record(tmp_path, "candidate", changed=True)
    delta = diff_graphs(before, after)
    assert delta.baseline_run_id == before.run_id
    assert delta.candidate_run_id == after.run_id
    assert len(delta.node_changed) == 1
    assert delta.node_changed[0].changed_fields == ["payload_hash"]
    assert len(delta.node_added) == len(delta.node_removed) == 1
    assert len(delta.edge_added) == len(delta.edge_removed) == 1
    assert delta.node_ambiguous == []
    assert canonical_json_bytes(delta) == canonical_json_bytes(diff_graphs(before, after))


def test_e2e_pilot_without_behavioral_change_is_empty_delta(tmp_path: Path) -> None:
    """Un cambio de run/condición/versión no crea regresión observable."""
    before, _, _, _ = _record(tmp_path, "baseline", changed=False)
    after, _, _, _ = _record(tmp_path, "candidate", changed=False)
    delta = diff_graphs(before, after)
    assert len(delta.node_unchanged) == len(before.nodes) == len(after.nodes)
    assert not (delta.node_changed or delta.node_added or delta.node_removed
                or delta.node_ambiguous or delta.edge_added or delta.edge_removed
                or delta.edge_ambiguous)


def test_e2e_corrupted_payload_prevents_projection(tmp_path: Path) -> None:
    """Los bytes alterados detienen el pipeline, no producen grafos parciales."""
    _, store, log, events = _record(tmp_path, "baseline", changed=False)
    ref = events[-1].payload_ref
    assert ref is not None
    (store.root / ref.relative_path).write_bytes(b"contenido adulterado")
    with pytest.raises(ArtifactIntegrityError):
        project_trace(iter_events(log), artifact_store=store)
    # Sin ArtifactStore solo se verifica la declaración, nunca los bytes.
    projected = project_trace(iter_events(log))
    assert projected.trace_hash is None


def test_e2e_corrupted_jsonl_prevents_read_and_projection(tmp_path: Path) -> None:
    """Un log alterado se rechaza antes de construir un resultado P2."""
    _, _, log, _ = _record(tmp_path, "baseline", changed=False)
    log.write_bytes(log.read_bytes() + b'{"fragmento":invalido}\n')
    with pytest.raises(EventLogError):
        list(iter_events(log))
    with pytest.raises(ProjectionError):
        project_trace(iter_events(log))


def test_e2e_rejected_confirmatory_case_never_builds_context() -> None:
    """El firewall P0 no autoriza accidentalmente entradas confirmatorias."""
    study, dataset, system, environment = _pilot_models("v1")
    with pytest.raises(PilotContaminationError):
        PilotFirewall(study).assert_pilot_case("confirm-b")
    with pytest.raises(PilotContaminationError):
        build_run_context(
            study=study, dataset=dataset, system=system, environment=environment,
            case_id="confirm-b", condition_id="baseline", repeat_index=0,
        )


@pytest.mark.parametrize("variant", ["future-parent", "sequence-gap", "cycle-via-future-parent"])
def test_e2e_g07_invalid_trace_stops_before_projection(variant: str) -> None:
    with pytest.raises(ProjectionError):
        project_trace(_events(("G07", variant), "baseline"))


def test_e2e_g07_explicit_graph_cycle_rejected() -> None:
    content = CASES[("G07", "explicit-dag-cycle")]["graph_to_validate"]
    with pytest.raises(GraphValidationError, match="ciclo"):
        validate_graph(content)


@pytest.mark.parametrize("variant,code", [
    ("case-mismatch", "case_mismatch"),
    ("app-mismatch", "app_mismatch"),
])
def test_e2e_g08_incompatible_graphs_rejected(variant: str, code: str) -> None:
    key = ("G08", variant)
    left = project_trace(_events(key, "baseline"))
    right = project_trace(_events(key, "candidate"))
    with pytest.raises(GraphComparisonError) as caught:
        diff_graphs(left, right)
    assert caught.value.code == code


@pytest.mark.parametrize("variant", ["reserved-attribute", "nested-reserved-attribute"])
def test_e2e_g09_reserved_observables_rejected_by_schema(variant: str) -> None:
    raw = CASES[("G09", variant)]["traces"]["baseline"][0]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(canonical_json_bytes(raw))


def test_e2e_cross_run_events_cannot_be_mixed() -> None:
    """No se proyectan trazas de distintas ejecuciones en un grafo común."""
    before = _events(("G02", "equivalent-unique-event"), "baseline")
    after = _events(("G02", "equivalent-unique-event"), "candidate")
    forged = after[0].model_copy(update={"sequence": 1})
    with pytest.raises(ProjectionError):
        project_trace([before[0], forged])


def test_e2e_g06_ambiguity_is_not_silently_resolved() -> None:
    key = ("G06", "ambiguous-repeated-event")
    before = project_trace(_events(key, "baseline"))
    after = project_trace(_events(key, "candidate"))
    delta = diff_graphs(before, after)
    assert len(delta.node_ambiguous) == 1
    assert delta.node_ambiguous[0].baseline_count == 2
    assert delta.node_ambiguous[0].candidate_count == 2
    assert len(delta.edge_ambiguous) == 4
    assert not (delta.node_changed or delta.node_added or delta.node_removed)


def test_e2e_g05_order_alone_is_not_regression() -> None:
    key = ("G05", "independent-reorder")
    delta = diff_graphs(project_trace(_events(key, "baseline")),
                        project_trace(_events(key, "candidate")))
    assert not (delta.node_added or delta.node_removed or delta.node_changed
                or delta.node_ambiguous or delta.edge_added or delta.edge_removed
                or delta.edge_ambiguous)


def test_frozen_oracle_files_remain_byte_identical() -> None:
    """Comprueba SHA-256 documentados, sin regenerar golden outputs."""
    expected_sha = {
        "inputs.json": "9d2be2dd2d894e7c4c7508cad0bb6160147dc01d82e3d1090e7903a69d9eb242",
        "expected.json": "47fd5e198f25704ee0fbc6363ea3621754397aad9ca72507be4a68752fa4be50",
    }
    for name, expected in expected_sha.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == expected


def test_cross_process_projection_is_reproducible() -> None:
    """Comprueba hashes iguales también al ejecutar un nuevo intérprete Python."""
    script = """
import json
from pathlib import Path
from provregress.schema.events import EventEnvelope
from provregress.storage.hashing import canonical_json_bytes
from provregress.provenance import project_trace
source = json.loads(Path('tests/fixtures/provenance/r0_8/inputs.json').read_bytes())
case = next(row for row in source['cases'] if row['id'] == 'G01')
events = [EventEnvelope.model_validate_json(canonical_json_bytes(row)) for row in case['traces']['baseline']]
print(project_trace(events).graph_hash)
"""
    first = subprocess.check_output([sys.executable, "-c", script], cwd=ROOT, text=True).strip()
    second = subprocess.check_output([sys.executable, "-c", script], cwd=ROOT, text=True).strip()
    expected = RESULTS[("G01", "reproject-and-deduplicate")]["graphs"]["baseline"]["graph_hash"]
    assert first == second == expected


def test_reference_python_does_not_import_legacy_or_mutation_engine() -> None:
    """Confirma separación de imports, sin ejecutar proveedores externos."""
    import ast
    package = ROOT / "provregress/provenance"
    sources = [path for path in package.glob("*.py") if path.name != "__pycache__"]
    assert sources
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                assert not any(alias.name.startswith("llmtestlab") for alias in item.names)
            elif isinstance(item, ast.ImportFrom):
                assert not (item.module or "").startswith("llmtestlab")
        text = path.read_text(encoding="utf-8")
        assert "MutationManifest" not in text

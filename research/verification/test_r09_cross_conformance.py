"""R0.9-R4: compara dos procesos independientes sin alterar golden F2/F3."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from provregress.provenance import diff_graphs, project_trace, validate_graph
from provregress.provenance.alignment import GraphComparisonError
from provregress.schema.events import EventEnvelope
from provregress.schema.graph import ProvenanceGraph
from provregress.storage.hashing import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/provenance/r0_8"
SOURCES = json.loads((FIXTURES / "inputs.json").read_bytes())
EXPECTED = json.loads((FIXTURES / "expected.json").read_bytes())
INPUTS = {(case["id"], case["variant"]): case for case in SOURCES["cases"]}
OUTPUTS = {(case["id"], case["variant"]): case for case in EXPECTED["cases"]}
POSITIVE = [key for key, value in OUTPUTS.items() if "graphs" in value]
PAIRED = [key for key, value in OUTPUTS.items() if value.get("delta") is not None]
NEGATIVE = [key for key, value in OUTPUTS.items() if "error" in value]


def rust_bin() -> Path:
    """La ausencia del ejecutable es un fallo, nunca una omisión silenciosa."""
    configured = os.environ.get("PROVREGRESS_RUST_BIN")
    candidate = Path(configured) if configured else ROOT / "target/debug/provregress-conformance"
    assert candidate.is_file(), f"Falta el binario Rust: {candidate}. Ejecuta cargo build --locked --bin provregress-conformance."
    return candidate


def rust_call(request: dict, *, success: bool = True) -> bytes:
    """Ejecuta el binario Rust en un proceso separado, sin compartir memoria Python."""
    process = subprocess.run(
        [str(rust_bin())],
        input=canonical_json_bytes(request),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if success:
        assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
        assert process.stdout.endswith(b"\n")
        return process.stdout[:-1]
    assert process.returncode != 0
    assert process.stdout == b"", "Una operación rechazada no debe emitir resultados parciales."
    return process.stderr


def python_events(raw: list[dict]) -> list[EventEnvelope]:
    """Revalida enums y UTC desde JSON, tal como realiza el contrato R0.7."""
    return [EventEnvelope.model_validate_json(canonical_json_bytes(item)) for item in raw]


@pytest.mark.parametrize("key", POSITIVE, ids=lambda item: "-".join(item))
def test_projection_matches_python_and_golden_bytes(key: tuple[str, str]) -> None:
    inputs = INPUTS[key]["traces"]
    outputs = OUTPUTS[key]["graphs"]
    for role, raw in inputs.items():
        python = canonical_json_bytes(project_trace(python_events(raw)))
        rust = rust_call({"op": "project", "events": raw})
        golden = canonical_json_bytes(outputs[role])
        assert python == rust == golden
        assert json.loads(rust)["trace_hash"] is None


@pytest.mark.parametrize("key", PAIRED, ids=lambda item: "-".join(item))
def test_delta_matches_python_and_golden_bytes(key: tuple[str, str]) -> None:
    sources = INPUTS[key]["traces"]
    before = project_trace(python_events(sources["baseline"]))
    after = project_trace(python_events(sources["candidate"]))
    python = canonical_json_bytes(diff_graphs(before, after))
    rust = rust_call({"op": "diff", **sources})
    golden = canonical_json_bytes(OUTPUTS[key]["delta"])
    assert python == rust == golden


@pytest.mark.parametrize("key", NEGATIVE, ids=lambda item: "-".join(item))
def test_both_runtimes_reject_invalid_cases(key: tuple[str, str]) -> None:
    case = INPUTS[key]
    stage = OUTPUTS[key]["error"]["stage"]
    raw = case["traces"]
    if stage == "schema":
        with pytest.raises(ValidationError):
            python_events(raw["baseline"])
        rust_call({"op": "project", "events": raw["baseline"]}, success=False)
    elif stage == "projection":
        from provregress.provenance.projector import ProjectionError
        with pytest.raises(ProjectionError):
            project_trace(python_events(raw["baseline"]))
        rust_call({"op": "project", "events": raw["baseline"]}, success=False)
    elif stage == "comparison":
        before = project_trace(python_events(raw["baseline"]))
        after = project_trace(python_events(raw["candidate"]))
        with pytest.raises(GraphComparisonError):
            diff_graphs(before, after)
        rejection = rust_call({"op": "diff", **raw}, success=False)
        assert OUTPUTS[key]["error"]["code"].encode() in rejection
    elif stage == "graph_validation":
        graph = case["graph_to_validate"]
        model = ProvenanceGraph.model_validate_json(canonical_json_bytes(graph))
        from provregress.provenance.projector import GraphValidationError
        with pytest.raises(GraphValidationError):
            validate_graph(model)
        rust_call({"op": "validate_dag", "graph": graph}, success=False)
    else:
        pytest.fail(f"Etapa inesperada: {stage}")


@pytest.mark.parametrize("value", [
    {"nested": [1.0, -0.0, 0.0001, 0.00001, 1e-7, 1e16, 1e21]},
    {"a": {"β": "España", "á": True}, "z": [0.1, 1.2345678901234567]},
    {"v": -1e-7, "x": "línea\ntexto"},
])
def test_numeric_and_unicode_canonical_json(value: dict) -> None:
    expected = canonical_json_bytes(value)
    assert rust_call({"op": "canonical", "value": value}) == expected


def test_floats_and_timezone_in_provenance_graph() -> None:
    raw = dict(INPUTS[("G02", "equivalent-unique-event")]["traces"]["baseline"][0])
    raw["timestamp_utc"] = "2026-10-08T13:00:00-04:00"
    raw["attributes"] = {"scores": [0.00001, 1e-7, 1e16, -0.0], "texto": "España"}
    raw["error"] = {"category": "audit", "message": "Caso de prueba",
                    "retryable": False, "details": {"score": 0.00001}}
    python = canonical_json_bytes(project_trace(python_events([raw])))
    rust = rust_call({"op": "project", "events": [raw]})
    assert python == rust
    assert json.loads(rust)["nodes"]


def test_separate_rust_processes_produce_identical_bytes() -> None:
    traces = INPUTS[("G03", "payload-change")]["traces"]
    request = {"op": "diff", **traces}
    first = rust_call(request)
    assert all(rust_call(request) == first for _ in range(3))


def test_no_legacy_or_treatment_details_in_rust_adapter() -> None:
    source = (ROOT / "rust/provregress-reference/src/bin/provregress-conformance.rs").read_text()
    assert "llmtestlab" not in source
    assert "MutationManifest" not in source
    assert rust_bin().is_file()

"""R0.9-R5: auditoría independiente de contratos, oráculos y puertas de CI.

No ejecuta el binario Rust; esa prueba permanece en el job cruzado de Actions.
"""

from __future__ import annotations

import ast
from collections import Counter, deque
import hashlib
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/provenance/r0_8"
FROZEN = {
    "research/preregistration/R0.8-P2-P3-contract.md":
        "bfb953563fdeb259660fdb1a792c9cd6dc512123534d922bdccd45d21ea8e690",
    "research/preregistration/R0.8-P2-P3-golden-fixtures.md":
        "0b0510da11cc70ad4d8860453a6d1921187a37aedae674877473d7077d37ef06",
    "tests/fixtures/provenance/r0_8/inputs.json":
        "9d2be2dd2d894e7c4c7508cad0bb6160147dc01d82e3d1090e7903a69d9eb242",
    "tests/fixtures/provenance/r0_8/expected.json":
        "47fd5e198f25704ee0fbc6363ea3621754397aad9ca72507be4a68752fa4be50",
    "tests/fixtures/provenance/r0_8/SHA256SUMS":
        "77afade80cad9ea95050cda679b496b45c4abc926d471581f1fff7901362e446",
    "tests/provregress/test_provenance_golden_fixtures.py":
        "484f7c1f847d9ecff715dffb25eaff540e436ff6a488438a504b8dbcfde3e55e",
}


def _canonical(value: object) -> bytes:
    """Oráculo de auditoría basado en la biblioteca estándar."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_bytes())


INPUTS = _read_json("inputs.json")
EXPECTED = _read_json("expected.json")
GOLDEN = {(record["id"], record["variant"]): record for record in EXPECTED["cases"]}
SOURCES = {(record["id"], record["variant"]): record for record in INPUTS["cases"]}
GRAPHS = [(key, side, graph) for key, case in GOLDEN.items()
          for side, graph in case.get("graphs", {}).items()]
DELTAS = [(key, case["delta"]) for key, case in GOLDEN.items()
          if case.get("delta") is not None]
NEGATIVES = [(key, case["error"]) for key, case in GOLDEN.items()
             if "error" in case]


@pytest.mark.parametrize("path,expected", sorted(FROZEN.items()))
def test_r08_frozen_bytes_are_unchanged(path: str, expected: str) -> None:
    """Una actualización silenciosa de los oráculos debe romper el gate."""
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected


def test_r09_goldens_have_the_exact_frozen_cardinality_and_json() -> None:
    """Revisa el índice de corpus antes de usar sus resultados como evidencia."""
    assert INPUTS["schema_version"] == "r0.8-golden-inputs-v1"
    assert EXPECTED["schema_version"] == "r0.8-golden-expected-v1"
    assert len(GOLDEN) == len(SOURCES) == 15
    assert set(GOLDEN) == set(SOURCES)
    assert {key[0] for key in GOLDEN} == {f"G{i:02d}" for i in range(1, 11)}
    assert len(GRAPHS) == 12
    assert len(DELTAS) == 5
    assert len(NEGATIVES) == 8
    for filename in ("inputs.json", "expected.json"):
        assert (FIXTURES / filename).read_bytes() == _canonical(_read_json(filename)) + b"\n"


@pytest.mark.parametrize("key,side,graph", GRAPHS,
                         ids=lambda item: str(item)[:80])
def test_r09_golden_graphs_validate_independently(key: tuple[str, str],
                                                  side: str, graph: dict) -> None:
    """Audita DAG y hashes sin invocar el proyector de Python ni de Rust."""
    assert graph["schema_version"] == "provenance-graph-v1"
    assert graph["trace_hash"] is None
    assert graph["graph_hash"] == _hash({k: v for k, v in graph.items() if k != "graph_hash"})
    run_id = graph["run_id"]
    nodes = {n["node_id"]: n for n in graph["nodes"]}
    assert len(nodes) == len(graph["nodes"])
    assert list(nodes) == sorted(nodes)
    seq = []
    for node_id, node in nodes.items():
        kind = node["node_kind"]
        if kind == "component":
            parts = ["r0.8.node.v1", run_id, kind, node["component_type"], node["component_id"]]
        elif kind == "event":
            parts = ["r0.8.node.v1", run_id, kind, node["event_id"]]
            seq.append(node["sequence"])
        else:
            assert kind == "payload"
            parts = ["r0.8.node.v1", run_id, kind, node["payload_hash"]["value"]]
        assert node_id == _hash(parts), (key, side, kind)
    assert sorted(seq) == list(range(len(seq)))
    assert seq
    edges = {e["edge_id"]: e for e in graph["edges"]}
    assert len(edges) == len(graph["edges"])
    assert list(edges) == sorted(edges)
    indegree = {i: 0 for i in nodes}
    adj = {i: [] for i in nodes}
    degree = Counter()
    allowed = {"emits": ("component", "event"),
               "observed_parent": ("event", "event"),
               "produces": ("event", "payload")}
    for edge_id, edge in edges.items():
        src, dst, typ = edge["source_node_id"], edge["target_node_id"], edge["edge_kind"]
        assert src in nodes and dst in nodes and src != dst
        assert (nodes[src]["node_kind"], nodes[dst]["node_kind"]) == allowed[typ]
        assert edge_id == _hash(["r0.8.edge.v1", typ, src, dst])
        if typ == "observed_parent":
            assert nodes[src]["sequence"] < nodes[dst]["sequence"]
        if typ in {"emits", "produces"}:
            event_id = dst if typ == "emits" else src
            degree[(event_id, typ)] += 1
        adj[src].append(dst)
        indegree[dst] += 1
    for node_id, node in nodes.items():
        if node["node_kind"] == "event":
            assert degree[(node_id, "emits")] == degree[(node_id, "produces")] == 1
    queue = deque(i for i, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        cur = queue.popleft()
        visited += 1
        for nxt in adj[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    assert visited == len(nodes), (key, side, "ciclo")


@pytest.mark.parametrize("key,delta", DELTAS)
def test_r09_delta_hashes_and_groups_are_immutable(key: tuple[str, str],
                                                     delta: dict) -> None:
    """Rechaza resultados parciales, duplicados y clasificación contradictoria."""
    assert delta["schema_version"] == "provenance-delta-v1"
    assert delta["delta_hash"] == _hash({k: v for k, v in delta.items() if k != "delta_hash"})
    keys = []
    for name in ("node_added", "node_removed", "node_unchanged",
                 "node_changed", "node_ambiguous"):
        entries = delta[name]
        assert entries == sorted(entries, key=_canonical), (key, name)
        for item in entries:
            keys.append(tuple(item["key"] if isinstance(item, dict) else item))
    assert len(keys) == len(set(keys))
    for name in ("edge_added", "edge_removed", "edge_ambiguous"):
        entries = delta[name]
        assert entries == sorted(entries, key=_canonical)
    assert {_canonical(e) for e in delta["edge_added"]}.isdisjoint(
        {_canonical(e) for e in delta["edge_removed"]})
    assert delta["baseline_run_id"] == GOLDEN[key]["graphs"]["baseline"]["run_id"]
    assert delta["candidate_run_id"] == GOLDEN[key]["graphs"]["candidate"]["run_id"]


@pytest.mark.parametrize("key,error", NEGATIVES)
def test_r09_rejected_cases_do_not_claim_partial_results(key: tuple[str, str],
                                                           error: dict) -> None:
    """Asegura que el corpus describe rechazos fail-closed."""
    entry = GOLDEN[key]
    assert set(entry) == {"id", "variant", "error"}
    assert set(error) == {"stage", "code"}
    assert error["stage"] in {"schema", "projection", "graph_validation", "comparison"}


def test_r09_ci_requires_three_real_jobs_and_golden_hashes() -> None:
    """Impide liberar R5 si desaparece un gate ejecutado en Actions."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    assert {"python", "rust", "cross_language"}.issubset(jobs)
    assert {"ubuntu-24.04"} == {jobs[j]["runs-on"] for j in ("python", "rust", "cross_language")}
    commands = {name: "\n".join(str(step.get("run", "")) for step in jobs[name]["steps"])
                for name in ("python", "rust", "cross_language")}
    assert "python -m pytest -q" in commands["python"]
    assert "python -m pip check" in commands["python"]
    assert "sha256sum -c SHA256SUMS" in commands["python"]
    assert "cargo fmt --all --check" in commands["rust"]
    assert "cargo test --workspace --locked" in commands["rust"]
    assert "cargo clippy --workspace --all-targets --locked -- -D warnings" in commands["rust"]
    assert "cargo build --workspace --locked --bin provregress-conformance" in commands["cross_language"]
    assert "research/verification/test_r09_cross_conformance.py" in commands["cross_language"]
    assert "sha256sum -c SHA256SUMS" in commands["cross_language"]


def test_r09_cross_suite_fails_when_rust_binary_is_missing() -> None:
    """El gate cruzado no puede convertir ausencia de Rust en un skip."""
    source = (ROOT / "research/verification/test_r09_cross_conformance.py").read_text()
    assert 'assert candidate.is_file()' in source
    assert "pytest.skip" not in source
    assert "PROVREGRESS_RUST_BIN" in source


def test_r09_rust_surfaces_and_lockfile_are_versioned() -> None:
    """Confirma que el workspace contiene las cuatro operaciones de referencia."""
    assert (ROOT / "Cargo.lock").is_file()
    assert (ROOT / "Cargo.toml").is_file()
    expected = {
        "projector.rs": ("pub fn project_trace", "pub fn validate_dag"),
        "alignment.rs": ("pub fn align_graphs",),
        "diff.rs": ("pub fn diff_graphs",),
        "canonical.rs": ("pub fn canonical_json_bytes",),
    }
    source_dir = ROOT / "rust/provregress-reference/src"
    for filename, signatures in expected.items():
        content = (source_dir / filename).read_text()
        for signature in signatures:
            assert signature in content, (filename, signature)
    assert (source_dir / "bin/provregress-conformance.rs").is_file()


def test_r09_no_legacy_or_privileged_imports_in_reference_engines() -> None:
    """Impide dependencias directas del núcleo científico con el paquete legacy."""
    rust_sources = (ROOT / "rust/provregress-reference/src").rglob("*.rs")
    for path in rust_sources:
        source = path.read_text()
        assert "llmtestlab" not in source, path
        assert "MutationManifest" not in source, path
    python_root = ROOT / "provregress/provenance"
    assert python_root.is_dir()
    python_sources = list(python_root.glob("*.py"))
    assert python_sources
    for path in python_sources:
        tree = ast.parse(path.read_text(), filename=str(path))
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                assert all(n.name.split(".")[0] != "llmtestlab" for n in item.names)
            elif isinstance(item, ast.ImportFrom) and item.module:
                assert item.module.split(".")[0] != "llmtestlab"

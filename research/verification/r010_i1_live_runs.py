"""Ejecuta A2/A3 locales y genera evidencia observable y testigos separados."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from provregress.provenance_v2.comparison import (
    assert_pilot_alignment_v2, compare_graphs_v2, topology_profile_v2,
)
from provregress.provenance_v2.live_workloads import (
    assert_external_witness, comparison_policy, demo_study,
    run_rag_local, run_tools_local,
)
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import canonical_v2
from provregress.schema.common import AppId
from provregress.storage.hashing import sha256_hex


def execute_pair(app_id: AppId, *, scenario: str = "insert", output: Path | None = None) -> dict:
    """Genera ejecuciones reales, verifica el testigo y calcula DeltaV2."""
    runner = run_rag_local if app_id == AppId.A2 else run_tools_local
    study = demo_study()
    baseline = runner(study=study, run_id=f"i1-{app_id.value}-baseline")
    candidate = runner(study=study, run_id=f"i1-{app_id.value}-{scenario}", scenario=scenario)
    assert_external_witness(baseline, candidate)
    before = project_trace_v2(baseline.events)
    after = project_trace_v2(candidate.events)
    policy = comparison_policy(app_id)
    delta = compare_graphs_v2(before, after, policy)
    # El objetivo de prueba es la primera operación de trabajo, no el root ni el join.
    target = next(event.key for event in before.events
                  if event.event_type.value in ("retrieval.returned", "tool.returned"))
    assert_pilot_alignment_v2(before, after, delta, policy=policy, target_keys=[target])
    summary = {
        "app_id": app_id.value,
        "scenario": scenario,
        "baseline_calls": len(baseline.completed_calls),
        "candidate_calls": len(candidate.completed_calls),
        "baseline_branched": topology_profile_v2(before)["branched"],
        "candidate_branched": topology_profile_v2(after)["branched"],
        "added_events": len(delta.added_events),
        "changed_events": len(delta.changed_events),
        "ambiguous_events": len(delta.ambiguous_events),
        "ambiguous_event_rate": delta.ambiguous_event_rate,
        "delta_hash": delta.delta_hash,
    }
    if output is not None:
        destination = Path(output)
        if destination.exists():
            raise FileExistsError("La ruta de salida ya existe: evitar sobrescribir evidencia.")
        destination.mkdir(parents=True, mode=0o700)
        observed = destination / "observable"
        privileged = destination / "privileged"
        observed.mkdir(mode=0o700)
        privileged.mkdir(mode=0o700)
        for side, execution, graph in (("baseline", baseline, before), ("candidate", candidate, after)):
            with (observed / f"{side}.jsonl").open("xb") as handle:
                handle.write(execution.observable_jsonl())
            with (observed / f"{side}-graph.json").open("xb") as handle:
                handle.write(canonical_v2(graph) + b"\n")
            protected = privileged / f"{side}-witness.json"
            with protected.open("xb") as handle:
                handle.write(execution.witness_json())
            protected.chmod(0o600)
        with (observed / "delta.json").open("xb") as handle:
            handle.write(canonical_v2(delta) + b"\n")
        with (privileged / "execution-hashes.json").open("xb") as handle:
            handle.write(canonical_v2({
                "baseline_sha256": sha256_hex(baseline.observable_jsonl()),
                "candidate_sha256": sha256_hex(candidate.observable_jsonl()),
            }) + b"\n")
        (privileged / "execution-hashes.json").chmod(0o600)
        summary["evidence_directory"] = str(destination)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecutar cargas observables A2/A3 en modo local I1")
    parser.add_argument("--app", choices=["a2", "a3"], required=True)
    parser.add_argument("--scenario", choices=["baseline", "insert", "reorder", "noise", "functional", "rekey", "retry"], default="insert")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    app = AppId.A2 if args.app == "a2" else AppId.A3
    summary = execute_pair(app, scenario=args.scenario, output=args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

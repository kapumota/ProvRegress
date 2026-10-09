"""Ejecutor I3: corpus local, evidencia persistente y oráculo separado."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.independent_audit import audit_dynamic_pair
from provregress.provenance_v2.live_workloads import DEFAULT_INPUTS, demo_study
from provregress.provenance_v2.persistent import persist_trace_v2, replay_trace_v2
from provregress.schema.common import AppId
from provregress.storage.artifacts import ArtifactStore

ANNOTATIONS = Path(__file__).resolve().parents[2] / "tests/fixtures/provenance/r0_10_i3/annotations.json"


def execute(output_dir: Path) -> list[dict[str, object]]:
    if output_dir.exists():
        raise ValueError("El directorio de salida debe ser nuevo para no sustituir evidencia.")
    output_dir.mkdir(parents=True)
    store = ArtifactStore(output_dir / "artifacts")
    study = demo_study()
    base = json.loads((DEFAULT_INPUTS / "catalog.json").read_text(encoding="utf-8"))
    changed = {**base, "enable_discount_step": True}
    candidate_catalog = output_dir / "candidate-catalog.json"
    candidate_catalog.write_text(json.dumps(changed,sort_keys=True),encoding="utf-8")
    configs = [
        (AppId.A2, run_rag_dynamic(study=study, run_id="i3-a2-base", top_k=3),
         run_rag_dynamic(study=study, run_id="i3-a2-new", top_k=4)),
        (AppId.A3, run_tools_dynamic(study=study, run_id="i3-a3-base"),
         run_tools_dynamic(study=study, run_id="i3-a3-new", catalog_path=candidate_catalog)),
    ]
    summaries = []
    for app, before, after in configs:
        receipts = [persist_trace_v2(run.events, store) for run in (before, after)]
        for original, receipt in zip((before, after), receipts):
            if replay_trace_v2(receipt, store) != original.events:
                raise ValueError("Replay v2 no reprodujo exactamente los eventos.")
        report = audit_dynamic_pair(before, after, app_id=app, annotations_path=ANNOTATIONS)
        summaries.append(report)
    (output_dir / "summary.json").write_text(json.dumps(summaries,indent=2,sort_keys=True)+"\n", encoding="utf-8")
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditoría dinámica R0.10-I3")
    parser.add_argument("--output-dir", type=Path, help="Directorio NUEVO para resultados")
    options = parser.parse_args()
    if options.output_dir is None:
        with tempfile.TemporaryDirectory(prefix="provregress-i3-") as temp:
            results = execute(Path(temp) / "results")
    else:
        results = execute(options.output_dir)
    print(json.dumps(results,ensure_ascii=False,sort_keys=True))


if __name__ == "__main__":
    main()

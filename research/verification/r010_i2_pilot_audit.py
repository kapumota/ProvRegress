"""R0.10-I2: auditoría repetida de identidades y cobertura sobre A2/A3 locales."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from provregress.provenance_v2.live_workloads import (
    comparison_policy, demo_study, run_rag_local, run_tools_local,
)
from provregress.provenance_v2.pilot_audit import (
    PairAuditV2, assert_i2_cohort_gate, audit_digest_v2, audit_execution_pair_v2,
)
from provregress.provenance_v2.schema import V2Error, canonical_v2
from provregress.schema.common import AppId

_SCENARIOS = ("baseline", "insert", "reorder", "noise", "functional", "retry")


def _scenario_contract(app: AppId, scenario: str) -> dict[str, tuple[str, ...]]:
    """Oráculo privilegiado declarativo, independiente de DeltaV2 calculado."""
    if app == AppId.A2:
        targets = ("rag.refund", "rag.shipping", "rag.returns", "rag.answer")
        changes = ("rag.refund", "rag.answer") if scenario == "functional" else ()
        added = ("rag.tracking",) if scenario == "insert" else (
            ("rag.refund.retry",) if scenario == "retry" else ())
    elif app == AppId.A3:
        targets = ("tools.inventory", "tools.tax", "tools.receipt", "tools.finish")
        changes = ("tools.inventory", "tools.finish") if scenario == "functional" else ()
        added = ("tools.discount",) if scenario == "insert" else (
            ("tools.inventory.retry",) if scenario == "retry" else ())
    else:
        raise V2Error("La auditoría I2 solo está definida para A2 y A3.")
    return {"target_logical_ids": targets, "expected_changed_logical_ids": changes,
            "expected_added_logical_ids": added}


def audit_i2_local(*, repeats: int = 3, output: Path | None = None) -> dict[str, Any]:
    """Exige todos los escenarios y un rekey rechazado por cada aplicación y repetición."""
    if type(repeats) is not int or not (1 <= repeats <= 20):
        raise V2Error("I2 requiere entre 1 y 20 repeticiones explícitas.")
    study = demo_study()
    approved: list[PairAuditV2] = []
    negative: list[PairAuditV2] = []
    for app, runner in ((AppId.A2, run_rag_local), (AppId.A3, run_tools_local)):
        for i in range(repeats):
            baseline = runner(study=study, run_id=f"i2-{app.value}-{i}-baseline")
            for scenario in (*_SCENARIOS, "rekey"):
                candidate = runner(study=study, run_id=f"i2-{app.value}-{i}-{scenario}",
                                   scenario=scenario)
                report = audit_execution_pair_v2(
                    baseline, candidate, comparison_policy(app), scenario=scenario,
                    **_scenario_contract(app, scenario),
                )
                (negative if scenario == "rekey" else approved).append(report)
    summary = assert_i2_cohort_gate(approved, repeats=repeats)
    if len(negative) != 2 * repeats or any(
        r.passed or r.false_pairs < 1 or r.missed_pairs < 1 for r in negative
    ):
        raise V2Error("El control adversarial de identidades intercambiadas no fue detectado.")
    summary["negative_rekey_rejections"] = len(negative)
    summary["status"] = "pass_local_instrumentation"
    # La huella no se basa en timestamps ni hashes de run: métricas reproducibles.
    summary["audit_hash"] = audit_digest_v2(summary)
    if output is not None:
        destination = Path(output)
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        protected = destination / "privileged"
        protected.mkdir(mode=0o700)
        with (protected / "pair-reports.json").open("xb") as handle:
            handle.write(canonical_v2({
                "schema_version": "r0.10-i2-privileged-v1",
                "accepted": [r.privileged_dict() for r in approved],
                "negative_controls": [r.privileged_dict() for r in negative],
            }) + b"\n")
        (protected / "pair-reports.json").chmod(0o600)
        with (destination / "audit-summary.json").open("xb") as handle:
            handle.write(canonical_v2(summary) + b"\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditoría I2 de cobertura e identidades A2/A3")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_i2_local(repeats=args.repeats, output=args.output_dir),
                     ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

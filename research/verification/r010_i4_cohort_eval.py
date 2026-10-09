"""Ejecuta la cohorte predeclarada R0.10-I4 sin seleccionar escenarios."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from provregress.provenance_v2.cohort_audit import run_cohort

ROOT = Path(__file__).resolve().parents[2]
COHORT = ROOT / "research/preregistration/R0.10-I4-cohort.json"
ANNOTATIONS = ROOT / "tests/fixtures/provenance/r0_10_i3/annotations.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluación controlada de cohorte R0.10-I4")
    parser.add_argument("--output-dir", type=Path, help="Directorio nuevo para evidencia")
    options = parser.parse_args()
    if options.output_dir is None:
        with tempfile.TemporaryDirectory(prefix="provregress-i4-") as temporary:
            report = run_cohort(cohort_path=COHORT, annotations_path=ANNOTATIONS,
                                output_dir=Path(temporary) / "resultados")
    else:
        report = run_cohort(cohort_path=COHORT, annotations_path=ANNOTATIONS,
                            output_dir=options.output_dir)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

"""Ejecuta cuatro casos NO confirmatorios A2/A3 sobre archivos de ejemplo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from provregress.mutation_v2.local_smoke import run_local_smoke_m2
from provregress.mutation_v2.system_treatments import make_request, read_system_snapshot
from provregress.provenance_v2.live_workloads import DEFAULT_INPUTS
from provregress.schema.common import AppId


def evaluate_local_examples(source_dir: Path = DEFAULT_INPUTS) -> list[dict[str, object]]:
    source = read_system_snapshot(source_dir)
    scenarios = (
        (AppId.A2, "prompt.query.replace.v1", "query", "entrega"),
        (AppId.A2, "retrieval.top_k.set.v1", "top_k", 4),
        (AppId.A2, "index.document.replace.v1", "refund.md", "Documento sin coincidencias léxicas."),
        (AppId.A3, "tool.catalog.field.set.v1", "item.stock", 0),
        (AppId.A3, "tool.catalog.field.set.v1", "item.price_units", 200),
    )
    return [run_local_smoke_m2(
        source_dir=source_dir,
        request=make_request(source, operator, target, value),
        app_id=app,
    ) for app, operator, target, value in scenarios]


def main() -> None:
    parser = argparse.ArgumentParser(description="R1.0-M2-P2, smoke local de tratamientos")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUTS,
                        help="Directorio local de entradas de ejemplo")
    args = parser.parse_args()
    result = evaluate_local_examples(args.input_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

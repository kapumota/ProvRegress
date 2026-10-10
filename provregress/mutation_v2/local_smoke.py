"""M2-P2: smoke de tratamientos en sandbox local, sin validez confirmatoria.

Nunca se ejecutan cargas ni tratamientos sobre rutas del usuario. Se crean dos
copias nuevas y se conserva intacta la fuente. No se infiere causalidad desde
la sola existencia de una arista ni desde los hashes de payload.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from provregress.mutation_v2.propagation_audit import (
    audit_propagation_m2, public_propagation_summary,
)
from provregress.mutation_v2.system_treatments import (
    SystemRequestM2, read_system_snapshot, materialize_snapshot, stage_system_treatment,
)
from provregress.provenance_v2.comparison_v21 import compare_graphs_v21
from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.live_workloads import comparison_policy, demo_study
from provregress.provenance_v2.projector import project_trace_v2
from provregress.schema.common import AppId


def run_local_smoke_m2(
    *, source_dir: Path, request: SystemRequestM2, app_id: AppId,
) -> dict[str, object]:
    """Ejecuta A2 o A3 sobre copias temporales, retorna solo conteos públicos."""
    if app_id not in {AppId.A2, AppId.A3}:
        raise ValueError("El smoke M2-P2 solo admite A2 o A3 locales.")
    operator_app = AppId.A3 if request.operator_id.startswith("tool.") else AppId.A2
    if app_id != operator_app:
        raise ValueError("Operador incompatible con la aplicación seleccionada.")
    source = read_system_snapshot(source_dir)
    changed, _private_receipt = stage_system_treatment(source, request)
    original_hash = source.snapshot_hash
    with TemporaryDirectory(prefix="provregress-m2-p2-") as work:
        root = Path(work)
        before_dir, before_catalog = materialize_snapshot(source, root / "baseline")
        after_dir, after_catalog = materialize_snapshot(changed, root / "candidate")
        study = demo_study()
        if app_id == AppId.A2:
            before = run_rag_dynamic(
                study=study, run_id="m2p2-a2-b", corpus=before_dir,
                query=source.query, top_k=source.top_k,
            )
            after = run_rag_dynamic(
                study=study, run_id="m2p2-a2-c", corpus=after_dir,
                query=changed.query, top_k=changed.top_k,
            )
            root_invocation = (
                f"retrieve:{request.target}"
                if request.operator_id == "index.document.replace.v1"
                else "query:refund"
            )
        else:
            before = run_tools_dynamic(
                study=study, run_id="m2p2-a3-b", catalog_path=before_catalog,
            )
            after = run_tools_dynamic(
                study=study, run_id="m2p2-a3-c", catalog_path=after_catalog,
            )
            root_invocation = "request:order"
        graph_b = project_trace_v2(list(before.events))
        graph_c = project_trace_v2(list(after.events))
        policy = comparison_policy(app_id)
        delta = compare_graphs_v21(graph_b, graph_c, policy)
        propagation = audit_propagation_m2(
            graph_b, graph_c, delta, policy=policy, root_invocation_key=root_invocation,
        )
        # Releer snapshots materializados con configuración externa explícita:
        before_again = read_system_snapshot(before_dir, query=source.query, top_k=source.top_k)
        after_again = read_system_snapshot(after_dir, query=changed.query, top_k=changed.top_k)
        if before_again.snapshot_hash != source.snapshot_hash or after_again.snapshot_hash != changed.snapshot_hash:
            raise ValueError("El sandbox no preserva la identidad de los snapshots.")
    if source.snapshot_hash != original_hash or read_system_snapshot(source_dir).snapshot_hash != original_hash:
        raise ValueError("El origen local fue modificado durante el smoke.")
    return {
        **public_propagation_summary(propagation),
        "app_id": app_id.value,
        "staged_snapshot_changed": True,
        "confirmatory_execution": False,
        "scientific_evidence": "not_admissible",
    }

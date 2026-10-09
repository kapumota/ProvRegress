"""Demostración local de un plan no ejecutable para A2 y A3."""

from __future__ import annotations

import json

from provregress.mutation_v2 import MutationRequestV2, plan_mutations_v2, public_plan_summary_v2, verify_plan_v2
from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.live_workloads import comparison_policy, demo_study
from provregress.provenance_v2.projector import project_trace_v2
from provregress.schema.common import AppId


def main() -> None:
    study = demo_study()
    summaries = []
    for app, execute in ((AppId.A2, run_rag_dynamic), (AppId.A3, run_tools_dynamic)):
        run = execute(study=study, run_id=f"r1-m1-design-{app.value}")
        graph = project_trace_v2(run.events)
        policy = comparison_policy(app)
        eligible_types = {rule.event_type for rule in policy.rules}
        target = next(node for node in graph.events if node.event_type in eligible_types)
        request = MutationRequestV2(
            request_id="candidate-1", target_key=list(target.key),
            operator_id="json.scalar.replace.v1", json_pointer="/result",
            parameters={"value": "ejemplo-controlado"},
        )
        plan = plan_mutations_v2(graph, policy, [request])
        verify_plan_v2(plan, graph, policy)
        summaries.append({"app_id": app.value, **public_plan_summary_v2(plan)})
    print(json.dumps({"phase": "r1.0-m1", "plans": summaries}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

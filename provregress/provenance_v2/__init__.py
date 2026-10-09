"""Contrato v2 experimental aislado. No sustituye implícitamente a P2/P3 v1."""

from .schema import (
    SAFE_INT, ComparisonPolicyV2, EdgeV2, EventNodeV2, EventV2, GraphV2, SignalRule,
    V2Error, canonical_v2, decimal_v2,
)
from .projector import project_trace_v2, validate_graph_v2
from .comparison import (
    DeltaV2, assert_pilot_alignment_v2, compare_graphs_v2,
    sequential_baseline_view_v2, topology_profile_v2,
)

__all__ = [
    "SAFE_INT", "ComparisonPolicyV2", "DeltaV2", "EdgeV2", "EventNodeV2", "EventV2",
    "GraphV2", "SignalRule", "V2Error", "assert_pilot_alignment_v2", "canonical_v2",
    "compare_graphs_v2", "decimal_v2", "project_trace_v2",
    "sequential_baseline_view_v2", "topology_profile_v2", "validate_graph_v2",
]

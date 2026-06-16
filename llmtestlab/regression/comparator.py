"""Estructuras iniciales para comparación entre versión base y versión candidata.

La comparación real se implementará en Fase 5.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RegressionComparisonPlan:
    """Plan declarativo para comparar dos ejecuciones."""

    baseline_name: str = "baseline"
    candidate_name: str = "candidate"
    purpose: str = "detectar regresiones, no solo evaluar respuestas aisladas"

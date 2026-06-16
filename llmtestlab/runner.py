"""Contrato inicial del runner.

La Fase 1 no ejecuta modelos. Este módulo existe para fijar la estructura que se implementará en Fase 2.
"""

from dataclasses import dataclass

from llmtestlab.evals import EvaluationSuite


@dataclass(frozen=True)
class RunnerPlan:
    """Plan declarativo de ejecución de una suite."""

    suite_name: str
    app_type: str
    provider_names: list[str]
    test_count: int


def build_runner_plan(suite: EvaluationSuite) -> RunnerPlan:
    """Construye un plan de ejecución sin llamar modelos."""
    return RunnerPlan(
        suite_name=suite.suite,
        app_type=suite.app_type.value,
        provider_names=sorted(suite.providers),
        test_count=len(suite.tests),
    )

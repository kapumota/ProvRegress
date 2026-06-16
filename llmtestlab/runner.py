"""Runner de Fase 2 para ejecutar suites evals.yaml."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from llmtestlab.assertions import evaluate_assertion
from llmtestlab.evals import load_evals_yaml
from llmtestlab.models import EvaluationSuite, RunResult, RunSummary, TestResult, TestStatus
from llmtestlab.providers import MockProvider, ProviderError


class RunnerError(RuntimeError):
    """Error de ejecución del runner."""


@dataclass(frozen=True)
class RunnerPlan:
    """Resumen de la suite que el runner ejecutará."""

    suite_name: str
    provider_names: list[str]
    test_count: int


def build_runner_plan(suite: EvaluationSuite) -> RunnerPlan:
    """Construye un plan de ejecución sin llamar providers."""
    return RunnerPlan(
        suite_name=suite.suite,
        provider_names=list(suite.providers),
        test_count=len(suite.tests),
    )


def run_suite_file(path: Path | str, provider_name: str = "candidate") -> RunResult:
    """Carga y ejecuta una suite desde archivo."""
    suite = load_evals_yaml(path)
    return run_suite(suite, provider_name=provider_name)


def run_suite(suite: EvaluationSuite, provider_name: str = "candidate") -> RunResult:
    """Ejecuta todos los tests de una suite."""
    if provider_name not in suite.providers:
        raise RunnerError(f"No existe el provider solicitado: {provider_name}")

    provider = MockProvider(suite.providers[provider_name])
    results: list[TestResult] = []

    for test in suite.tests:
        try:
            output = provider.generate(test)
        except ProviderError as exc:
            raise RunnerError(str(exc)) from exc

        assertion_results = [
            evaluate_assertion(assertion, test, output) for assertion in test.assertions
        ]
        passed = all(result.passed for result in assertion_results)
        status = TestStatus.PASSED if passed else TestStatus.FAILED
        results.append(
            TestResult(
                id=test.id,
                status=status,
                input=test.input,
                output=output,
                assertions=assertion_results,
            )
        )

    passed_count = sum(1 for result in results if result.status == TestStatus.PASSED)
    failed_count = len(results) - passed_count
    return RunResult(
        suite=suite.suite,
        app_type=suite.app_type,
        provider=provider_name,
        summary=RunSummary(total=len(results), passed=passed_count, failed=failed_count),
        tests=results,
    )


def write_run_result(result: RunResult, path: Path | str) -> None:
    """Guarda resultados en JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_run_result(path: Path | str) -> RunResult:
    """Carga resultados desde JSON."""
    result_path = Path(path)
    if not result_path.exists():
        raise RunnerError(f"No se encontró el archivo de resultados: {result_path}")
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunnerError(f"El archivo JSON no es válido: {exc}") from exc
    try:
        return RunResult.model_validate(data)
    except ValidationError as exc:
        raise RunnerError(f"El archivo de resultados no tiene el esquema esperado: {exc}") from exc

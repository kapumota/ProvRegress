"""Reportes de consola para Fase 2."""

from __future__ import annotations

from llmtestlab.models import RunResult, TestStatus


def render_run_summary(result: RunResult) -> str:
    """Renderiza resumen de ejecución."""
    lines = [f"Running suite: {result.suite}", ""]
    for test in result.tests:
        mark = "✓" if test.status == TestStatus.PASSED else "✗"
        lines.append(f"{mark} {test.id}")
    lines.extend([
        "",
        "Summary:",
        f"Passed: {result.summary.passed}",
        f"Failed: {result.summary.failed}",
    ])
    return "\n".join(lines) + "\n"


def render_console_report(result: RunResult) -> str:
    """Renderiza un reporte detallado desde results.json."""
    lines = [
        f"Suite: {result.suite}",
        f"Provider: {result.provider}",
        f"Total: {result.summary.total}",
        f"Passed: {result.summary.passed}",
        f"Failed: {result.summary.failed}",
        "",
        "Tests:",
    ]
    for test in result.tests:
        mark = "✓" if test.status == TestStatus.PASSED else "✗"
        lines.append(f"{mark} {test.id}")
        for assertion in test.assertions:
            assertion_mark = "✓" if assertion.passed else "✗"
            lines.append(f"  {assertion_mark} {assertion.type}: {assertion.message}")
    return "\n".join(lines) + "\n"

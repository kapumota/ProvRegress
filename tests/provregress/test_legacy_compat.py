"""Gate PG0: compatibilidad observable y aislamiento del núcleo legacy."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmtestlab import __version__ as legacy_version
from llmtestlab.cli import app
from llmtestlab.evals import load_evals_yaml
from llmtestlab.models import AppType, TestStatus
from llmtestlab.regression.comparator import compare_results
from llmtestlab.runner import load_run_result, run_suite_file
from provregress import __version__ as research_version
from provregress.schema.common import AppId


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_public_models_unchanged() -> None:
    """Conserva el vocabulario de aplicación y los estados públicos de LLMTestLab."""
    assert legacy_version == "0.3.0"
    assert research_version == "0.3.0"
    assert {member.value for member in AppType} == {
        "simple_chatbot", "json_extractor", "basic_rag",
    }
    assert {member.value for member in TestStatus} == {"passed", "failed"}
    assert AppType is not AppId
    assert {member.value for member in AppId} == {
        "a1_extraction", "a2_rag", "a3_tools",
    }


def test_legacy_runner_customer_support_still_passes() -> None:
    """La suite histórica conserva sus tres resultados deterministas."""
    result = run_suite_file(ROOT / "examples/customer_support/evals.yaml")
    assert result.suite == "customer-support-chatbot"
    assert result.app_type is AppType.SIMPLE_CHATBOT
    assert (result.summary.total, result.summary.passed, result.summary.failed) == (3, 3, 0)
    assert [item.id for item in result.tests] == [
        "refund-policy-001", "privacy-policy-002", "warranty-policy-003",
    ]
    assert all(item.status is TestStatus.PASSED for item in result.tests)


def test_legacy_runner_invoice_still_passes() -> None:
    """La extracción JSON mantiene sus dos resultados esperados."""
    result = run_suite_file(ROOT / "examples/invoice_extractor/evals.yaml")
    assert result.suite == "invoice-json-extractor"
    assert result.app_type is AppType.JSON_EXTRACTOR
    assert (result.summary.total, result.summary.passed, result.summary.failed) == (2, 2, 0)


def test_legacy_rag_yaml_still_loads() -> None:
    """El perfil RAG permanece disponible sin convertirse en AppId."""
    suite = load_evals_yaml(ROOT / "examples/rag_bot/evals.yaml")
    assert suite.app_type is AppType.BASIC_RAG
    assert len(suite.tests) == 1
    assert set(suite.providers) == {"baseline", "candidate"}


def test_legacy_mock_execution_is_deterministic() -> None:
    """La capa de compatibilidad no necesita un proveedor externo para las fixtures."""
    path = ROOT / "examples/customer_support/evals.yaml"
    first = run_suite_file(path)
    second = run_suite_file(path)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert all(item.output.raw.get("provider") == "mock" for item in first.tests)


def test_legacy_cli_validate_and_scope_unchanged() -> None:
    """Conserva entradas históricas de los comandos de validación."""
    runner = CliRunner()
    examples = ROOT / "examples"
    scope = runner.invoke(app, ["validate", str(examples / "phase0_scope.json")])
    assert scope.exit_code == 0, scope.output
    assert "El alcance cumple la Fase 0." in scope.output
    suite = runner.invoke(app, ["evals", "validate", str(examples / "customer_support/evals.yaml")])
    assert suite.exit_code == 0, suite.output
    assert "El archivo evals.yaml es válido para Fase 1." in suite.output


def test_legacy_cli_run_and_report_still_work(tmp_path: Path) -> None:
    """Valida el recorrido CLI con una ruta temporal y sin persistencia extra."""
    runner = CliRunner()
    output = tmp_path / "resultados.json"
    executed = runner.invoke(
        app,
        ["run", str(ROOT / "examples/customer_support/evals.yaml"), "--output", str(output)],
    )
    assert executed.exit_code == 0, executed.output
    assert output.is_file()
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["summary"] == {"total": 3, "passed": 3, "failed": 0}
    assert load_run_result(output).summary.passed == 3
    reported = runner.invoke(app, ["report", str(output)])
    assert reported.exit_code == 0, reported.output
    assert "Suite: customer-support-chatbot" in reported.output
    assert "Passed: 3" in reported.output


def test_legacy_comparator_remains_reserved() -> None:
    """No transforma la API legacy en un motor experimental prematuro."""
    with pytest.raises(NotImplementedError):
        compare_results()


def _imported_roots(path: Path) -> set[str]:
    """Obtiene dependencias explícitas sin hacer importaciones con efectos."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize(
    "package,forbidden",
    [
        ("llmtestlab", "provregress"),
        ("provregress", "llmtestlab"),
    ],
)
def test_package_imports_remain_isolated(package: str, forbidden: str) -> None:
    """Impide nuevas dependencias directas entre ambos paquetes."""
    paths = sorted((ROOT / package).rglob("*.py"))
    assert paths, f"No se encontraron archivos Python en {package}."
    offenders = [path.relative_to(ROOT).as_posix() for path in paths if forbidden in _imported_roots(path)]
    assert not offenders, f"Importaciones cruzadas no autorizadas: {offenders}"

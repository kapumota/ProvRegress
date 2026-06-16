from pathlib import Path

from typer.testing import CliRunner

from llmtestlab.cli import app
from llmtestlab.scope import build_default_scope, validate_scope

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_phase_zero_scope_still_valid() -> None:
    scope = build_default_scope()
    assert validate_scope(scope) == []


def test_phase_zero_validate_command_still_works() -> None:
    result = runner.invoke(app, ["validate", str(ROOT / "examples" / "phase0_scope.json")])
    assert result.exit_code == 0
    assert "El alcance cumple la Fase 0." in result.output


def test_phase_zero_summary_command_still_works() -> None:
    result = runner.invoke(app, ["summary", str(ROOT / "examples" / "phase0_scope.json")])
    assert result.exit_code == 0
    assert "Proyecto: LLMTestLab" in result.output
    assert "Chatbot simple: calidad de respuesta" in result.output

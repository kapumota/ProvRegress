from pathlib import Path

from typer.testing import CliRunner

from llmtestlab.cli import app

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_validate_command_passes() -> None:
    result = runner.invoke(app, ["validate", str(ROOT / "examples" / "customer_support" / "evals.yaml")])
    assert result.exit_code == 0
    assert "válido" in result.output


def test_validate_command_fails() -> None:
    result = runner.invoke(app, ["validate", str(ROOT / "examples" / "invalid" / "missing_candidate.yaml")])
    assert result.exit_code == 1
    assert "candidate" in result.output


def test_run_command_creates_results(tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    result = runner.invoke(
        app,
        ["run", str(ROOT / "examples" / "customer_support" / "evals.yaml"), "--output", str(output)],
    )
    assert result.exit_code == 0
    assert output.exists()
    assert "Passed: 3" in result.output
    assert "Failed: 0" in result.output


def test_report_command_prints_results(tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    run_result = runner.invoke(
        app,
        ["run", str(ROOT / "examples" / "invoice_extractor" / "evals.yaml"), "--output", str(output)],
    )
    assert run_result.exit_code == 0
    report_result = runner.invoke(app, ["report", str(output)])
    assert report_result.exit_code == 0
    assert "Suite: invoice-json-extractor" in report_result.output
    assert "Passed: 2" in report_result.output

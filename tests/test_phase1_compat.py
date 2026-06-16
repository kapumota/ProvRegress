from pathlib import Path

from typer.testing import CliRunner

from llmtestlab.cli import app
from llmtestlab.evals import build_example_suite, render_evals_spec_markdown
from llmtestlab.models import AppType
from llmtestlab.runner import build_runner_plan

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_phase_one_evals_group_still_validates_examples() -> None:
    result = runner.invoke(app, ["evals", "validate", str(ROOT / "examples" / "rag_bot" / "evals.yaml")])
    assert result.exit_code == 0
    assert "El archivo evals.yaml es válido para Fase 1." in result.output


def test_phase_one_example_builder_still_supports_three_profiles() -> None:
    suites = [build_example_suite(profile) for profile in ["customer_support", "invoice_extractor", "rag_bot"]]
    assert {suite.app_type for suite in suites} == {
        AppType.SIMPLE_CHATBOT,
        AppType.JSON_EXTRACTOR,
        AppType.BASIC_RAG,
    }


def test_phase_one_spec_uses_required_titles() -> None:
    spec = render_evals_spec_markdown()
    assert "### Especificación de evals.yaml" in spec
    assert "#### Campos principales" in spec


def test_phase_one_runner_plan_still_works() -> None:
    suite = build_example_suite("rag_bot")
    plan = build_runner_plan(suite)
    assert plan.suite_name == "customer-support-rag"
    assert plan.provider_names == ["baseline", "candidate"]
    assert plan.test_count == 1

from pathlib import Path

from llmtestlab.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_cli_evals_init_creates_yaml(tmp_path: Path):
    output = tmp_path / "evals.yaml"

    exit_code = main(["evals", "init", "--profile", "rag_bot", "--output", str(output)])

    assert exit_code == 0
    assert output.exists()


def test_cli_evals_init_refuses_to_overwrite_without_force(tmp_path: Path):
    output = tmp_path / "evals.yaml"
    first_exit_code = main(["evals", "init", "--profile", "customer_support", "--output", str(output)])
    second_exit_code = main(["evals", "init", "--profile", "customer_support", "--output", str(output)])

    assert first_exit_code == 0
    assert second_exit_code == 2


def test_cli_evals_validate_accepts_valid_example(capsys):
    exit_code = main(["evals", "validate", str(ROOT / "examples/rag_bot/evals.yaml")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "El archivo evals.yaml es válido para Fase 1." in captured.out


def test_cli_evals_validate_rejects_invalid_example(capsys):
    exit_code = main(["evals", "validate", str(ROOT / "examples/invalid/missing_candidate.yaml")])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "providers debe incluir candidate" in captured.out


def test_cli_evals_summary_outputs_suite_name(capsys):
    exit_code = main(["evals", "summary", str(ROOT / "examples/customer_support/evals.yaml")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Suite: customer-support-chatbot" in captured.out
    assert "refund-policy-001" in captured.out


def test_cli_evals_spec_can_write_markdown(tmp_path: Path):
    output = tmp_path / "EVALS_YAML_SPEC.md"

    exit_code = main(["evals", "spec", "--output", str(output)])

    assert exit_code == 0
    assert output.exists()
    assert "Especificación de evals.yaml" in output.read_text(encoding="utf-8")

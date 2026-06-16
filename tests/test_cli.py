from pathlib import Path

from llmtestlab.cli import main


def test_cli_init_creates_phase_zero_artifacts(tmp_path: Path):
    exit_code = main(["init", "--output", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "scope.json").exists()
    assert (tmp_path / "PHASE_0_SCOPE.md").exists()


def test_cli_init_refuses_to_overwrite_without_force(tmp_path: Path):
    first_exit_code = main(["init", "--output", str(tmp_path)])
    second_exit_code = main(["init", "--output", str(tmp_path)])

    assert first_exit_code == 0
    assert second_exit_code == 2


def test_cli_validate_accepts_default_scope(tmp_path: Path, capsys):
    main(["init", "--output", str(tmp_path)])

    exit_code = main(["validate", str(tmp_path / "scope.json")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "El alcance cumple la Fase 0." in captured.out


def test_cli_summary_text_contains_phase_zero_decisions(tmp_path: Path, capsys):
    main(["init", "--output", str(tmp_path)])

    exit_code = main(["summary", str(tmp_path / "scope.json")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Proyecto: LLMTestLab" in captured.out
    assert "Foco: unit testing + regression testing para apps LLM" in captured.out
    assert "Chatbot simple: calidad de respuesta" in captured.out
    assert "Extractor JSON: estructura y campos correctos" in captured.out
    assert "RAG básico: respuesta sustentada por documentos" in captured.out


def test_cli_summary_markdown_contains_table(tmp_path: Path, capsys):
    main(["init", "--output", str(tmp_path)])

    exit_code = main(["summary", str(tmp_path / "scope.json"), "--format", "markdown"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "| Tipo de app | Qué evalúas | Ejemplos de prueba |" in captured.out

from pathlib import Path
from dataclasses import replace

from llmtestlab.scope import (
    AppType,
    build_default_app_profiles,
    build_default_scope,
    get_supported_app_types,
    load_scope_json,
    render_scope_markdown,
    validate_scope,
    write_scope_json,
)


def test_build_default_scope_matches_phase_zero_decisions():
    scope = build_default_scope()

    errors = validate_scope(scope)

    assert errors == []
    assert scope.project_name == "LLMTestLab"
    assert scope.focus == "unit testing + regression testing para apps LLM"
    assert scope.differentiator == "detectar regresiones, no solo evaluar respuestas aisladas"


def test_build_default_scope_supports_exactly_three_initial_app_types():
    scope = build_default_scope()

    assert get_supported_app_types(scope) == {
        AppType.SIMPLE_CHATBOT,
        AppType.JSON_EXTRACTOR,
        AppType.BASIC_RAG,
    }
    assert len(scope.supported_app_profiles) == 3


def test_default_app_profiles_define_what_each_app_evaluates():
    profiles = build_default_app_profiles()
    targets = {profile.display_name: profile.evaluation_target for profile in profiles}

    assert targets["Chatbot simple"] == "calidad de respuesta"
    assert targets["Extractor JSON"] == "estructura y campos correctos"
    assert targets["RAG básico"] == "respuesta sustentada por documentos"


def test_scope_json_roundtrip(tmp_path: Path):
    scope = build_default_scope()
    output_path = tmp_path / "scope.json"

    write_scope_json(scope, output_path)
    loaded_scope = load_scope_json(output_path)

    assert loaded_scope == scope


def test_validate_scope_rejects_wrong_project_name():
    scope = build_default_scope()
    invalid_scope = replace(scope, project_name="OtroNombre")

    errors = validate_scope(invalid_scope)

    assert "El nombre del proyecto debe ser exactamente LLMTestLab." in errors


def test_validate_scope_rejects_missing_regression_focus():
    scope = build_default_scope()
    invalid_scope = replace(scope, focus="unit testing para apps LLM")

    errors = validate_scope(invalid_scope)

    assert "El foco debe incluir unit testing y regression testing para apps LLM." in errors


def test_validate_scope_rejects_extra_or_missing_app_types():
    scope = build_default_scope()
    invalid_scope = replace(scope, supported_app_profiles=scope.supported_app_profiles[:2])

    errors = validate_scope(invalid_scope)

    assert any("chatbot simple, extractor JSON y RAG básico" in error for error in errors)


def test_validate_scope_rejects_agents_with_tools_inside_first_version():
    scope = build_default_scope()
    invalid_scope = replace(scope, out_of_scope=["No ejecutar llamadas reales a modelos LLM."] * 5)

    errors = validate_scope(invalid_scope)

    assert "El alcance excluido debe dejar fuera agentes con tools." in errors


def test_render_scope_markdown_contains_required_phase_zero_table():
    scope = build_default_scope()

    markdown = render_scope_markdown(scope)

    assert "# LLMTestLab - Fase 0: Definición del alcance" in markdown
    assert "| Chatbot simple | calidad de respuesta |" in markdown
    assert "| Extractor JSON | estructura y campos correctos |" in markdown
    assert "| RAG básico | respuesta sustentada por documentos |" in markdown
    assert "## Fuera del alcance por ahora" in markdown

from pathlib import Path

import pytest

from llmtestlab.evals import (
    AppType,
    EvalsYamlError,
    Severity,
    build_example_suite,
    load_evals_yaml,
    parse_evaluation_suite,
    render_evals_spec_markdown,
    suite_to_dict,
    validate_evaluation_suite,
    write_evals_yaml,
)
from llmtestlab.runner import build_runner_plan


ROOT = Path(__file__).resolve().parents[1]


def test_customer_support_example_is_valid():
    suite = load_evals_yaml(ROOT / "examples/customer_support/evals.yaml")

    assert suite.suite == "customer-support-chatbot"
    assert suite.app_type == AppType.SIMPLE_CHATBOT
    assert set(suite.providers) == {"baseline", "candidate"}
    assert suite.tests[0].assertions[0].severity == Severity.CRITICAL


def test_invoice_extractor_example_is_valid():
    suite = load_evals_yaml(ROOT / "examples/invoice_extractor/evals.yaml")

    assertion_types = {assertion.type for assertion in suite.tests[0].assertions}

    assert suite.app_type == AppType.JSON_EXTRACTOR
    assert "json_valid" in assertion_types
    assert "json_schema" in assertion_types


def test_rag_bot_example_is_valid():
    suite = load_evals_yaml(ROOT / "examples/rag_bot/evals.yaml")

    assertion_types = {assertion.type for assertion in suite.tests[0].assertions}

    assert suite.app_type == AppType.BASIC_RAG
    assert "grounded_in_sources" in assertion_types
    assert suite.tests[0].required_sources == ["docs/refund_policy.md"]


@pytest.mark.parametrize(
    "relative_path, expected_message",
    [
        ("examples/invalid/missing_candidate.yaml", "providers debe incluir candidate"),
        ("examples/invalid/unknown_assertion.yaml", "Aserción desconocida"),
        ("examples/invalid/invalid_threshold.yaml", "threshold entre 0 y 1"),
        ("examples/invalid/duplicate_test_ids.yaml", "duplicado"),
        ("examples/invalid/json_extractor_without_json_assertion.yaml", "requiere json_valid o json_schema"),
    ],
)
def test_invalid_examples_are_rejected(relative_path: str, expected_message: str):
    with pytest.raises(EvalsYamlError) as exc_info:
        load_evals_yaml(ROOT / relative_path)

    assert expected_message in str(exc_info.value)


def test_build_example_suite_supports_three_profiles():
    profiles = ["customer_support", "invoice_extractor", "rag_bot"]
    suites = [build_example_suite(profile) for profile in profiles]

    assert {suite.app_type for suite in suites} == {
        AppType.SIMPLE_CHATBOT,
        AppType.JSON_EXTRACTOR,
        AppType.BASIC_RAG,
    }


def test_evals_yaml_roundtrip(tmp_path: Path):
    suite = build_example_suite("rag_bot")
    path = tmp_path / "evals.yaml"

    write_evals_yaml(suite, path)
    loaded = load_evals_yaml(path)

    assert loaded == suite


def test_suite_to_dict_uses_yaml_strings_for_enums():
    suite = build_example_suite("customer_support")
    data = suite_to_dict(suite)

    assert data["app_type"] == "simple_chatbot"
    assert data["tests"][0]["assertions"][0]["severity"] == "critical"


def test_semantic_similarity_requires_expected_answer():
    data = {
        "suite": "semantic-suite",
        "app_type": "simple_chatbot",
        "version": "0.1.0",
        "providers": {
            "baseline": {"model": "gpt-4.1-mini", "prompt": "prompts/v1.txt"},
            "candidate": {"model": "gpt-4.1-mini", "prompt": "prompts/v2.txt"},
        },
        "tests": [
            {
                "id": "semantic-001",
                "input": "Pregunta",
                "assertions": [{"type": "semantic_similarity", "threshold": 0.8}],
            }
        ],
    }

    suite = parse_evaluation_suite(data)
    errors = validate_evaluation_suite(suite)

    assert any("expected_answer" in error for error in errors)


def test_rag_assertion_requires_required_sources():
    data = {
        "suite": "rag-suite",
        "app_type": "basic_rag",
        "version": "0.1.0",
        "providers": {
            "baseline": {"model": "gpt-4.1-mini", "prompt": "prompts/v1.txt"},
            "candidate": {"model": "gpt-4.1-mini", "prompt": "prompts/v2.txt"},
        },
        "tests": [
            {
                "id": "rag-001",
                "input": "Pregunta",
                "assertions": [{"type": "grounded_in_sources", "threshold": 0.8}],
            }
        ],
    }

    suite = parse_evaluation_suite(data)
    errors = validate_evaluation_suite(suite)

    assert any("required_sources" in error for error in errors)


def test_render_evals_spec_contains_required_sections():
    spec = render_evals_spec_markdown()

    assert "### Especificación de evals.yaml - Fase 1" in spec
    assert "`simple_chatbot`" in spec
    assert "`json_extractor`" in spec
    assert "`basic_rag`" in spec
    assert "`contains_any`" in spec


def test_runner_plan_uses_phase_one_suite_contract():
    suite = build_example_suite("rag_bot")
    plan = build_runner_plan(suite)

    assert plan.suite_name == "customer-support-rag"
    assert plan.provider_names == ["baseline", "candidate"]
    assert plan.test_count == 1

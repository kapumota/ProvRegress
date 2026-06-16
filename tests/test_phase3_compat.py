from pathlib import Path

import pytest

from llmtestlab.evals import EvalsYamlError, load_evals_yaml
from llmtestlab.runner import run_suite_file

ROOT = Path(__file__).resolve().parents[1]


def test_phase_three_invoice_schema_path_is_resolved() -> None:
    suite = load_evals_yaml(ROOT / "examples" / "invoice_extractor" / "evals.yaml")
    assertion = suite.tests[0].assertions[1]
    assert assertion.type == "json_schema"
    assert isinstance(assertion.schema_, dict)
    assert assertion.schema_["required"] == ["vendor", "invoice_number", "total"]


def test_phase_three_invoice_suite_passes() -> None:
    result = run_suite_file(ROOT / "examples" / "invoice_extractor" / "evals.yaml")
    assert result.summary.total == 2
    assert result.summary.passed == 2
    assert result.summary.failed == 0


def test_phase_three_blocks_schema_path_traversal(tmp_path: Path) -> None:
    evals_path = tmp_path / "evals.yaml"
    evals_path.write_text(
        """
suite: unsafe-schema
app_type: json_extractor
version: 0.3.0
providers:
  baseline:
    model: mock
    prompt: prompts/v1.txt
    provider: mock
  candidate:
    model: mock
    prompt: prompts/v2.txt
    provider: mock
tests:
  - id: invoice-unsafe-001
    input: "Extrae JSON."
    metadata:
      mock_output: '{"value":1}'
    assertions:
      - type: json_valid
      - type: json_schema
        schema: ../schema.json
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(EvalsYamlError):
        load_evals_yaml(evals_path)

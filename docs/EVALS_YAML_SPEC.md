### Especificación de evals.yaml

#### Campos principales

`evals.yaml` define una suite de pruebas para aplicaciones LLM.

```yaml
suite: customer-support-rag
app_type: basic_rag
version: 0.2.0
providers:
  baseline:
    model: gpt-4.1-mini
    prompt: prompts/v1.txt
  candidate:
    model: gpt-4.1-mini
    prompt: prompts/v2.txt
tests:
  - id: refund-policy-001
    input: "Can I get a refund after 45 days?"
    assertions:
      - type: contains
        value: "30 days"
        severity: critical
```

#### Tipos de aplicación

`simple_chatbot`, `json_extractor` y `basic_rag`.

#### Severidades

`info`, `low`, `medium`, `high` y `critical`.

#### Assertions iniciales

`contains`, `contains_any`, `not_contains`, `regex`, `exact_match`, `json_valid`, `json_schema`, `grounded_in_sources`, `citation_required`, `citation_accuracy`, `context_recall`, `no_unsupported_claims`, `max_latency_ms` y `max_cost_usd`.

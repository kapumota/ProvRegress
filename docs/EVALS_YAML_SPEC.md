### Especificación de evals.yaml

#### Propósito

`evals.yaml` define una suite de pruebas para aplicaciones LLM.

La especificación nació en Fase 1 y se mantiene en Fase 3 para soportar el Assertion Engine determinístico.

#### Campos principales

```yaml
suite: customer-support-rag
app_type: basic_rag
version: 0.3.0
providers:
  baseline:
    model: gpt-4.1-mini
    prompt: prompts/v1.txt
    provider: mock
  candidate:
    model: gpt-4.1-mini
    prompt: prompts/v2.txt
    provider: mock
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

#### Assertions textuales

- `contains`
- `contains_any`
- `not_contains`
- `regex`
- `exact_match`

#### Assertions de estructura

- `json_valid`
- `json_schema`

`json_schema` puede recibir un schema inline o una ruta relativa al archivo `evals.yaml`.

Ejemplo:

```yaml
assertions:
  - type: json_valid
    severity: critical
  - type: json_schema
    severity: critical
    schema: schemas/invoice.schema.json
```

#### Assertions de ejecución

- `max_latency_ms`
- `max_cost_usd`

#### Assertions RAG básicas

- `grounded_in_sources`
- `citation_required`
- `citation_accuracy`
- `context_recall`
- `no_unsupported_claims`

#### Compatibilidad

Esta especificación conserva compatibilidad con:

- Fase 0 para alcance estricto
- Fase 1 para definición de suites
- Fase 2 para CLI básico

### Especificación de evals.yaml - Fase 1

#### Objetivo

`evals.yaml` define suites de unit testing y regression testing para aplicaciones LLM.

En Fase 1 el archivo solo se valida. La ejecución real de modelos y aserciones queda para fases posteriores.

#### Campos principales

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---:|---|
| `suite` | string | sí | Nombre corto de la suite. Usa minúsculas, números, guiones o guiones bajos. |
| `app_type` | string | sí | Tipo de app. Valores: `simple_chatbot`, `json_extractor`, `basic_rag`. |
| `version` | string | sí | Versión del contrato de la suite. |
| `providers` | object | sí | Debe incluir `baseline` y `candidate`. |
| `tests` | list | sí | Lista de casos de prueba. |
| `metadata` | object | no | Metadatos libres de la suite. |

#### Proveedores

Cada proveedor debe declarar al menos:

```yaml
providers:
  baseline:
    model: gpt-4.1-mini
    prompt: prompts/v1.txt
  candidate:
    model: gpt-4.1-mini
    prompt: prompts/v2.txt
```

Campos permitidos por proveedor:

- `model`
- `prompt`
- `provider`
- `temperature`
- `max_tokens`
- `base_url`

#### Casos de prueba

Cada caso de prueba debe tener:

- `id`
- `input`
- `assertions`

Campos opcionales:

- `expected_answer`
- `expected_facts`
- `required_sources`
- `metadata`

#### Severidades

Valores permitidos: `info`, `low`, `medium`, `high`, `critical`.

Si no se indica `severity`, se usa `high`.

#### Aserciones soportadas

`answer_correctness`, `citation_accuracy`, `citation_required`, `contains`, `contains_any`, `context_recall`, `exact_match`, `grounded_in_sources`, `json_schema`, `json_valid`, `max_cost_usd`, `max_latency_ms`, `no_unsupported_claims`, `not_contains`, `regex`, `relevance`, `semantic_similarity`.

#### Reglas por tipo de app

| app_type | Regla mínima |
|---|---|
| `simple_chatbot` | Cada test debe tener al menos una aserción textual. |
| `json_extractor` | Cada caso de prueba debe tener `json_valid` o `json_schema`. |
| `basic_rag` | Cada test debe tener una aserción RAG y `required_sources`. |

#### Ejemplo

```yaml
suite: customer-support-rag
app_type: basic_rag
version: 0.1.0

providers:
  baseline:
    model: gpt-4.1-mini
    prompt: prompts/v1.txt
  candidate:
    model: gpt-4.1-mini
    prompt: prompts/v2.txt

tests:
  - id: refund-policy-001
    input: "¿Puedo pedir un reembolso después de 45 días?"
    expected_facts:
      - "Los reembolsos se permiten dentro de 30 días."
      - "Las excepciones requieren aprobación de un gerente."
    required_sources:
      - docs/refund_policy.md
    assertions:
      - type: contains
        value: "30 días"
        severity: critical
      - type: grounded_in_sources
        threshold: 0.85
        severity: critical
```

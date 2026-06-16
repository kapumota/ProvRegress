### LLMTestLab - Fase 1

LLMTestLab será un framework estilo Pytest para aplicar unit testing y regression testing a aplicaciones basadas en LLMs.

Esta Fase 1 diseña e implementa el formato `evals.yaml`, que permite declarar suites, proveedores, casos de prueba, aserciones, severidades y umbrales.

#### Decisiones de alcance heredadas de Fase 0

| Decisión | Valor |
|---|---|
| Nombre | LLMTestLab |
| Foco | unit testing + regression testing para apps LLM |
| Diferenciador | detectar regresiones, no solo evaluar respuestas aisladas |

#### Tipos de aplicación soportados en esta primera versión

| Tipo de app | Qué evalúas |
|---|---|
| `simple_chatbot` | calidad de respuesta |
| `json_extractor` | estructura y campos correctos |
| `basic_rag` | respuesta sustentada por documentos |

Los agentes complejos y agentes con tools siguen fuera de esta versión.

#### Qué incluye esta fase

- Especificación del formato `evals.yaml`.
- Parser y validador del YAML.
- Validación de suites, proveedores, casos de prueba, aserciones, severidades y umbrales.
- Ejemplos válidos para chatbot simple, extractor JSON y RAG básico.
- Ejemplos inválidos para probar errores comunes.
- Estructura de carpetas para fases posteriores: runner, assertions, providers, reports y regression.
- CLI para inicializar, validar y resumir archivos `evals.yaml`.
- Tests unitarios del contrato de Fase 1.

#### Instalación en modo desarrollo

```bash
python -m venv .llmtest
source .llmtest/bin/activate
pip install -e ".[dev]"
```

En Windows PowerShell:

```powershell
python -m venv .llmtest
.llmtest\Scripts\Activate.ps1
pip install -e ".[dev]"
```

#### Uso rápido

Validar un archivo `evals.yaml`:

```bash
llmtestlab evals validate examples/customer_support/evals.yaml
```

Mostrar resumen:

```bash
llmtestlab evals summary examples/customer_support/evals.yaml
```

Crear un ejemplo nuevo:

```bash
llmtestlab evals init --profile customer_support --output evals.yaml
```

Crear la especificación Markdown:

```bash
llmtestlab evals spec --output EVALS_YAML_SPEC.md
```

#### Ejemplo mínimo

```yaml
suite: soporte-cliente-rag
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
    required_sources:
      - docs/refund_policy.md
    assertions:
      - type: contains
        value: "30 días"
        severity: critical

      - type: contains_any
        values: ["excepción", "aprobación de un gerente"]
        severity: high

      - type: not_contains
        value: "los reembolsos siempre están permitidos"
        severity: critical

      - type: max_latency_ms
        value: 5000

      - type: grounded_in_sources
        threshold: 0.85
        severity: critical
```

#### Ejecutar tests

```bash
pytest
```

#### Siguiente fase

La Fase 2 debe implementar el runner CLI para ejecutar suites reales y guardar resultados en JSON.

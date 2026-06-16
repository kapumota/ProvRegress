### LLMTestLab

LLMTestLab es un framework para unit testing y regression testing de aplicaciones basadas en LLM.

El objetivo del proyecto es permitir que prompts, chatbots, extractores JSON y sistemas RAG puedan probarse con una metodología similar a las pruebas tradicionales de software, pero adaptada a salidas no determinísticas.

#### Estado actual

Fase actual: Fase 3

Estado del proyecto:

- Fase 0 completada
- Fase 1 completada
- Fase 2 completada
- Fase 3 completada
- Fase 4 pendiente

#### Foco del proyecto

LLMTestLab se enfoca en:

- unit testing para aplicaciones LLM
- regression testing entre versiones baseline y candidate
- validación reproducible de casos de prueba
- ejecución por CLI
- resultados en JSON
- assertions determinísticas

#### Alcance inicial

La primera versión del proyecto soporta tres tipos de aplicaciones:

| Tipo de aplicación | Qué evalúa |
|---|---|
| Chatbot simple | calidad de respuesta |
| Extractor JSON | estructura y campos correctos |
| RAG básico | respuesta sustentada por documentos |

#### Fuera de alcance por ahora

Estas capacidades no forman parte de las primeras fases:

- agentes complejos
- agentes con tools
- evaluación multimodal
- dashboard web
- CI/CD
- llamadas reales a modelos externos
- LLM-as-judge

Estas capacidades pueden agregarse en fases posteriores.

### Fases implementadas

#### Fase 0

Define el alcance estricto del proyecto.

Incluye:

- nombre del proyecto
- foco del proyecto
- tipos de aplicación soportados
- límites explícitos del MVP
- validación de alcance mediante `phase0_scope.json`

Comandos principales:

```bash
python -m llmtestlab validate examples/phase0_scope.json
python -m llmtestlab summary examples/phase0_scope.json
```

#### Fase 1

Diseña el formato de pruebas `evals.yaml`.

Incluye:

- `suite`
- `version`
- `app_type`
- `providers`
- `baseline`
- `candidate`
- `tests`
- `assertions`
- `severity`
- `threshold`

Comando principal:

```bash
python -m llmtestlab evals validate examples/customer_support/evals.yaml
```

#### Fase 2

Agrega la primera interfaz de línea de comandos.

Comandos principales:

```bash
llmtestlab validate examples/customer_support/evals.yaml
llmtestlab run examples/customer_support/evals.yaml --output results.json
llmtestlab report results.json
```

También se puede ejecutar como módulo:

```bash
python -m llmtestlab validate examples/customer_support/evals.yaml
python -m llmtestlab run examples/customer_support/evals.yaml --output results.json
python -m llmtestlab report results.json
```

La Fase 2 permite:

- leer un archivo YAML
- validar la estructura del archivo
- ejecutar cada test usando provider mock
- guardar resultados en JSON
- mostrar resumen en consola

#### Fase 3

Agrega el Assertion Engine determinístico.

Assertions implementadas:

- `contains`
- `not_contains`
- `contains_any`
- `regex`
- `exact_match`
- `max_latency_ms`
- `json_valid`
- `json_schema`

También se mantiene soporte básico para assertions RAG declaradas en Fase 1:

- `grounded_in_sources`
- `citation_required`
- `citation_accuracy`
- `context_recall`
- `no_unsupported_claims`

Ejemplo de extractor JSON:

```yaml
tests:
  - id: invoice-001
    input: "Extrae JSON de esta factura: Proveedor ACME, número INV-001, total 125.50 USD."
    assertions:
      - type: json_valid
        severity: critical
      - type: json_schema
        severity: critical
        schema: schemas/invoice.schema.json
```

### Instalación local

#### Crear entorno

```bash
python3 -m venv .llmtest
source .llmtest/bin/activate
```

#### Instalar dependencias

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### Validación

Antes de hacer commit o push, ejecutar:

```bash
pytest -q
python -m llmtestlab validate examples/phase0_scope.json
python -m llmtestlab summary examples/phase0_scope.json
python -m llmtestlab evals validate examples/customer_support/evals.yaml
python -m llmtestlab validate examples/customer_support/evals.yaml
python -m llmtestlab run examples/customer_support/evals.yaml --output results.json
python -m llmtestlab report results.json
python -m llmtestlab run examples/invoice_extractor/evals.yaml --output invoice_results.json
python -m llmtestlab report invoice_results.json
```

Luego limpiar resultados locales:

```bash
rm -f results.json invoice_results.json baseline.json candidate.json comparison.json
```

### Estructura del proyecto

```text
LLMTestLab/
  docs/
  examples/
    customer_support/
    invoice_extractor/
      schemas/
    rag_bot/
    invalid/
    phase0_scope.json
  llmtestlab/
    assertions/
    providers/
    reports/
    regression/
    cli.py
    evals.py
    runner.py
    scope.py
  tests/
  .gitignore
  README.md
  ROADMAP.md
  pyproject.toml
```

### Convenciones del proyecto

#### Código

- nombres de funciones en inglés
- nombres de clases en inglés
- nombres de variables en inglés
- comentarios en español
- cadenas visibles en español

#### Documentación

- títulos con `###`
- subtítulos con `####`
- sin guiones largos
- sin líneas decorativas
- sin emoticones

### Flujo de trabajo recomendado

#### Antes de cada commit

```bash
source .llmtest/bin/activate

find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
rm -f results.json invoice_results.json baseline.json candidate.json comparison.json

pytest -q
git diff --check
git status --short --untracked-files=all
```

#### Commit

```bash
git add -A
git diff --cached --check
git commit -m "fase 3: implementa assertions deterministicas"
```

#### Push

```bash
git push
```

### Siguiente fase

#### Fase 4

La siguiente fase agrega providers de modelos.

Providers mínimos:

- mock provider
- OpenAI-compatible API
- Ollama o modelo local

### Licencia

Pendiente de definir.

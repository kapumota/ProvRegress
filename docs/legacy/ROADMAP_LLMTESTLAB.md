### Roadmap

#### Fase 0

Estado: completada

Define el alcance estricto del proyecto.

Incluye:

- nombre LLMTestLab
- foco en unit testing y regression testing
- soporte inicial para chatbot simple, extractor JSON y RAG básico
- límites explícitos del MVP

#### Fase 1

Estado: completada

Diseña el formato `evals.yaml`.

Incluye:

- suites
- providers
- baseline
- candidate
- tests
- assertions
- severidades
- umbrales
- ejemplos válidos e inválidos

#### Fase 2

Estado: completada

Agrega CLI básico.

Incluye:

- `llmtestlab validate evals.yaml`
- `llmtestlab run evals.yaml`
- `llmtestlab report results.json`
- lectura de YAML
- validación de estructura
- ejecución con provider mock
- resultados JSON
- resumen en consola

#### Fase 3

Estado: completada

Agrega el Assertion Engine determinístico.

Incluye:

- `contains`
- `not_contains`
- `contains_any`
- `regex`
- `exact_match`
- `max_latency_ms`
- `json_valid`
- `json_schema`

También conserva compatibilidad con:

- comandos de Fase 0
- comandos `evals` de Fase 1
- comandos `validate`, `run` y `report` de Fase 2

#### Fase 4

Estado: pendiente

Agregar providers de modelos.

Providers mínimos:

- mock provider
- OpenAI-compatible API
- Ollama o modelo local

#### Criterio de avance

Antes de pasar a la siguiente fase:

- ejecutar `pytest -q`
- ejecutar validaciones de Fase 0, Fase 1, Fase 2 y Fase 3
- limpiar archivos temporales
- revisar `git diff --check`
- commitear una fase completa

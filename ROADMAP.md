### Roadmap resumido de LLMTestLab

#### Fase 0: Definición del alcance

Completada.

Decisiones cerradas:

- Nombre: LLMTestLab.
- Foco: unit testing + regression testing para apps LLM.
- Diferenciador: detectar regresiones, no solo evaluar respuestas aisladas.
- Primera versión: chatbot simple, extractor JSON y RAG básico.
- Fuera por ahora: agentes complejos y agentes con tools.

#### Fase 1: Formato de pruebas

Completada en este paquete.

Objetivo: diseñar e implementar `evals.yaml` para declarar suites, proveedores, casos de prueba, aserciones, severidades y umbrales.

Entregables:

- Especificación del YAML.
- Parser y validador.
- Ejemplos válidos.
- Casos inválidos definidos.
- Estructura de carpetas para fases siguientes.
- CLI `llmtestlab evals ...`.
- Tests unitarios de Fase 1.

#### Fase 2: Runner CLI

Objetivo: ejecutar suites y guardar resultados en JSON.

#### Fase 3: Assertion Engine determinístico

Objetivo: ejecutar `contains`, `not_contains`, `contains_any`, `regex`, `json_valid`, `json_schema`, `max_latency_ms` y otras aserciones básicas.

#### Fase 4: Providers

Objetivo: conectar modelos OpenAI-compatible, Ollama/local y mock provider.

#### Fase 5: Pruebas de regresión

Objetivo: comparar baseline contra candidate.

#### Fase 6: LLM como juez

Objetivo: evaluar correctness, relevance, similarity y faithfulness.

#### Fase 7: Pruebas RAG con evidencia

Objetivo: validar fuentes, citas, groundedness y recuperación de contexto.

#### Fase 8: Detector de flakiness

Objetivo: repetir tests y clasificar estabilidad.

#### Fase 9: Dashboard

Objetivo: reporte HTML con diff, evidencia, costos y latencia.

#### Fase 10: CI/CD

Objetivo: integración con GitHub Actions y bloqueo de PRs con regresiones críticas.

#### Fase posterior: Agentes con tools

Objetivo futuro: evaluar tool calling, secuencias de herramientas, loops, costo y trazas de agentes.

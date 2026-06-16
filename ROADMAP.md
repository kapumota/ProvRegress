# Roadmap resumido de LLMTestLab

## Fase 0: Definición del alcance

Objetivo: definir exactamente qué se construirá antes de programar.

Decisiones cerradas:

- Nombre: LLMTestLab.
- Foco: unit testing + regression testing para apps LLM.
- Diferenciador: detectar regresiones, no solo evaluar respuestas aisladas.
- Primera versión: chatbot simple, extractor JSON y RAG básico.
- Fuera por ahora: agentes complejos y agentes con tools.

Entregables:

- CLI inicial.
- `scope.json`.
- `PHASE_0_SCOPE.md`.
- Validación estricta de alcance.
- Tests unitarios básicos.

## Fase 1: Formato de pruebas

Objetivo: diseñar `evals.yaml` para declarar providers, casos de prueba y assertions.

## Fase 2: Runner CLI

Objetivo: ejecutar suites y guardar resultados en JSON.

## Fase 3: Assertion Engine determinístico

Objetivo: soportar `contains`, `not_contains`, `regex`, `json_valid`, `json_schema` y métricas básicas.

## Fase 4: Providers

Objetivo: conectar modelos OpenAI-compatible, Ollama/local y mock provider.

## Fase 5: Regression Testing

Objetivo: comparar baseline contra candidate.

## Fase 6: LLM-as-Judge

Objetivo: evaluar correctness, relevance, similarity y faithfulness.

## Fase 7: RAG Evidence Testing

Objetivo: validar fuentes, citas, groundedness y recuperación de contexto.

## Fase 8: Flakiness Detector

Objetivo: repetir tests y clasificar estabilidad.

## Fase 9: Dashboard

Objetivo: reporte HTML con diff, evidencia, costos y latencia.

## Fase 10: CI/CD

Objetivo: integración con GitHub Actions y bloqueo de PRs con regresiones críticas.

## Fase posterior: Agentes con tools

Objetivo futuro: evaluar tool calling, secuencias de herramientas, loops, costo y trazas de agentes.

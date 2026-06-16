# LLMTestLab - Fase 0

LLMTestLab será un framework estilo Pytest para aplicar **unit testing + regression testing** a aplicaciones basadas en LLMs.

Esta **Fase 0** no ejecuta modelos todavía. Su objetivo es definir exactamente qué se construirá antes de programar el motor de pruebas.

## Decisiones de alcance

| Decisión | Valor |
|---|---|
| Nombre | LLMTestLab |
| Foco | unit testing + regression testing para apps LLM |
| Diferenciador | detectar regresiones, no solo evaluar respuestas aisladas |

## Tipos de aplicación de la primera versión

| Tipo de app | Qué evalúas |
|---|---|
| Chatbot simple | calidad de respuesta |
| Extractor JSON | estructura y campos correctos |
| RAG básico | respuesta sustentada por documentos |

Los agentes complejos y agentes con tools quedan fuera de la primera versión. Pueden entrar en una fase posterior.

## Qué incluye esta fase

- Modelo de alcance del proyecto.
- Perfiles explícitos para chatbot simple, extractor JSON y RAG básico.
- CLI inicial.
- Archivo `scope.json` generado automáticamente.
- Documento `PHASE_0_SCOPE.md` generado automáticamente.
- Validaciones estrictas del alcance.
- Tests unitarios del núcleo inicial.

## Reglas de estilo usadas

- Firmas de funciones, clases, variables y módulos en inglés.
- Comentarios, docstrings, mensajes y cadenas visibles en español.

## Instalación en modo desarrollo

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

En Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Uso

Crear los artefactos de Fase 0:

```bash
llmtestlab init --output .
```

Validar un archivo de alcance:

```bash
llmtestlab validate scope.json
```

Mostrar resumen en consola:

```bash
llmtestlab summary scope.json
```

Generar resumen Markdown:

```bash
llmtestlab summary scope.json --format markdown
```

## Ejecutar tests

```bash
pytest
```

## Siguiente fase

La Fase 1 debe implementar el formato `evals.yaml` para declarar suites, providers, casos de prueba, assertions, severidades y umbrales.

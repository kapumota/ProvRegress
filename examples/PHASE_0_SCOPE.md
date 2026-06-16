### LLMTestLab - Fase 0: Definición del alcance

#### Nombre

LLMTestLab

#### Foco

unit testing + regression testing para apps LLM

#### Diferenciador

detectar regresiones, no solo evaluar respuestas aisladas

#### Versión

0.0.1

#### Resumen del producto

Framework estilo Pytest para definir pruebas unitarias y pruebas de regresión en aplicaciones basadas en LLMs, empezando con chatbots simples, extractores JSON y sistemas RAG básicos.

#### Meta principal

Definir exactamente qué se construirá antes de programar el motor de pruebas: alcance, límites, tipos de aplicación soportados y criterios de éxito.

#### Tipos de aplicación soportados en la primera versión

| Tipo de app | Qué evalúas | Ejemplos de prueba |
|---|---|---|
| Chatbot simple | calidad de respuesta | La respuesta incluye hechos obligatorios.<br>La respuesta evita afirmaciones explícitamente prohibidas.<br>La respuesta cumple un formato mínimo definido por la suite. |
| Extractor JSON | estructura y campos correctos | La salida es JSON válido.<br>La salida cumple un JSON Schema.<br>Los campos obligatorios existen y tienen el tipo esperado. |
| RAG básico | respuesta sustentada por documentos | La respuesta está basada en los documentos recuperados.<br>La respuesta cita la fuente esperada cuando sea obligatorio.<br>La respuesta no agrega afirmaciones sin soporte documental. |

#### Dentro del alcance

- Definir el nombre oficial del proyecto: LLMTestLab.
- Definir el foco: unit testing + regression testing para apps LLM.
- Definir el diferenciador: detectar regresiones, no solo evaluar respuestas aisladas.
- Limitar la primera versión a chatbot simple, extractor JSON y RAG básico.
- Crear una CLI inicial para generar, validar y resumir el alcance.
- Generar un archivo scope.json versionable.
- Generar un documento PHASE_0_SCOPE.md legible para revisión humana.
- Validar que el alcance tenga tipos soportados, límites y criterios de éxito.

#### Fuera del alcance por ahora

- No ejecutar llamadas reales a modelos LLM en Fase 0.
- No implementar aserciones ni evaluadores en Fase 0.
- No comparar versión base contra versión candidata en Fase 0.
- No construir dashboard web en Fase 0.
- No integrar CI/CD en Fase 0.
- No soportar agentes complejos ni agentes con tools en la primera versión.
- No soportar evaluación multimodal en la primera versión.

#### Criterios de éxito

- El repositorio puede instalarse en modo desarrollo.
- El comando init genera scope.json y PHASE_0_SCOPE.md.
- El comando validate detecta alcances incompletos o fuera del alcance inicial.
- El alcance incluye exactamente tres tipos de app: chatbot simple, extractor JSON y RAG básico.
- Cada tipo de app indica claramente qué se evaluará.
- El alcance excluye explícitamente agentes con tools para una fase posterior.
- Los tests unitarios de Fase 0 pasan localmente.

#### Riesgos técnicos iniciales

- Intentar construir agentes con tools antes de tener un runner estable.
- Confundir evaluación aislada con regression testing versionado.
- Agregar demasiados tipos de aplicación antes de validar el MVP.
- Construir dashboard o CI/CD antes de validar el contrato de pruebas.

#### Siguiente fase

Fase 1: diseñar el formato evals.yaml para declarar suites, proveedores, casos de prueba, aserciones, severidades y umbrales.

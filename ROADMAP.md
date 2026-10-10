### Roadmap de ProvRegress

#### R0.0, baseline reproducible

Estado: cerrado.

Resultado:

- repositorio privado verificado
- HEAD histórico registrado
- entorno virtual aislado
- 40 tests legacy reproducidos

#### R0.1, identidad del proyecto

Estado: en preparación.

Objetivo:

- consolidar el nombre ProvRegress
- preservar el package `llmtestlab` como compatibilidad legacy
- introducir el package `provregress`
- preparar el repositorio para visibilidad pública

#### R0.7, P0 y P1

Objetivo:

- schemas estrictos
- hashing determinista
- manifests
- pilot firewall
- RunContext
- EventEnvelope
- ArtifactStore
- JSONL append-only
- EventSink
- RunManifest

No incluye experimentos.

#### R0.8, P2 y P3

Objetivo:

- especificación de `tau -> G`
- identidad canónica de nodos
- construcción de aristas
- serialización determinista
- validación de DAG
- alignment baseline y candidate
- `DeltaG`
- golden fixtures

#### R0.8-I, referencia Python

Objetivo:

- projector
- canonicalization
- alignment
- graph diff
- fixtures verificables

Python será la implementación semántica de referencia.

#### R0.9, Rust core

Objetivo:

- event ingestion
- hashing
- artifact verification
- graph projection
- graph diff
- procesamiento paralelo

Rust debe ser conforme con los golden fixtures de Python.

#### R0.10, contrato Python v2 de procedencia diferencial

Estado: auditoría técnica cerrada con condiciones en F4. Baseline de ingeniería
aceptado, sin congelación científica ni superioridad demostrada frente a secuencia
fuerte de información equivalente. R0.8, R0.8-I y R0.9 permanecen congelados
como referencia legacy v1; Rust v2 no es requisito hasta justificar su necesidad.

#### R1.0, mutation harness

Estado: M1 integrado, diseño y planificación determinista sin ejecución.

- M2-P1: mapa declarado JSON Pointer → señal, preflight sobre payloads originales,
  medición separada de riesgo de mutaciones silenciosas y semántica de comparación
  v2.1 para `signal_missing`, sin cambiar oráculos R0.10.
- M2-P2: operadores sobre prompt, índice/recuperador y herramienta, con controles
  sin efecto y evidencia de propagación a eventos descendientes.
- Las mutaciones experimentales siguen bloqueadas hasta superar las condiciones
  científicas de R0.10-F4 y la congelación previa del protocolo.

#### R1.1 a R1.3, aplicaciones experimentales

A1:

- structured extraction

A2:

- evidence-grounded RAG

A3:

- tool-using workflow

#### R1.4, piloto

Objetivo:

- no-change variance
- severity calibration
- leakage audit
- power analysis
- evaluator and system variance identifiability

#### R1.5, preregistro final

Antes de cualquier experimento confirmatorio se congelarán:

- hipótesis
- casos
- mutaciones
- severidades
- sample size
- repetitions
- baselines
- endpoints
- statistical models
- stopping rules

#### R2.0, confirmatory study

Solo después del preregistro final.

#### Líneas posteriores

Paper 2:

- learned paired graph representations

Paper 3:

- mutation-grounded causal attribution

Paper 4:

- temporal regression graphs

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

#### R1.0, mutation harness

Objetivo:

- mutaciones controladas
- target conocido
- manifests de mutación
- controles identity y evaluator

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

### ProvRegress

**Version-Differential Provenance and Regression Attribution for Evolving AI Systems**

ProvRegress es un proyecto de investigación y software orientado a estudiar regresiones conductuales en sistemas de IA que evolucionan entre versiones.

El proyecto parte de una pregunta central:

> ¿Puede la procedencia diferencial entre versiones mejorar la detección y localización de regresiones frente a representaciones basadas únicamente en salida, métricas agregadas o trazas secuenciales?

### Estado

El repositorio se encuentra en fase preexperimental.

No contiene todavía resultados confirmatorios ni claims científicos validados.

El núcleo histórico de `LLMTestLab` se conserva temporalmente como capa de compatibilidad. La nueva infraestructura se desarrollará en el package `provregress`.

### Línea científica

La hoja de ruta estudia progresivamente:

1. version-differential provenance
2. graph-based regression localization
3. mutation-grounded causal attribution
4. evaluator-vs-system uncertainty separation
5. temporal regression graphs

Estas líneas no se presentan como contribuciones ya demostradas. Son hipótesis y etapas de investigación que deberán superar gates experimentales explícitos.

### Objeto formal

Una versión de un sistema se modela como:

```text
S_v = (C_v, theta_v, Pi_v)
```

Una ejecución:

```text
e = Exec(S_v, x, xi)
```

produce una traza:

```text
tau(e)
```

que posteriormente se proyectará a una representación de procedencia:

```text
G(e)
```

Para una versión baseline y una versión candidate:

```text
G_b = G(e_b)
G_c = G(e_c)
```

el objeto de estudio principal será el diferencial:

```text
DeltaG = G_c minus G_b
```

### Alcance actual

El desarrollo inmediato se limita a infraestructura reproducible:

- schemas estrictos
- manifests
- hashing determinista
- separación pilot y confirmatory
- event logs append-only
- almacenamiento content-addressed
- provenance determinista en fases posteriores

Todavía no forman parte del núcleo actual:

- GNN
- temporal graph learning
- causal SCM confirmatorio
- Rust como contribución científica
- experimentos confirmatorios

### Arquitectura

Actualmente conviven dos packages:

```text
provregress/
    Nuevo núcleo de investigación.

llmtestlab/
    Implementación legacy preservada por compatibilidad.
```

El package `llmtestlab` no representa la dirección científica futura del proyecto.

### Reproducibilidad

La línea base histórica verificada antes de la migración fue:

```text
LLMTestLab 0.3.0
commit e440bf402ed7b5410f97a6f01927e04f7ab198ce
Python 3.11.15
40 tests passed
```

El desarrollo nuevo debe preservar esos tests hasta que exista una migración explícita y revisada.

### Roadmap

Consulta [ROADMAP.md](ROADMAP.md).

### Alcance científico

Consulta [docs/SCIENTIFIC_SCOPE.md](docs/SCIENTIFIC_SCOPE.md).

### Reproducibilidad

Consulta [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).

### Contribuciones

Consulta [CONTRIBUTING.md](CONTRIBUTING.md).

### Seguridad

Consulta [SECURITY.md](SECURITY.md).

### Licencia

ProvRegress se distribuye bajo Apache License 2.0.

Consulta [LICENSE](LICENSE) para conocer los términos completos.

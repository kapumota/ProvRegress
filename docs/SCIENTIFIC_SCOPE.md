### Alcance científico

ProvRegress estudia regresiones conductuales en sistemas de IA evolutivos.

#### Núcleo conceptual

La línea de investigación se organiza alrededor de cinco ejes:

1. version-differential provenance
2. graph-based regression localization
3. mutation-grounded causal attribution
4. evaluator-vs-system uncertainty separation
5. temporal regression graphs

#### Claims que no se realizan actualmente

Este repositorio no afirma todavía que:

- los grafos superen a las trazas
- la procedencia diferencial mejore la localización
- una GNN sea necesaria
- exista atribución causal validada
- sea posible separar de forma estable todas las fuentes de varianza
- los grafos temporales permitan predecir regresiones futuras

Estas son hipótesis que deberán evaluarse experimentalmente.

#### Líneas saturadas que no constituyen la contribución principal

ProvRegress no se presenta como:

- framework genérico de evaluación de LLM
- sistema genérico LLM-as-a-Judge
- benchmark de GraphRAG
- framework de RAG faithfulness
- mutation testing genérico
- herramienta genérica de trace debugging

#### Paper 1

La hipótesis central provisional es:

```text
Paired execution-provenance graph differentials improve root-cause localization
of controlled behavioral regressions over output-only, aggregate-metric and
sequential-trace baselines.
```

La hipótesis debe poder ser falsificada.

Un resultado negativo riguroso será aceptado si los gates experimentales se cumplen.

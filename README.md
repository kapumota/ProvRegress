### Fase 2 - CLI básico

LLMTestLab permite validar, ejecutar y reportar suites declaradas en `evals.yaml`.

#### Instalación

```bash
pip install -e ".[dev]"
```

#### Comandos mínimos

```bash
llmtestlab validate examples/customer_support/evals.yaml
llmtestlab run examples/customer_support/evals.yaml
llmtestlab report results.json
```

#### Alcance

Esta fase lee YAML, valida la estructura, ejecuta tests con salidas simuladas, guarda resultados JSON y muestra resumen en consola. No llama modelos externos todavía.

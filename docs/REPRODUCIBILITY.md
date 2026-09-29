### Reproducibilidad

#### Entorno Python

El desarrollo utiliza un entorno virtual local:

```bash
python3.11 -m venv --prompt provregress .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

#### Tests

Ejecutar:

```bash
python -m pytest -q
```

La línea base previa a la migración de identidad fue:

```text
40 passed
```

#### Git

Antes de cada commit:

```bash
python -m pytest -q
git diff --check
git status --short
git diff --stat
```

#### Principio de reproducibilidad

Los futuros resultados científicos deberán registrar como mínimo:

- commit Git
- estado dirty
- versión de Python
- dependency lock
- dataset hash
- system manifest hash
- environment manifest hash
- trace hash
- configuración de evaluadores

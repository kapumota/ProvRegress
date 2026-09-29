### Contribuir a ProvRegress

#### Estilo

Las firmas de funciones, clases, variables, módulos y campos se escriben en inglés.

Los comentarios, docstrings explicativos y cadenas visibles al usuario se escriben en español.

Los identificadores machine-readable permanecen en inglés.

Ejemplo:

```python
def hash_case_ids(case_ids):
    """Calcula el hash canónico de los identificadores de casos."""
```

#### Documentación

Los títulos comienzan con `###`.

Los subtítulos comienzan con `####`.

Cuando sea necesario se utiliza `#####`.

En la prosa se prefieren comas y puntos. Se evita el punto y coma cuando no es necesario.

Se evitan guiones largos, comillas tipográficas, emojis y símbolos decorativos.

#### Flujo Git

Los cambios se realizan mediante:

1. rama
2. parche pequeño
3. tests
4. revisión
5. commit

No se mezclan fases científicas distintas en un mismo commit.

#### Gate mínimo

Antes de cada commit:

```bash
python -m pytest -q
git diff --check
git status --short
git diff --stat
```

No se hace push con tests fallidos.

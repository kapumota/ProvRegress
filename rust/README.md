### R0.9, referencia Rust de contratos P2/P3

#### R1: workspace, schemas y JSON canónico

El paquete `rust/provregress-reference` conserva los tipos de
`provenance-graph-v1` y `provenance-delta-v1` congelados en R0.8-F3.
**No** calcula grafos, correspondencias ni diferencias: esos gates serán R2/R3.
No modifica R0.7, la referencia Python ni los fixtures normativos.

Las estructuras Rust utilizan `serde` con campos cerrados y `validate()` para
identidades SHA-256, hashes canónicos, grupos tipados y órdenes. El método de
serialización recorre recursivamente objetos JSON, ordena claves por orden
lexicográfico y emite UTF-8 compacto. Conserva los mismos bytes y hashes para
los golden fixtures actuales, que no contienen valores de coma flotante.

**Límite explícito:** los formatos de exponentes y algunas representaciones
numéricas de punto flotante entre Python y `serde_json` aún no han sido
cubiertos por golden fixtures. R0.9-R4 deberá introducir verificaciones cruzadas
adicionales sin modificar silenciosamente los oráculos F2/F3. No se declara
conformidad general para todos los posibles valores `JsonValue` en este gate.

#### Verificación

```bash
cargo generate-lockfile
cargo fmt --all --check
cargo test --workspace --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
python -m pytest -q
```

El `Cargo.lock` raíz se genera en el entorno Rust del autor y debe incluirse
en el mismo commit R1 para que los jobs CI reproducibles puedan usar `--locked`.
No se debe editar manualmente ni simular su contenido sin Cargo.

La implementación Rust no debe importar información de tratamientos
experimentales ni utilizar identidades de ejecución como claves de alineamiento.

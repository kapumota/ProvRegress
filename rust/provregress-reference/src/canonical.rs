//! Codificación JSON compacta y ordenada para los contratos golden de Python.

use serde_json::Value;
use sha2::{Digest, Sha256};

/// Serializa JSON con claves ordenadas por orden lexicográfico y sin espacios.
///
/// La equivalencia con Python para valores de coma flotante extremos todavía
/// requiere tests cruzados adicionales antes de declarar R0.9 completo.
pub fn canonical_json_bytes(value: &Value) -> Result<Vec<u8>, serde_json::Error> {
    fn append(value: &Value, bytes: &mut Vec<u8>) -> Result<(), serde_json::Error> {
        match value {
            Value::Object(entries) => {
                bytes.push(b'{');
                let mut keys: Vec<_> = entries.keys().collect();
                keys.sort_unstable();
                for (index, key) in keys.iter().enumerate() {
                    if index > 0 {
                        bytes.push(b',');
                    }
                    bytes.extend(serde_json::to_vec(key)?);
                    bytes.push(b':');
                    append(&entries[*key], bytes)?;
                }
                bytes.push(b'}');
            }
            Value::Array(items) => {
                bytes.push(b'[');
                for (index, item) in items.iter().enumerate() {
                    if index > 0 {
                        bytes.push(b',');
                    }
                    append(item, bytes)?;
                }
                bytes.push(b']');
            }
            primitive => bytes.extend(serde_json::to_vec(primitive)?),
        }
        Ok(())
    }
    let mut bytes = Vec::new();
    append(value, &mut bytes)?;
    Ok(bytes)
}

/// SHA-256 hexadecimal minúsculo de los bytes exactos, sin prefijo.
pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Calcula H(x) para JSON canónico de los contratos R0.8-F3.
pub fn canonical_hash(value: &Value) -> Result<String, serde_json::Error> {
    Ok(sha256_hex(&canonical_json_bytes(value)?))
}

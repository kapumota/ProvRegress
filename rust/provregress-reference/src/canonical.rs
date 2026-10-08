//! Codificación JSON compacta y ordenada para los contratos golden de Python.

use serde_json::Value;
use sha2::{Digest, Sha256};

/// Representación corta compatible con json.dumps() para floats finitos.
/// Los enteros conservan su serialización original; no hay redondeos extra.
fn python_float_text(number: &serde_json::Number) -> String {
    let raw = number.to_string();
    let (sign, positive) = if let Some(value) = raw.strip_prefix('-') {
        ("-", value)
    } else {
        ("", raw.as_str())
    };
    let (mantissa, exponent) = positive
        .split_once(['e', 'E'])
        .map(|(value, power)| (value, power.parse::<i32>().unwrap_or(0)))
        .unwrap_or((positive, 0));
    let dot = mantissa.find('.').unwrap_or(mantissa.len());
    let raw_digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    let leading = raw_digits
        .bytes()
        .take_while(|digit| *digit == b'0')
        .count();
    if leading == raw_digits.len() {
        return format!("{sign}0.0");
    }
    let significant = raw_digits[leading..].trim_end_matches('0');
    let magnitude = exponent + dot as i32 - leading as i32 - 1;
    if !(-4..16).contains(&magnitude) {
        let (first, rest) = significant.split_at(1);
        let normalized = if rest.is_empty() {
            first.to_owned()
        } else {
            format!("{first}.{rest}")
        };
        return format!("{sign}{normalized}e{magnitude:+03}");
    }
    let position = magnitude + 1;
    let fixed = if position <= 0 {
        format!("0.{}{significant}", "0".repeat((-position) as usize))
    } else if position as usize >= significant.len() {
        format!(
            "{}{}.0",
            significant,
            "0".repeat(position as usize - significant.len())
        )
    } else {
        let index = position as usize;
        format!("{}.{}", &significant[..index], &significant[index..])
    };
    format!("{sign}{fixed}")
}

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
            Value::Number(number) if number.is_f64() => {
                // json.dumps() de Python usa notación científica fuera de [-4, 15].
                bytes.extend_from_slice(python_float_text(number).as_bytes());
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

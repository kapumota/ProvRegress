//! Casos numéricos adicionales, sin modificar los oráculos F2/F3.

use provregress_reference::canonical_json_bytes;
use serde_json::json;

#[test]
fn python_float_thresholds_and_signed_zero() {
    let cases = [
        (json!(1.0), "1.0"),
        (json!(-0.0), "-0.0"),
        (json!(0.0001), "0.0001"),
        (json!(0.00001), "1e-05"),
        (json!(0.000001), "1e-06"),
        (json!(0.0000001), "1e-07"),
        (json!(1e16), "1e+16"),
        (json!(1e21), "1e+21"),
        (json!(-1e-7), "-1e-07"),
        (json!(1.2345678901234567), "1.2345678901234567"),
    ];
    for (value, expected) in cases {
        assert_eq!(canonical_json_bytes(&value).unwrap(), expected.as_bytes());
    }
}

#[test]
fn integer_and_unicode_representation_stays_intact() {
    let value = json!({"á": "niño", "a": [10, true, null], "z": 0.5});
    assert_eq!(
        canonical_json_bytes(&value).unwrap(),
        "{\"a\":[10,true,null],\"z\":0.5,\"á\":\"niño\"}".as_bytes()
    );
}

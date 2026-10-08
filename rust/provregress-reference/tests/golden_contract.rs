//! Gate R0.9-R1: schemas y hashes Rust comparados con oráculos F2/F3.

use std::collections::BTreeSet;

use provregress_reference::{
    canonical_hash, canonical_json_bytes, sha256_hex, DeltaG, ProvenanceGraph,
};
use serde_json::{json, Value};

const EXPECTED: &str = include_str!("../../../tests/fixtures/provenance/r0_8/expected.json");
const INPUTS: &str = include_str!("../../../tests/fixtures/provenance/r0_8/inputs.json");

fn golden() -> Value {
    serde_json::from_str(EXPECTED).expect("Oráculo golden JSON")
}

fn with_graphs() -> Vec<Value> {
    golden()["cases"]
        .as_array()
        .expect("Casos golden")
        .iter()
        .filter(|item| item.get("graphs").is_some())
        .cloned()
        .collect()
}

fn with_delta() -> Vec<Value> {
    golden()["cases"]
        .as_array()
        .expect("Casos golden")
        .iter()
        .filter(|item| item.get("delta").is_some_and(|value| !value.is_null()))
        .cloned()
        .collect()
}

#[test]
fn golden_bytes_are_frozen_and_unchanged() {
    assert_eq!(
        sha256_hex(INPUTS.as_bytes()),
        "9d2be2dd2d894e7c4c7508cad0bb6160147dc01d82e3d1090e7903a69d9eb242"
    );
    assert_eq!(
        sha256_hex(EXPECTED.as_bytes()),
        "47fd5e198f25704ee0fbc6363ea3621754397aad9ca72507be4a68752fa4be50"
    );
    let inputs: Value = serde_json::from_str(INPUTS).unwrap();
    let outputs = golden();
    assert_eq!(
        canonical_json_bytes(&inputs).unwrap(),
        INPUTS.trim_end_matches('\n').as_bytes()
    );
    assert_eq!(
        canonical_json_bytes(&outputs).unwrap(),
        EXPECTED.trim_end_matches('\n').as_bytes()
    );
}

#[test]
fn golden_graphs_parse_validate_and_roundtrip_without_changes() {
    let mut count = 0;
    for case in with_graphs() {
        for (role, payload) in case["graphs"].as_object().unwrap() {
            let graph: ProvenanceGraph = serde_json::from_value(payload.clone())
                .unwrap_or_else(|error| panic!("{} {role}: {error}", case["id"]));
            graph
                .validate()
                .unwrap_or_else(|error| panic!("{} {role}: {error}", case["id"]));
            let encoded = serde_json::to_value(&graph).unwrap();
            assert_eq!(
                encoded, *payload,
                "{} {role}: serialización no conforme",
                case["id"]
            );
            assert_eq!(
                canonical_json_bytes(&encoded).unwrap(),
                canonical_json_bytes(payload).unwrap()
            );
            count += 1;
        }
    }
    assert_eq!(count, 12);
}

#[test]
fn golden_deltas_parse_validate_and_roundtrip_without_changes() {
    let mut count = 0;
    for case in with_delta() {
        let payload = &case["delta"];
        let delta: DeltaG = serde_json::from_value(payload.clone())
            .unwrap_or_else(|error| panic!("{}: {error}", case["id"]));
        delta
            .validate()
            .unwrap_or_else(|error| panic!("{}: {error}", case["id"]));
        assert_eq!(serde_json::to_value(&delta).unwrap(), *payload);
        count += 1;
    }
    assert_eq!(count, 5);
}

#[test]
fn schema_rejects_extra_keys_invalid_ids_and_changed_hashes() {
    let sample = &with_graphs()[0]["graphs"]["baseline"];
    let mut extra = sample.clone();
    extra["not_in_schema"] = json!(true);
    assert!(serde_json::from_value::<ProvenanceGraph>(extra).is_err());

    let mut forged = sample.clone();
    forged["graph_hash"] = json!("0".repeat(64));
    let forged_model: ProvenanceGraph = serde_json::from_value(forged).unwrap();
    assert!(forged_model.validate().is_err());

    let mut malformed = sample.clone();
    malformed["nodes"][0]["node_id"] = json!("0".repeat(64));
    let malformed_model: ProvenanceGraph = serde_json::from_value(malformed).unwrap();
    assert!(malformed_model.validate().is_err());
}

#[test]
fn schema_rejects_privileged_event_attributes() {
    let graph = &with_graphs()[0]["graphs"]["baseline"];
    let mut invalid = graph.clone();
    let index = invalid["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .position(|node| node["node_kind"] == "event")
        .unwrap();
    invalid["nodes"][index]["attributes"] = json!({"nested": {"severity": "high"}});
    let model: ProvenanceGraph = serde_json::from_value(invalid).unwrap();
    assert!(model.validate().is_err());
}

#[test]
fn golden_delta_rejects_repeated_node_classification() {
    let mut sample = with_delta()[0]["delta"].clone();
    let present = sample["node_unchanged"][0].clone();
    sample["node_added"] = json!([present]);
    sample["delta_hash"] = json!(canonical_hash(&{
        let mut body = sample.clone();
        body.as_object_mut().unwrap().remove("delta_hash");
        body
    })
    .unwrap());
    let model: DeltaG = serde_json::from_value(sample).unwrap();
    assert!(model.validate().is_err());
}

#[test]
fn canonical_json_orders_keys_and_keeps_utf8() {
    let original = json!({"z": [true, null, 1], "á": {"β": "España", "a": 3}, "a": 2});
    let expected = "{\"a\":2,\"z\":[true,null,1],\"á\":{\"a\":3,\"β\":\"España\"}}";
    assert_eq!(
        canonical_json_bytes(&original).unwrap(),
        expected.as_bytes()
    );
    assert_eq!(
        canonical_hash(&original).unwrap(),
        sha256_hex(expected.as_bytes())
    );
}

#[test]
fn golden_corpus_still_has_ten_families_and_fifteen_cases() {
    let data = golden();
    let cases = data["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 15);
    let families: BTreeSet<_> = cases
        .iter()
        .map(|case| case["id"].as_str().unwrap())
        .collect();
    assert_eq!(families.len(), 10);
    for (index, family) in families.iter().enumerate() {
        assert_eq!(*family, format!("G{:02}", index + 1));
    }
}

#[test]
fn delta_model_rejects_incompatible_schema_versions() {
    let mut sample = with_delta()[0]["delta"].clone();
    sample["schema_version"] = json!("provenance-delta-v2");
    let delta: DeltaG = serde_json::from_value(sample).unwrap();
    assert!(delta.validate().is_err());
}

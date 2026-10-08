//! R0.9-R2: proyección real desde eventos y validación DAG contra F2/F3.

use provregress_reference::{
    canonical_hash, canonical_json_bytes, project_trace, validate_dag, EventEnvelope,
    ProvenanceGraph,
};
use serde_json::{json, Value};

const INPUTS: &str = include_str!("../../../tests/fixtures/provenance/r0_8/inputs.json");
const EXPECTED: &str = include_str!("../../../tests/fixtures/provenance/r0_8/expected.json");

fn corpus() -> (Value, Value) {
    (
        serde_json::from_str(INPUTS).unwrap(),
        serde_json::from_str(EXPECTED).unwrap(),
    )
}

fn events(items: &Value) -> Vec<EventEnvelope> {
    serde_json::from_value(items.clone()).expect("Traza tipada")
}

fn validated_graph(raw: &Value) -> ProvenanceGraph {
    serde_json::from_value(raw.clone()).expect("Grafo golden tipado")
}

#[test]
fn all_positive_traces_project_exact_golden_graphs() {
    let (inputs, expected) = corpus();
    let mut count = 0;
    for (source, outcome) in inputs["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(expected["cases"].as_array().unwrap())
    {
        assert_eq!(source["id"], outcome["id"]);
        assert_eq!(source["variant"], outcome["variant"]);
        let Some(graphs) = outcome.get("graphs") else {
            continue;
        };
        for (role, golden) in graphs.as_object().unwrap() {
            let trace = events(&source["traces"][role.as_str()]);
            let projected = project_trace(&trace).expect("La traza positiva se proyecta");
            validate_dag(&projected).expect("El resultado debe ser DAG");
            assert_eq!(serde_json::to_value(&projected).unwrap(), *golden);
            assert_eq!(
                canonical_json_bytes(&serde_json::to_value(&projected).unwrap()).unwrap(),
                canonical_json_bytes(golden).unwrap()
            );
            assert_eq!(projected, project_trace(&trace).unwrap());
            assert!(projected.trace_hash.is_none());
            count += 1;
        }
    }
    assert_eq!(count, 12);
}

#[test]
fn rejects_future_parents_non_contiguous_sequences_and_invalid_cycle() {
    let (inputs, expected) = corpus();
    let mut failures = 0;
    for (source, outcome) in inputs["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(expected["cases"].as_array().unwrap())
    {
        if outcome["error"]["stage"] != "projection" {
            continue;
        }
        let trace = events(&source["traces"]["baseline"]);
        assert!(project_trace(&trace).is_err(), "{}", source["variant"]);
        failures += 1;
    }
    assert_eq!(failures, 3);
}

#[test]
fn validator_detects_cycle_with_valid_ids_and_graph_hash() {
    let (inputs, _) = corpus();
    let forged = inputs["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == "G07" && item["variant"] == "explicit-dag-cycle")
        .unwrap();
    let graph = validated_graph(&forged["graph_to_validate"]);
    graph
        .validate()
        .expect("El schema del ciclo adulterado es consistente");
    let error = validate_dag(&graph).unwrap_err();
    assert!(error.to_string().contains("ciclo"));
}

#[test]
fn reserved_attributes_fail_before_projection() {
    let (inputs, _) = corpus();
    let mut rejected = 0;
    for input in inputs["cases"].as_array().unwrap() {
        if input["id"] != "G09" {
            continue;
        }
        assert!(project_trace(&events(&input["traces"]["baseline"])).is_err());
        rejected += 1;
    }
    assert_eq!(rejected, 2);
}

#[test]
fn duplicated_event_id_is_rejected() {
    let (inputs, _) = corpus();
    let source = inputs["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == "G01")
        .unwrap();
    let mut trace = events(&source["traces"]["baseline"]);
    trace[1].event_id = trace[0].event_id.clone();
    assert!(project_trace(&trace).is_err());
}

#[test]
fn shared_digest_with_incompatible_references_is_rejected() {
    let (inputs, _) = corpus();
    let source = inputs["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == "G01")
        .unwrap();
    let mut trace = events(&source["traces"]["baseline"]);
    trace[1].payload_ref = None;
    assert!(project_trace(&trace).is_err());
}

#[test]
fn artifact_reference_must_match_payload_digest() {
    let (inputs, _) = corpus();
    let source = inputs["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == "G01")
        .unwrap();
    let mut trace = events(&source["traces"]["baseline"]);
    trace[0].payload_hash.value = "0".repeat(64);
    assert!(project_trace(&trace).is_err());
}

#[test]
fn mixing_runs_is_forbidden_even_with_valid_individual_events() {
    let (inputs, _) = corpus();
    let base = inputs["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == "G02")
        .unwrap();
    let mut trace = events(&base["traces"]["baseline"]);
    let mut next = events(&base["traces"]["candidate"]);
    next[0].sequence = 1;
    trace.extend(next);
    assert!(project_trace(&trace).is_err());
}

#[test]
fn rejects_empty_traces_and_extra_event_fields() {
    assert!(project_trace(&[]).is_err());
    let (inputs, _) = corpus();
    let mut value = inputs["cases"][0]["traces"]["baseline"][0].clone();
    value["unknown"] = json!(true);
    assert!(serde_json::from_value::<EventEnvelope>(value).is_err());
}

#[test]
fn offset_timestamp_is_normalized_to_utc() {
    let (inputs, _) = corpus();
    let baseline = &inputs["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == "G02")
        .unwrap()["traces"]["baseline"];
    let mut trace = events(baseline);
    trace[0].timestamp_utc = "2026-10-08T12:00:00-05:00".to_owned();
    let graph = project_trace(&trace).unwrap();
    let event = graph
        .nodes
        .iter()
        .find(|node| serde_json::to_value(node).unwrap()["node_kind"] == "event")
        .unwrap();
    assert_eq!(
        serde_json::to_value(event).unwrap()["timestamp_utc"],
        "2026-10-08T17:00:00Z"
    );
}

#[test]
fn rejects_graph_without_required_relation_even_if_hash_is_recomputed() {
    let (_, expected) = corpus();
    let mut graph = expected["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == "G02")
        .unwrap()["graphs"]["baseline"]
        .clone();
    let edges = graph["edges"].as_array_mut().unwrap();
    edges.retain(|edge| edge["edge_kind"] != "produces");
    let mut without_hash = graph.clone();
    without_hash.as_object_mut().unwrap().remove("graph_hash");
    graph["graph_hash"] = json!(canonical_hash(&without_hash).unwrap());
    let checked = validated_graph(&graph);
    checked.validate().unwrap();
    assert!(validate_dag(&checked).is_err());
}

#[test]
fn golden_values_remain_immutable() {
    let (inputs, expected) = corpus();
    assert_eq!(
        provregress_reference::sha256_hex(INPUTS.as_bytes()),
        "9d2be2dd2d894e7c4c7508cad0bb6160147dc01d82e3d1090e7903a69d9eb242"
    );
    assert_eq!(
        provregress_reference::sha256_hex(EXPECTED.as_bytes()),
        "47fd5e198f25704ee0fbc6363ea3621754397aad9ca72507be4a68752fa4be50"
    );
    assert_eq!(inputs["cases"].as_array().unwrap().len(), 15);
    assert_eq!(expected["cases"].as_array().unwrap().len(), 15);
}

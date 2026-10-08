//! Conformidad R0.9-R3 con los cinco diferenciales F2/F3 congelados.

use provregress_reference::{
    align_graphs, canonical_hash, canonical_json_bytes, diff_graphs, project_trace, AlignmentError,
    DeltaG, EventEnvelope, GraphDiffError, ProvenanceGraph,
};
use serde_json::{json, Value};

const INPUTS: &str = include_str!("../../../tests/fixtures/provenance/r0_8/inputs.json");
const EXPECTED: &str = include_str!("../../../tests/fixtures/provenance/r0_8/expected.json");

fn fixtures() -> Value {
    serde_json::from_str(EXPECTED).expect("Corpus F2 válido")
}

fn fixture(name: &str) -> Value {
    fixtures()["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == name && item["delta"].is_object())
        .unwrap_or_else(|| panic!("No se encontró el fixture {name}"))
        .clone()
}

fn graphs(name: &str) -> (ProvenanceGraph, ProvenanceGraph) {
    let record = fixture(name);
    (
        serde_json::from_value(record["graphs"]["baseline"].clone()).unwrap(),
        serde_json::from_value(record["graphs"]["candidate"].clone()).unwrap(),
    )
}

fn rehash(mut graph: Value) -> ProvenanceGraph {
    let _ = graph.as_object_mut().unwrap().remove("graph_hash");
    let digest = canonical_hash(&graph).unwrap();
    graph["graph_hash"] = json!(digest);
    serde_json::from_value(graph).unwrap()
}

#[test]
fn all_five_frozen_deltas_match_exactly() {
    for family in ["G02", "G03", "G04", "G05", "G06"] {
        let (baseline, candidate) = graphs(family);
        let actual = diff_graphs(&baseline, &candidate).unwrap();
        let expected = fixture(family)["delta"].clone();
        let expected_model: DeltaG = serde_json::from_value(expected.clone()).unwrap();
        actual.validate().unwrap();
        assert_eq!(actual, expected_model, "{family}: contenido tipado");
        let actual_json = serde_json::to_value(&actual).unwrap();
        assert_eq!(actual_json, expected, "{family}: diferencias canónicas");
        assert_eq!(
            canonical_json_bytes(&actual_json).unwrap(),
            canonical_json_bytes(&expected).unwrap(),
            "{family}: bytes"
        );
        assert_eq!(actual.delta_hash, expected["delta_hash"].as_str().unwrap());
    }
}

#[test]
fn g02_ignores_run_clock_and_system_version() {
    let (before, after) = graphs("G02");
    assert_ne!(before.run_id, after.run_id);
    assert_ne!(before.system_version_id, after.system_version_id);
    let alignment = align_graphs(&before, &after).unwrap();
    assert_eq!(alignment.pairs.len(), 3);
    assert!(alignment.ambiguous.is_empty());
    let delta = diff_graphs(&before, &after).unwrap();
    assert_eq!(delta.node_unchanged.len(), 3);
    assert!(delta.node_changed.is_empty() && delta.edge_added.is_empty());
}

#[test]
fn g03_changes_payload_without_pairing_payload_nodes_by_similarity() {
    let (before, after) = graphs("G03");
    let alignment = align_graphs(&before, &after).unwrap();
    assert_eq!(alignment.baseline_only.len(), 1);
    assert_eq!(alignment.candidate_only.len(), 1);
    assert_eq!(alignment.baseline_only[0].key[0], "payload");
    let delta = diff_graphs(&before, &after).unwrap();
    assert_eq!(delta.node_changed.len(), 1);
    assert_eq!(delta.node_changed[0].changed_fields, vec!["payload_hash"]);
    assert_eq!(delta.edge_added.len(), 1);
    assert_eq!(delta.edge_removed.len(), 1);
}

#[test]
fn g04_reports_only_explicit_parent_added() {
    let (before, after) = graphs("G04");
    let delta = diff_graphs(&before, &after).unwrap();
    assert_eq!(delta.edge_added.len(), 1);
    assert!(delta.edge_removed.is_empty());
    assert!(delta.node_changed.is_empty());
    assert_eq!(
        serde_json::to_value(delta.edge_added[0].edge_kind).unwrap(),
        "observed_parent"
    );
}

#[test]
fn g05_independent_reorder_does_not_signal_regression() {
    let (before, after) = graphs("G05");
    let delta = diff_graphs(&before, &after).unwrap();
    assert!(delta.node_changed.is_empty());
    assert!(delta.node_added.is_empty());
    assert!(delta.node_removed.is_empty());
    assert!(delta.edge_added.is_empty());
    assert!(delta.edge_removed.is_empty());
    assert!(delta.node_ambiguous.is_empty());
}

#[test]
fn g06_never_assigns_repeated_calls_by_position() {
    let (before, after) = graphs("G06");
    let alignment = align_graphs(&before, &after).unwrap();
    assert_eq!(alignment.ambiguous.len(), 1);
    assert_eq!(alignment.ambiguous[0].baseline_count(), 2);
    assert_eq!(alignment.ambiguous[0].candidate_count(), 2);
    let key = &alignment.ambiguous[0].key;
    assert!(!alignment.pairs.iter().any(|pair| &pair.key == key));
    let delta = diff_graphs(&before, &after).unwrap();
    assert_eq!(delta.node_ambiguous.len(), 1);
    assert_eq!(delta.edge_ambiguous.len(), 4);
    assert!(delta.edge_ambiguous.iter().all(|edge| edge.count == 2));
}

#[test]
fn g06_one_sided_repetition_remains_ambiguous() {
    let data: Value = serde_json::from_str(INPUTS).unwrap();
    let source = data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == "G06")
        .unwrap();
    let candidate_events = source["traces"]["candidate"].as_array().unwrap();
    let single: EventEnvelope = serde_json::from_value(candidate_events[0].clone()).unwrap();
    let candidate = project_trace(&[single]).unwrap();
    let baseline = graphs("G06").0;
    let aligned = align_graphs(&baseline, &candidate).unwrap();
    let repeated = aligned
        .ambiguous
        .iter()
        .find(|g| g.key[0] == "event")
        .unwrap();
    assert_eq!(repeated.baseline_count(), 2);
    assert_eq!(repeated.candidate_count(), 1);
    let delta = diff_graphs(&baseline, &candidate).unwrap();
    assert_eq!(delta.node_ambiguous[0].baseline_count, 2);
    assert_eq!(delta.node_ambiguous[0].candidate_count, 1);
}

#[test]
fn g08_rejects_incompatible_application_and_case_before_diff() {
    let data: Value = serde_json::from_str(INPUTS).unwrap();
    for (variant, expected) in [
        ("case-mismatch", "case_mismatch"),
        ("app-mismatch", "app_mismatch"),
    ] {
        let case = data["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|item| item["id"] == "G08" && item["variant"] == variant)
            .unwrap();
        let roles = &case["traces"];
        let left: Vec<EventEnvelope> = serde_json::from_value(roles["baseline"].clone()).unwrap();
        let right: Vec<EventEnvelope> = serde_json::from_value(roles["candidate"].clone()).unwrap();
        let before = project_trace(&left).unwrap();
        let after = project_trace(&right).unwrap();
        let err = align_graphs(&before, &after).unwrap_err();
        assert_eq!(err.code(), expected);
        assert!(matches!(
            diff_graphs(&before, &after),
            Err(GraphDiffError::Alignment(_))
        ));
    }
}

#[test]
fn repeat_index_is_a_required_comparability_condition() {
    let (before, after) = graphs("G02");
    let mut altered = serde_json::to_value(&after).unwrap();
    altered["repeat_index"] = json!(11);
    let candidate = rehash(altered);
    assert!(matches!(
        align_graphs(&before, &candidate),
        Err(AlignmentError::Incompatible("repeat_mismatch"))
    ));
}

#[test]
fn invalid_graph_is_rejected_even_when_hash_is_recomputed() {
    let (before, after) = graphs("G02");
    let mut altered = serde_json::to_value(&after).unwrap();
    altered["edges"][0]["source_node_id"] = json!("0".repeat(64));
    // El ID de arista debe seguir la huella nueva para que la validación estructural lo examine.
    let edge = &mut altered["edges"][0];
    let parts = json!([
        "r0.8.edge.v1",
        edge["edge_kind"],
        edge["source_node_id"],
        edge["target_node_id"]
    ]);
    edge["edge_id"] = json!(canonical_hash(&parts).unwrap());
    let entries = altered["edges"].as_array_mut().unwrap();
    entries.sort_by(|x, y| x["edge_id"].as_str().cmp(&y["edge_id"].as_str()));
    let candidate = rehash(altered);
    assert!(align_graphs(&before, &candidate).is_err());
    assert!(diff_graphs(&before, &candidate).is_err());
}

#[test]
fn changed_observable_attributes_are_reported_without_new_event_pairing() {
    let (before, after) = graphs("G02");
    let mut changed = serde_json::to_value(&after).unwrap();
    let event = changed["nodes"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|node| node["node_kind"] == "event")
        .unwrap();
    event["attributes"] = json!({"new_attribute": true});
    let candidate = rehash(changed);
    let delta = diff_graphs(&before, &candidate).unwrap();
    assert_eq!(delta.node_changed.len(), 1);
    assert_eq!(delta.node_changed[0].changed_fields, vec!["attributes"]);
    assert!(delta.edge_added.is_empty() && delta.edge_removed.is_empty());
}

#[test]
fn repeated_calls_are_deterministic_without_mutating_inputs() {
    for name in ["G02", "G03", "G04", "G05", "G06"] {
        let (before, after) = graphs(name);
        let left_bytes = canonical_json_bytes(&serde_json::to_value(&before).unwrap()).unwrap();
        let right_bytes = canonical_json_bytes(&serde_json::to_value(&after).unwrap()).unwrap();
        let first = canonical_json_bytes(
            &serde_json::to_value(diff_graphs(&before, &after).unwrap()).unwrap(),
        )
        .unwrap();
        for _ in 0..3 {
            let actual = canonical_json_bytes(
                &serde_json::to_value(diff_graphs(&before, &after).unwrap()).unwrap(),
            )
            .unwrap();
            assert_eq!(actual, first, "Diferencial no determinista para {name}");
        }
        assert_eq!(
            canonical_json_bytes(&serde_json::to_value(&before).unwrap()).unwrap(),
            left_bytes
        );
        assert_eq!(
            canonical_json_bytes(&serde_json::to_value(&after).unwrap()).unwrap(),
            right_bytes
        );
    }
}

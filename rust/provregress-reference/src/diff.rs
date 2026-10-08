//! DeltaG tipado P3 sobre el alineamiento conservador y los oráculos F2/F3.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::error::Error;
use std::fmt;

use serde::Serialize;
use serde_json::Value;

use crate::alignment::{align_graphs, semantic_key, AlignmentError};
use crate::canonical::{canonical_hash, canonical_json_bytes};
use crate::schema::{
    DeltaG, EdgeAmbiguous, EdgeChange, EdgeKind, GraphNode, NodeAmbiguous, NodeChanged,
    ProvenanceGraph, SchemaError, SemanticKey, Side,
};

type RelationKey = (String, SemanticKey, SemanticKey);

#[derive(Debug)]
pub enum GraphDiffError {
    Alignment(AlignmentError),
    Schema(SchemaError),
    Json(serde_json::Error),
    DuplicateRelation,
}

impl fmt::Display for GraphDiffError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Alignment(error) => write!(f, "Alineamiento fallido: {error}"),
            Self::Schema(error) => write!(f, "DeltaG no válido: {error}"),
            Self::Json(error) => write!(f, "Serialización no válida: {error}"),
            Self::DuplicateRelation => write!(f, "Aristas comparables duplicadas"),
        }
    }
}

impl Error for GraphDiffError {}

impl From<AlignmentError> for GraphDiffError {
    fn from(error: AlignmentError) -> Self {
        Self::Alignment(error)
    }
}

impl From<SchemaError> for GraphDiffError {
    fn from(error: SchemaError) -> Self {
        Self::Schema(error)
    }
}

impl From<serde_json::Error> for GraphDiffError {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error)
    }
}

fn canonical_sort<T: Serialize>(entries: &mut Vec<T>) -> Result<(), GraphDiffError> {
    let mut ordered = Vec::with_capacity(entries.len());
    for item in std::mem::take(entries) {
        let encoded = canonical_json_bytes(&serde_json::to_value(&item)?)?;
        ordered.push((encoded, item));
    }
    ordered.sort_by(|left, right| left.0.cmp(&right.0));
    *entries = ordered.into_iter().map(|(_, item)| item).collect();
    Ok(())
}

fn edge_kind_name(kind: EdgeKind) -> &'static str {
    match kind {
        EdgeKind::Emits => "emits",
        EdgeKind::ObservedParent => "observed_parent",
        EdgeKind::Produces => "produces",
    }
}

fn edge_kind_from_name(name: &str) -> EdgeKind {
    match name {
        "emits" => EdgeKind::Emits,
        "observed_parent" => EdgeKind::ObservedParent,
        "produces" => EdgeKind::Produces,
        _ => unreachable!("Las aristas se validan antes del diferencial"),
    }
}

fn classify_edges(
    graph: &ProvenanceGraph,
    ambiguous: &HashSet<SemanticKey>,
) -> Result<(BTreeSet<RelationKey>, BTreeMap<RelationKey, u64>), GraphDiffError> {
    let nodes: HashMap<_, _> = graph
        .nodes
        .iter()
        .map(|node| (node.node_id(), node))
        .collect();
    let mut comparable = BTreeSet::new();
    let mut unresolved = BTreeMap::new();
    for relation in &graph.edges {
        // validate_dag() de I2 ya comprobó ambos extremos.
        let source = semantic_key(nodes[relation.source_node_id.as_str()]);
        let target = semantic_key(nodes[relation.target_node_id.as_str()]);
        let incident = ambiguous.contains(&source) || ambiguous.contains(&target);
        let key = (
            edge_kind_name(relation.edge_kind).to_owned(),
            source,
            target,
        );
        if incident {
            *unresolved.entry(key).or_insert(0) += 1;
        } else if !comparable.insert(key) {
            return Err(GraphDiffError::DuplicateRelation);
        }
    }
    Ok((comparable, unresolved))
}

fn edge_change(key: &RelationKey) -> EdgeChange {
    EdgeChange {
        edge_kind: edge_kind_from_name(&key.0),
        source_key: key.1.clone(),
        target_key: key.2.clone(),
    }
}

/// Deriva diferencias observables y topológicas sin inferir correspondencias.
pub fn diff_graphs(
    baseline: &ProvenanceGraph,
    candidate: &ProvenanceGraph,
) -> Result<DeltaG, GraphDiffError> {
    let alignment = align_graphs(baseline, candidate)?;
    let left: HashMap<_, _> = baseline
        .nodes
        .iter()
        .map(|node| (node.node_id(), node))
        .collect();
    let right: HashMap<_, _> = candidate
        .nodes
        .iter()
        .map(|node| (node.node_id(), node))
        .collect();

    let mut delta = DeltaG {
        schema_version: "provenance-delta-v1".to_owned(),
        baseline_run_id: baseline.run_id.clone(),
        candidate_run_id: candidate.run_id.clone(),
        node_added: alignment
            .candidate_only
            .iter()
            .map(|item| item.key.clone())
            .collect(),
        node_removed: alignment
            .baseline_only
            .iter()
            .map(|item| item.key.clone())
            .collect(),
        node_unchanged: Vec::new(),
        node_changed: Vec::new(),
        node_ambiguous: alignment
            .ambiguous
            .iter()
            .map(|group| NodeAmbiguous {
                key: group.key.clone(),
                baseline_count: group.baseline_count() as u64,
                candidate_count: group.candidate_count() as u64,
            })
            .collect(),
        edge_added: Vec::new(),
        edge_removed: Vec::new(),
        edge_ambiguous: Vec::new(),
        delta_hash: String::new(),
    };

    for pair in &alignment.pairs {
        let original = left[pair.baseline_node_id.as_str()];
        let updated = right[pair.candidate_node_id.as_str()];
        if let (
            GraphNode::Event {
                payload_hash: before_hash,
                attributes: before_attrs,
                error: before_error,
                ..
            },
            GraphNode::Event {
                payload_hash: after_hash,
                attributes: after_attrs,
                error: after_error,
                ..
            },
        ) = (original, updated)
        {
            let mut fields = Vec::new();
            if before_hash != after_hash {
                fields.push("payload_hash".to_owned());
            }
            if before_attrs != after_attrs {
                fields.push("attributes".to_owned());
            }
            if before_error != after_error {
                fields.push("error".to_owned());
            }
            fields.sort();
            if fields.is_empty() {
                delta.node_unchanged.push(pair.key.clone());
            } else {
                delta.node_changed.push(NodeChanged {
                    key: pair.key.clone(),
                    changed_fields: fields,
                });
            }
        } else {
            delta.node_unchanged.push(pair.key.clone());
        }
    }

    let ambiguous: HashSet<SemanticKey> = alignment
        .ambiguous
        .iter()
        .map(|group| group.key.clone())
        .collect();
    let (before_edges, before_unclear) = classify_edges(baseline, &ambiguous)?;
    let (after_edges, after_unclear) = classify_edges(candidate, &ambiguous)?;
    delta.edge_added = after_edges
        .difference(&before_edges)
        .map(edge_change)
        .collect();
    delta.edge_removed = before_edges
        .difference(&after_edges)
        .map(edge_change)
        .collect();
    for (side, records) in [
        (Side::Baseline, before_unclear),
        (Side::Candidate, after_unclear),
    ] {
        for (key, count) in records {
            let edge = edge_change(&key);
            delta.edge_ambiguous.push(EdgeAmbiguous {
                edge_kind: edge.edge_kind,
                source_key: edge.source_key,
                target_key: edge.target_key,
                side,
                count,
            });
        }
    }

    canonical_sort(&mut delta.node_added)?;
    canonical_sort(&mut delta.node_removed)?;
    canonical_sort(&mut delta.node_unchanged)?;
    canonical_sort(&mut delta.node_changed)?;
    canonical_sort(&mut delta.node_ambiguous)?;
    canonical_sort(&mut delta.edge_added)?;
    canonical_sort(&mut delta.edge_removed)?;
    canonical_sort(&mut delta.edge_ambiguous)?;

    let mut content = serde_json::to_value(&delta)?;
    if let Value::Object(fields) = &mut content {
        let _ = fields.remove("delta_hash");
    }
    delta.delta_hash = canonical_hash(&content)?;
    delta.validate()?;
    Ok(delta)
}

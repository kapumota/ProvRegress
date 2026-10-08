//! Correspondencia P3 conservadora de nodos entre dos ejecuciones observables.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;

use serde_json::to_value;

use crate::canonical::canonical_json_bytes;
use crate::projector::validate_dag;
use crate::schema::{GraphNode, ProvenanceGraph, SemanticKey};

#[derive(Debug)]
pub enum AlignmentError {
    InvalidGraph(String),
    Incompatible(&'static str),
    Json(serde_json::Error),
    Invalid(&'static str),
}

impl AlignmentError {
    /// Identificador estable para las precondiciones P3 incompatibles.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Incompatible(code) => code,
            Self::InvalidGraph(_) => "invalid_graph",
            Self::Json(_) => "invalid_json",
            Self::Invalid(_) => "invalid_alignment",
        }
    }
}

impl fmt::Display for AlignmentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidGraph(message) => write!(f, "Grafo no válido: {message}"),
            Self::Incompatible(code) => write!(f, "Grafos no comparables: {code}"),
            Self::Json(error) => write!(f, "Serialización no válida: {error}"),
            Self::Invalid(message) => write!(f, "{message}"),
        }
    }
}

impl Error for AlignmentError {}

impl From<serde_json::Error> for AlignmentError {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AlignedNode {
    pub key: SemanticKey,
    pub baseline_node_id: String,
    pub candidate_node_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnmatchedNode {
    pub key: SemanticKey,
    pub node_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AmbiguousGroup {
    pub key: SemanticKey,
    pub baseline_node_ids: Vec<String>,
    pub candidate_node_ids: Vec<String>,
}

impl AmbiguousGroup {
    pub fn baseline_count(&self) -> usize {
        self.baseline_node_ids.len()
    }

    pub fn candidate_count(&self) -> usize {
        self.candidate_node_ids.len()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphAlignment {
    pub baseline_run_id: String,
    pub candidate_run_id: String,
    pub pairs: Vec<AlignedNode>,
    pub baseline_only: Vec<UnmatchedNode>,
    pub candidate_only: Vec<UnmatchedNode>,
    pub ambiguous: Vec<AmbiguousGroup>,
}

/// Identifica objetos comparables sin run, condición, reloj ni número de secuencia.
pub fn semantic_key(node: &GraphNode) -> SemanticKey {
    fn string_value<T: serde::Serialize>(item: &T) -> String {
        match to_value(item) {
            Ok(serde_json::Value::String(value)) => value,
            _ => unreachable!("Los enums del contrato se serializan como texto"),
        }
    }
    match node {
        GraphNode::Component {
            component_type,
            component_id,
            ..
        } => {
            vec![
                "component".into(),
                string_value(component_type),
                component_id.clone(),
            ]
        }
        GraphNode::Event {
            component_type,
            component_id,
            event_type,
            ..
        } => vec![
            "event".into(),
            string_value(component_type),
            component_id.clone(),
            string_value(event_type),
        ],
        GraphNode::Payload { payload_hash, .. } => {
            vec!["payload".into(), payload_hash.value.clone()]
        }
    }
}

fn group_nodes(graph: &ProvenanceGraph) -> BTreeMap<SemanticKey, Vec<String>> {
    let mut result: BTreeMap<SemanticKey, Vec<String>> = BTreeMap::new();
    for node in &graph.nodes {
        result
            .entry(semantic_key(node))
            .or_default()
            .push(node.node_id().to_owned());
    }
    for values in result.values_mut() {
        values.sort_unstable();
    }
    result
}

/// La correspondencia es inyectiva y deja grupos repetidos sin emparejar.
pub fn align_graphs(
    baseline: &ProvenanceGraph,
    candidate: &ProvenanceGraph,
) -> Result<GraphAlignment, AlignmentError> {
    validate_dag(baseline).map_err(|error| AlignmentError::InvalidGraph(error.to_string()))?;
    validate_dag(candidate).map_err(|error| AlignmentError::InvalidGraph(error.to_string()))?;
    if baseline.app_id != candidate.app_id {
        return Err(AlignmentError::Incompatible("app_mismatch"));
    }
    if baseline.case_id != candidate.case_id {
        return Err(AlignmentError::Incompatible("case_mismatch"));
    }
    if baseline.repeat_index != candidate.repeat_index {
        return Err(AlignmentError::Incompatible("repeat_mismatch"));
    }

    let before = group_nodes(baseline);
    let after = group_nodes(candidate);
    let mut keys: BTreeSet<SemanticKey> = before.keys().cloned().collect();
    keys.extend(after.keys().cloned());
    let mut ordered = Vec::with_capacity(keys.len());
    for key in keys {
        ordered.push((canonical_json_bytes(&to_value(&key)?)?, key));
    }
    ordered.sort_by(|left, right| left.0.cmp(&right.0));

    let mut result = GraphAlignment {
        baseline_run_id: baseline.run_id.clone(),
        candidate_run_id: candidate.run_id.clone(),
        pairs: Vec::new(),
        baseline_only: Vec::new(),
        candidate_only: Vec::new(),
        ambiguous: Vec::new(),
    };
    for (_, key) in ordered {
        let left = before.get(&key).map(Vec::as_slice).unwrap_or_default();
        let right = after.get(&key).map(Vec::as_slice).unwrap_or_default();
        if left.len() > 1 || right.len() > 1 {
            if key[0] != "event" {
                return Err(AlignmentError::Invalid("Solo los eventos pueden repetirse"));
            }
            result.ambiguous.push(AmbiguousGroup {
                key,
                baseline_node_ids: left.to_vec(),
                candidate_node_ids: right.to_vec(),
            });
        } else if let ([before_id], [after_id]) = (left, right) {
            result.pairs.push(AlignedNode {
                key,
                baseline_node_id: before_id.clone(),
                candidate_node_id: after_id.clone(),
            });
        } else if let [before_id] = left {
            result.baseline_only.push(UnmatchedNode {
                key,
                node_id: before_id.clone(),
            });
        } else if let [after_id] = right {
            result.candidate_only.push(UnmatchedNode {
                key,
                node_id: after_id.clone(),
            });
        }
    }
    Ok(result)
}

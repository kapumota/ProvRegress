//! Representaciones P2/P3: sin projector, alineamiento ni diferencial ejecutable.

use std::collections::HashSet;
use std::error::Error;
use std::fmt;

use chrono::DateTime;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};

use crate::canonical::{canonical_hash, canonical_json_bytes};

#[derive(Debug)]
pub enum SchemaError {
    Invalid(&'static str),
    Json(serde_json::Error),
}

impl fmt::Display for SchemaError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "{message}"),
            Self::Json(error) => write!(formatter, "JSON no válido: {error}"),
        }
    }
}

impl Error for SchemaError {}

impl From<serde_json::Error> for SchemaError {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error)
    }
}

fn require(ok: bool, message: &'static str) -> Result<(), SchemaError> {
    if ok {
        Ok(())
    } else {
        Err(SchemaError::Invalid(message))
    }
}

fn nonblank(value: &str) -> bool {
    !value.trim().is_empty()
}

fn is_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}

fn hash_parts(parts: Value) -> Result<String, SchemaError> {
    Ok(canonical_hash(&parts)?)
}

fn hash_without<T: Serialize>(value: &T, key: &str) -> Result<String, SchemaError> {
    let mut object = serde_json::to_value(value)?;
    if let Value::Object(fields) = &mut object {
        fields.remove(key);
    }
    Ok(canonical_hash(&object)?)
}

fn check_observable(value: &Value) -> Result<(), SchemaError> {
    match value {
        Value::Object(fields) => {
            for (key, item) in fields {
                require(
                    !matches!(
                        key.as_str(),
                        "mutation_id" | "operator_id" | "target_component_id" | "severity"
                    ),
                    "Etiqueta experimental reservada",
                )?;
                check_observable(item)?;
            }
        }
        Value::Array(items) => {
            for item in items {
                check_observable(item)?;
            }
        }
        _ => {}
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AppId {
    #[serde(rename = "a1_extraction")]
    A1,
    #[serde(rename = "a2_rag")]
    A2,
    #[serde(rename = "a3_tools")]
    A3,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ComponentType {
    InputCase,
    SystemVersion,
    Prompt,
    Model,
    Retriever,
    Corpus,
    Chunk,
    Ranker,
    Agent,
    Tool,
    ToolCall,
    ToolResult,
    Schema,
    GeneratedArtifact,
    Claim,
    Citation,
    Evaluator,
    Evaluation,
    Outcome,
    Failure,
    Runtime,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EventType {
    #[serde(rename = "run.started")]
    RunStarted,
    #[serde(rename = "run.finished")]
    RunFinished,
    #[serde(rename = "prompt.issued")]
    PromptIssued,
    #[serde(rename = "model.invoked")]
    ModelInvoked,
    #[serde(rename = "model.returned")]
    ModelReturned,
    #[serde(rename = "retrieval.started")]
    RetrievalStarted,
    #[serde(rename = "retrieval.returned")]
    RetrievalReturned,
    #[serde(rename = "tool.called")]
    ToolCalled,
    #[serde(rename = "tool.returned")]
    ToolReturned,
    #[serde(rename = "evaluator.invoked")]
    EvaluatorInvoked,
    #[serde(rename = "evaluator.scored")]
    EvaluatorScored,
    #[serde(rename = "outcome.recorded")]
    OutcomeRecorded,
    #[serde(rename = "error.observed")]
    ErrorObserved,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EdgeKind {
    Emits,
    ObservedParent,
    Produces,
}

impl EdgeKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Emits => "emits",
            Self::ObservedParent => "observed_parent",
            Self::Produces => "produces",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HashRef {
    pub algorithm: HashAlgorithm,
    pub value: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum HashAlgorithm {
    #[serde(rename = "sha256")]
    Sha256,
}

impl HashRef {
    pub fn validate(&self) -> Result<(), SchemaError> {
        require(is_digest(&self.value), "Digest SHA-256 inválido")
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactRef {
    pub hash: HashRef,
    pub relative_path: String,
    pub media_type: Option<String>,
    pub size_bytes: u64,
}

impl ArtifactRef {
    pub fn validate(&self) -> Result<(), SchemaError> {
        self.hash.validate()?;
        let path = self.relative_path.as_str();
        require(
            nonblank(path)
                && !path.starts_with('/')
                && !path.contains('\\')
                && !path.contains('\0')
                && !path.as_bytes().get(1).is_some_and(|x| *x == b':')
                && path
                    .split('/')
                    .all(|segment| !segment.is_empty() && segment != "." && segment != ".."),
            "Ruta relativa de artefacto no canónica",
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EventError {
    pub category: String,
    pub message: String,
    pub retryable: bool,
    pub details: Map<String, Value>,
}

impl EventError {
    fn validate(&self) -> Result<(), SchemaError> {
        require(
            nonblank(&self.category) && nonblank(&self.message),
            "Error observable sin identidad",
        )?;
        check_observable(&Value::Object(self.details.clone()))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "node_kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum GraphNode {
    Component {
        node_id: String,
        component_type: ComponentType,
        component_id: String,
    },
    Event {
        node_id: String,
        event_id: String,
        sequence: u64,
        timestamp_utc: String,
        event_type: EventType,
        component_type: ComponentType,
        component_id: String,
        payload_hash: HashRef,
        attributes: Map<String, Value>,
        error: Option<EventError>,
    },
    Payload {
        node_id: String,
        payload_hash: HashRef,
        payload_ref: Option<ArtifactRef>,
    },
}

impl GraphNode {
    pub fn node_id(&self) -> &str {
        match self {
            Self::Component { node_id, .. }
            | Self::Event { node_id, .. }
            | Self::Payload { node_id, .. } => node_id,
        }
    }

    fn validate(&self, run_id: &str) -> Result<(), SchemaError> {
        let (observed, expected) = match self {
            Self::Component {
                node_id,
                component_type,
                component_id,
            } => {
                require(nonblank(component_id), "Componente sin identificador")?;
                (
                    node_id,
                    json!([
                        "r0.8.node.v1",
                        run_id,
                        "component",
                        component_type,
                        component_id
                    ]),
                )
            }
            Self::Event {
                node_id,
                event_id,
                timestamp_utc,
                component_id,
                payload_hash,
                attributes,
                error,
                ..
            } => {
                require(
                    nonblank(event_id) && nonblank(component_id),
                    "Evento sin identificador",
                )?;
                let instant = DateTime::parse_from_rfc3339(timestamp_utc)
                    .map_err(|_| SchemaError::Invalid("Timestamp de evento no válido"))?;
                require(
                    instant.offset().local_minus_utc() == 0,
                    "El timestamp del evento debe estar normalizado a UTC",
                )?;
                payload_hash.validate()?;
                check_observable(&Value::Object(attributes.clone()))?;
                if let Some(error) = error {
                    error.validate()?;
                }
                (node_id, json!(["r0.8.node.v1", run_id, "event", event_id]))
            }
            Self::Payload {
                node_id,
                payload_hash,
                payload_ref,
            } => {
                payload_hash.validate()?;
                if let Some(reference) = payload_ref {
                    reference.validate()?;
                    require(
                        reference.hash == *payload_hash,
                        "Referencia de payload inconsistente",
                    )?;
                }
                (
                    node_id,
                    json!(["r0.8.node.v1", run_id, "payload", payload_hash.value]),
                )
            }
        };
        require(is_digest(observed), "Identidad de nodo no canónica")?;
        require(
            observed.as_str() == hash_parts(expected)?.as_str(),
            "Identidad SHA-256 de nodo incorrecta",
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphEdge {
    pub edge_id: String,
    pub edge_kind: EdgeKind,
    pub source_node_id: String,
    pub target_node_id: String,
}

impl GraphEdge {
    fn validate(&self) -> Result<(), SchemaError> {
        require(
            is_digest(&self.edge_id)
                && is_digest(&self.source_node_id)
                && is_digest(&self.target_node_id)
                && self.source_node_id != self.target_node_id,
            "Identidad o extremos de arista no válidos",
        )?;
        let expected = hash_parts(json!([
            "r0.8.edge.v1",
            self.edge_kind.as_str(),
            self.source_node_id,
            self.target_node_id,
        ]))?;
        require(
            self.edge_id == expected,
            "Identidad SHA-256 de arista incorrecta",
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProvenanceGraph {
    pub schema_version: String,
    pub run_id: String,
    pub app_id: AppId,
    pub case_id: String,
    pub condition_id: String,
    pub repeat_index: u64,
    pub system_version_id: String,
    pub trace_hash: Option<HashRef>,
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
    pub graph_hash: String,
}

impl ProvenanceGraph {
    /// Verifica schema, identidad y digest, no realiza todavía validación DAG.
    pub fn validate(&self) -> Result<(), SchemaError> {
        require(
            self.schema_version == "provenance-graph-v1",
            "Versión de grafo no admitida",
        )?;
        require(
            nonblank(&self.run_id)
                && nonblank(&self.case_id)
                && nonblank(&self.condition_id)
                && nonblank(&self.system_version_id),
            "Identidad de ejecución incompleta",
        )?;
        if let Some(trace) = &self.trace_hash {
            trace.validate()?;
        }
        let mut seen_nodes: HashSet<&str> = HashSet::new();
        let mut previous_node: Option<&str> = None;
        for node in &self.nodes {
            node.validate(&self.run_id)?;
            let id = node.node_id();
            require(seen_nodes.insert(id), "Nodo duplicado")?;
            if let Some(previous) = previous_node {
                require(previous < id, "Orden de nodos no canónico")?;
            }
            previous_node = Some(id);
        }
        let mut seen_edges: HashSet<&str> = HashSet::new();
        let mut previous_edge: Option<&str> = None;
        for edge in &self.edges {
            edge.validate()?;
            require(seen_edges.insert(&edge.edge_id), "Arista duplicada")?;
            if let Some(previous) = previous_edge {
                require(
                    previous < edge.edge_id.as_str(),
                    "Orden de aristas no canónico",
                )?;
            }
            previous_edge = Some(&edge.edge_id);
        }
        require(
            is_digest(&self.graph_hash) && self.graph_hash == hash_without(self, "graph_hash")?,
            "Digest del grafo incorrecto",
        )
    }
}

pub type SemanticKey = Vec<String>;

fn validate_semantic_key(key: &[String]) -> Result<(), SchemaError> {
    require(
        !key.is_empty() && key.iter().all(|part| nonblank(part)),
        "Clave semántica vacía",
    )?;
    let allowed = match key {
        [kind, component_type, _] if kind == "component" => {
            serde_json::from_value::<ComponentType>(Value::String(component_type.clone())).is_ok()
        }
        [kind, component_type, _, event_type] if kind == "event" => {
            serde_json::from_value::<ComponentType>(Value::String(component_type.clone())).is_ok()
                && serde_json::from_value::<EventType>(Value::String(event_type.clone())).is_ok()
        }
        [kind, hash] if kind == "payload" => is_digest(hash),
        _ => false,
    };
    require(allowed, "Clave semántica no admitida")
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NodeChanged {
    pub key: SemanticKey,
    pub changed_fields: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NodeAmbiguous {
    pub key: SemanticKey,
    pub baseline_count: u64,
    pub candidate_count: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EdgeChange {
    pub edge_kind: EdgeKind,
    pub source_key: SemanticKey,
    pub target_key: SemanticKey,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Side {
    Baseline,
    Candidate,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EdgeAmbiguous {
    pub edge_kind: EdgeKind,
    pub source_key: SemanticKey,
    pub target_key: SemanticKey,
    pub side: Side,
    pub count: u64,
}

fn validate_edge_keys(
    kind: EdgeKind,
    source: &[String],
    target: &[String],
) -> Result<(), SchemaError> {
    validate_semantic_key(source)?;
    validate_semantic_key(target)?;
    let actual = (source[0].as_str(), target[0].as_str());
    let expected = match kind {
        EdgeKind::Emits => ("component", "event"),
        EdgeKind::ObservedParent => ("event", "event"),
        EdgeKind::Produces => ("event", "payload"),
    };
    require(
        actual == expected,
        "Arista semántica con extremos inválidos",
    )
}

fn check_sorted_unique<T: Serialize>(items: &[T]) -> Result<(), SchemaError> {
    let mut previous: Option<Vec<u8>> = None;
    for item in items {
        let encoded = canonical_json_bytes(&serde_json::to_value(item)?)?;
        if let Some(before) = &previous {
            require(before < &encoded, "Orden de diferencial no canónico")?;
        }
        previous = Some(encoded);
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeltaG {
    pub schema_version: String,
    pub baseline_run_id: String,
    pub candidate_run_id: String,
    pub node_added: Vec<SemanticKey>,
    pub node_removed: Vec<SemanticKey>,
    pub node_unchanged: Vec<SemanticKey>,
    pub node_changed: Vec<NodeChanged>,
    pub node_ambiguous: Vec<NodeAmbiguous>,
    pub edge_added: Vec<EdgeChange>,
    pub edge_removed: Vec<EdgeChange>,
    pub edge_ambiguous: Vec<EdgeAmbiguous>,
    pub delta_hash: String,
}

impl DeltaG {
    /// Valida listas tipadas y huella; el cálculo real del diferencial será R3.
    pub fn validate(&self) -> Result<(), SchemaError> {
        require(
            self.schema_version == "provenance-delta-v1",
            "Versión DeltaG no admitida",
        )?;
        require(
            nonblank(&self.baseline_run_id) && nonblank(&self.candidate_run_id),
            "DeltaG sin identidad de ejecuciones",
        )?;
        for group in [&self.node_added, &self.node_removed, &self.node_unchanged] {
            check_sorted_unique(group)?;
        }
        for key in self
            .node_added
            .iter()
            .chain(&self.node_removed)
            .chain(&self.node_unchanged)
        {
            validate_semantic_key(key)?;
        }
        check_sorted_unique(&self.node_changed)?;
        check_sorted_unique(&self.node_ambiguous)?;
        check_sorted_unique(&self.edge_added)?;
        check_sorted_unique(&self.edge_removed)?;
        check_sorted_unique(&self.edge_ambiguous)?;
        let mut node_keys = HashSet::new();
        for key in self
            .node_added
            .iter()
            .chain(&self.node_removed)
            .chain(&self.node_unchanged)
        {
            require(
                node_keys.insert(key.clone()),
                "Nodo clasificado más de una vez",
            )?;
        }
        for change in &self.node_changed {
            validate_semantic_key(&change.key)?;
            require(
                change.key[0] == "event" && !change.changed_fields.is_empty(),
                "Cambio de nodo no permitido",
            )?;
            require(
                change
                    .changed_fields
                    .iter()
                    .all(|field| matches!(field.as_str(), "payload_hash" | "attributes" | "error"))
                    && change.changed_fields.windows(2).all(|p| p[0] < p[1]),
                "Campos de cambio no canónicos",
            )?;
            require(
                node_keys.insert(change.key.clone()),
                "Nodo clasificado más de una vez",
            )?;
        }
        for group in &self.node_ambiguous {
            validate_semantic_key(&group.key)?;
            require(
                group.key[0] == "event" && group.baseline_count.max(group.candidate_count) > 1,
                "Grupo ambiguo inválido",
            )?;
            require(
                node_keys.insert(group.key.clone()),
                "Nodo clasificado más de una vez",
            )?;
        }
        let mut removed = HashSet::new();
        for edge in &self.edge_removed {
            validate_edge_keys(edge.edge_kind, &edge.source_key, &edge.target_key)?;
            removed.insert(canonical_json_bytes(&serde_json::to_value(edge)?)?);
        }
        for edge in &self.edge_added {
            validate_edge_keys(edge.edge_kind, &edge.source_key, &edge.target_key)?;
            require(
                !removed.contains(&canonical_json_bytes(&serde_json::to_value(edge)?)?),
                "Arista añadida y retirada simultáneamente",
            )?;
        }
        for edge in &self.edge_ambiguous {
            validate_edge_keys(edge.edge_kind, &edge.source_key, &edge.target_key)?;
            require(edge.count > 0, "Arista ambigua sin multiplicidad")?;
        }
        require(
            is_digest(&self.delta_hash) && self.delta_hash == hash_without(self, "delta_hash")?,
            "Digest de DeltaG incorrecto",
        )
    }
}

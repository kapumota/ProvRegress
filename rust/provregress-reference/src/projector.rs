//! Proyección P2 determinista de EventEnvelope a ProvenanceGraph.

use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::error::Error;
use std::fmt;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};

use crate::canonical::canonical_hash;
use crate::schema::{
    AppId, ArtifactRef, ComponentType, EdgeKind, EventError, EventType, GraphEdge, GraphNode,
    HashRef, ProvenanceGraph, SchemaError,
};

#[derive(Debug)]
pub enum ProjectionError {
    Invalid(&'static str),
    Schema(SchemaError),
    Json(serde_json::Error),
    Graph(GraphValidationError),
}

impl fmt::Display for ProjectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(f, "{message}"),
            Self::Schema(error) => write!(f, "{error}"),
            Self::Json(error) => write!(f, "JSON inválido: {error}"),
            Self::Graph(error) => write!(f, "{error}"),
        }
    }
}

impl Error for ProjectionError {}

impl From<SchemaError> for ProjectionError {
    fn from(value: SchemaError) -> Self {
        Self::Schema(value)
    }
}

impl From<serde_json::Error> for ProjectionError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphValidationError(pub String);

impl fmt::Display for GraphValidationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl Error for GraphValidationError {}

fn invalid_graph(message: &str) -> GraphValidationError {
    GraphValidationError(message.to_owned())
}

/// Forma de entrada de R0.7, con claves cerradas y sin información de mutación.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EventEnvelope {
    pub schema_version: String,
    pub run_id: String,
    pub event_id: String,
    pub sequence: u64,
    pub timestamp_utc: String,
    pub app_id: AppId,
    pub system_version_id: String,
    pub case_id: String,
    pub condition_id: String,
    pub repeat_index: u64,
    pub event_type: EventType,
    pub component_type: ComponentType,
    pub component_id: String,
    pub parent_event_ids: Vec<String>,
    pub payload_hash: HashRef,
    pub payload_ref: Option<ArtifactRef>,
    pub attributes: Map<String, Value>,
    pub error: Option<EventError>,
}

fn nonblank(value: &str) -> bool {
    !value.trim().is_empty()
}

fn check_observable(value: &Value) -> Result<(), ProjectionError> {
    match value {
        Value::Object(fields) => {
            for (key, item) in fields {
                if matches!(
                    key.as_str(),
                    "mutation_id" | "operator_id" | "target_component_id" | "severity"
                ) {
                    return Err(ProjectionError::Invalid("Etiqueta experimental reservada"));
                }
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

/// Convierte instantes con zona horaria a UTC en el formato JSON de Pydantic.
/// Rechaza precisión superior a microsegundos en lugar de redondear sin aviso.
fn canonical_utc(value: &str) -> Result<String, ProjectionError> {
    let parsed = DateTime::parse_from_rfc3339(value)
        .map_err(|_| ProjectionError::Invalid("El timestamp requiere zona horaria"))?;
    let utc = parsed.with_timezone(&Utc);
    let nanos = utc.timestamp_subsec_nanos();
    if nanos % 1000 != 0 {
        return Err(ProjectionError::Invalid(
            "Precisión UTC superior a microsegundos",
        ));
    }
    let seconds = utc.format("%Y-%m-%dT%H:%M:%S").to_string();
    if nanos == 0 {
        Ok(format!("{seconds}Z"))
    } else {
        Ok(format!("{seconds}.{:06}Z", nanos / 1000))
    }
}

impl EventEnvelope {
    /// Valida estructura P1 además de las restricciones propias de serde.
    pub fn validate(&self) -> Result<(), ProjectionError> {
        if self.schema_version != "pilot-event-v1"
            || !nonblank(&self.run_id)
            || !nonblank(&self.event_id)
            || !nonblank(&self.system_version_id)
            || !nonblank(&self.case_id)
            || !nonblank(&self.condition_id)
            || !nonblank(&self.component_id)
        {
            return Err(ProjectionError::Invalid(
                "Identidad o versión de evento inválida",
            ));
        }
        canonical_utc(&self.timestamp_utc)?;
        self.payload_hash.validate()?;
        if let Some(reference) = &self.payload_ref {
            reference.validate()?;
            if reference.hash != self.payload_hash {
                return Err(ProjectionError::Invalid(
                    "Referencia de payload inconsistente",
                ));
            }
        }
        check_observable(&Value::Object(self.attributes.clone()))?;
        if let Some(error) = &self.error {
            if !nonblank(&error.category) || !nonblank(&error.message) {
                return Err(ProjectionError::Invalid("Error observable incompleto"));
            }
            check_observable(&Value::Object(error.details.clone()))?;
        }
        let mut parents = HashSet::new();
        for parent in &self.parent_event_ids {
            if !nonblank(parent) || parent == &self.event_id || !parents.insert(parent) {
                return Err(ProjectionError::Invalid("Padres duplicados o inválidos"));
            }
        }
        Ok(())
    }
}

fn digest(parts: Value) -> Result<String, ProjectionError> {
    Ok(canonical_hash(&parts)?)
}

fn edge(kind: EdgeKind, source: &str, target: &str) -> Result<GraphEdge, ProjectionError> {
    let edge_id = digest(json!(["r0.8.edge.v1", kind, source, target]))?;
    Ok(GraphEdge {
        edge_id,
        edge_kind: kind,
        source_node_id: source.to_owned(),
        target_node_id: target.to_owned(),
    })
}

/// Convierte una traza P1 validada a un grafo sin inventar relaciones.
/// No genera trace_hash: no recibe los bytes originales del JSONL.
pub fn project_trace(events: &[EventEnvelope]) -> Result<ProvenanceGraph, ProjectionError> {
    if events.is_empty() {
        return Err(ProjectionError::Invalid("Se requiere una traza no vacía"));
    }
    let first = &events[0];
    let mut known_events = HashSet::new();
    for (position, event) in events.iter().enumerate() {
        event.validate()?;
        if event.sequence != position as u64 {
            return Err(ProjectionError::Invalid("Secuencia no contigua"));
        }
        if event.run_id != first.run_id
            || event.app_id != first.app_id
            || event.case_id != first.case_id
            || event.condition_id != first.condition_id
            || event.repeat_index != first.repeat_index
            || event.system_version_id != first.system_version_id
        {
            return Err(ProjectionError::Invalid(
                "Se mezclaron identidades de ejecución",
            ));
        }
        if !event
            .parent_event_ids
            .iter()
            .all(|parent| known_events.contains(parent.as_str()))
        {
            return Err(ProjectionError::Invalid("Padre ausente o futuro"));
        }
        if !known_events.insert(event.event_id.as_str()) {
            return Err(ProjectionError::Invalid("Evento duplicado"));
        }
    }

    let mut nodes: BTreeMap<String, GraphNode> = BTreeMap::new();
    let mut edges: BTreeMap<String, GraphEdge> = BTreeMap::new();
    let mut event_ids: HashMap<&str, String> = HashMap::new();
    for event in events {
        let component_id = digest(json!([
            "r0.8.node.v1",
            event.run_id,
            "component",
            event.component_type,
            event.component_id
        ]))?;
        let event_id = digest(json!([
            "r0.8.node.v1",
            event.run_id,
            "event",
            event.event_id
        ]))?;
        let payload_id = digest(json!([
            "r0.8.node.v1",
            event.run_id,
            "payload",
            event.payload_hash.value
        ]))?;
        nodes
            .entry(component_id.clone())
            .or_insert_with(|| GraphNode::Component {
                node_id: component_id.clone(),
                component_type: event.component_type,
                component_id: event.component_id.clone(),
            });
        let previous_event = nodes.insert(
            event_id.clone(),
            GraphNode::Event {
                node_id: event_id.clone(),
                event_id: event.event_id.clone(),
                sequence: event.sequence,
                timestamp_utc: canonical_utc(&event.timestamp_utc)?,
                event_type: event.event_type,
                component_type: event.component_type,
                component_id: event.component_id.clone(),
                payload_hash: event.payload_hash.clone(),
                attributes: event.attributes.clone(),
                error: event.error.clone(),
            },
        );
        if previous_event.is_some() {
            return Err(ProjectionError::Invalid(
                "Colisión entre identidades canónicas",
            ));
        }
        match nodes.get(&payload_id) {
            Some(GraphNode::Payload { payload_ref, .. }) if payload_ref == &event.payload_ref => {}
            Some(_) => {
                return Err(ProjectionError::Invalid(
                    "Referencias incompatibles para payload compartido",
                ))
            }
            None => {
                let _ = nodes.insert(
                    payload_id.clone(),
                    GraphNode::Payload {
                        node_id: payload_id.clone(),
                        payload_hash: event.payload_hash.clone(),
                        payload_ref: event.payload_ref.clone(),
                    },
                );
            }
        }
        for relation in [
            edge(EdgeKind::Emits, &component_id, &event_id)?,
            edge(EdgeKind::Produces, &event_id, &payload_id)?,
        ] {
            let _ = edges.insert(relation.edge_id.clone(), relation);
        }
        for parent in &event.parent_event_ids {
            let source = event_ids
                .get(parent.as_str())
                .ok_or(ProjectionError::Invalid("Padre no proyectado"))?;
            let relation = edge(EdgeKind::ObservedParent, source, &event_id)?;
            let _ = edges.insert(relation.edge_id.clone(), relation);
        }
        let _ = event_ids.insert(&event.event_id, event_id);
    }

    let mut graph = ProvenanceGraph {
        schema_version: "provenance-graph-v1".to_owned(),
        run_id: first.run_id.clone(),
        app_id: first.app_id,
        case_id: first.case_id.clone(),
        condition_id: first.condition_id.clone(),
        repeat_index: first.repeat_index,
        system_version_id: first.system_version_id.clone(),
        trace_hash: None,
        nodes: nodes.into_values().collect(),
        edges: edges.into_values().collect(),
        graph_hash: String::new(),
    };
    let mut encoded = serde_json::to_value(&graph)?;
    encoded
        .as_object_mut()
        .ok_or(ProjectionError::Invalid("Grafo JSON no es un objeto"))?
        .remove("graph_hash");
    graph.graph_hash = canonical_hash(&encoded)?;
    validate_dag(&graph).map_err(ProjectionError::Graph)?;
    Ok(graph)
}

/// Valida el DAG de manera independiente, sin confiar en el constructor.
pub fn validate_dag(graph: &ProvenanceGraph) -> Result<(), GraphValidationError> {
    graph
        .validate()
        .map_err(|e| invalid_graph(&e.to_string()))?;
    let nodes: HashMap<_, _> = graph
        .nodes
        .iter()
        .map(|node| (node.node_id(), node))
        .collect();
    let mut successors: HashMap<&str, Vec<&str>> =
        nodes.keys().map(|id| (*id, Vec::new())).collect();
    let mut indegree: HashMap<&str, usize> = nodes.keys().map(|id| (*id, 0)).collect();
    let mut incident = HashSet::new();
    let mut emits: HashMap<&str, usize> = HashMap::new();
    let mut produces: HashMap<&str, usize> = HashMap::new();
    let mut relationships = HashSet::new();
    for relation in &graph.edges {
        let source = nodes
            .get(relation.source_node_id.as_str())
            .ok_or_else(|| invalid_graph("Arista con origen inexistente"))?;
        let target = nodes
            .get(relation.target_node_id.as_str())
            .ok_or_else(|| invalid_graph("Arista con destino inexistente"))?;
        if !relationships.insert((
            relation.edge_kind as u8,
            relation.source_node_id.as_str(),
            relation.target_node_id.as_str(),
        )) {
            return Err(invalid_graph("Relación duplicada"));
        }
        let typed = match (relation.edge_kind, *source, *target) {
            (
                EdgeKind::Emits,
                GraphNode::Component {
                    component_type: a,
                    component_id: b,
                    ..
                },
                GraphNode::Event {
                    component_type: c,
                    component_id: d,
                    ..
                },
            ) => {
                if a != c || b != d {
                    return Err(invalid_graph("Componente emisor incorrecto"));
                }
                *emits.entry(target.node_id()).or_insert(0) += 1;
                true
            }
            (
                EdgeKind::Produces,
                GraphNode::Event {
                    payload_hash: a, ..
                },
                GraphNode::Payload {
                    payload_hash: b, ..
                },
            ) => {
                if a != b {
                    return Err(invalid_graph("Digest de producción inconsistente"));
                }
                *produces.entry(source.node_id()).or_insert(0) += 1;
                true
            }
            (EdgeKind::ObservedParent, GraphNode::Event { .. }, GraphNode::Event { .. }) => true,
            _ => false,
        };
        if !typed {
            return Err(invalid_graph("Arista con extremos tipados incorrectos"));
        }
        successors
            .get_mut(relation.source_node_id.as_str())
            .unwrap()
            .push(relation.target_node_id.as_str());
        *indegree.get_mut(relation.target_node_id.as_str()).unwrap() += 1;
        incident.insert(relation.source_node_id.as_str());
        incident.insert(relation.target_node_id.as_str());
    }

    // Kahn detecta ciclos incluso cuando el objeto tiene IDs y digest coherentes.
    let mut available: VecDeque<_> = indegree
        .iter()
        .filter_map(|(id, degree)| (*degree == 0).then_some(*id))
        .collect();
    let mut visited = 0;
    while let Some(node_id) = available.pop_front() {
        visited += 1;
        for child in &successors[node_id] {
            let count = indegree.get_mut(child).unwrap();
            *count -= 1;
            if *count == 0 {
                available.push_back(child);
            }
        }
    }
    if visited != nodes.len() {
        return Err(invalid_graph("El grafo contiene un ciclo dirigido"));
    }

    let mut sequences = Vec::new();
    for node in &graph.nodes {
        if let GraphNode::Event {
            sequence, node_id, ..
        } = node
        {
            sequences.push(*sequence);
            if emits.get(node_id.as_str()) != Some(&1) || produces.get(node_id.as_str()) != Some(&1)
            {
                return Err(invalid_graph(
                    "El evento necesita una emisión y una producción",
                ));
            }
        }
    }
    sequences.sort_unstable();
    if sequences.is_empty()
        || sequences
            .iter()
            .enumerate()
            .any(|(i, seq)| *seq != i as u64)
    {
        return Err(invalid_graph("Secuencia del grafo no contigua"));
    }
    for relation in &graph.edges {
        if relation.edge_kind == EdgeKind::ObservedParent {
            let source = nodes[relation.source_node_id.as_str()];
            let target = nodes[relation.target_node_id.as_str()];
            if let (
                GraphNode::Event {
                    sequence: before, ..
                },
                GraphNode::Event {
                    sequence: after, ..
                },
            ) = (source, target)
            {
                if before >= after {
                    return Err(invalid_graph("Padre observado posterior al hijo"));
                }
            }
        }
    }
    if incident.len() != nodes.len() {
        return Err(invalid_graph("Componente o payload huérfano"));
    }
    Ok(())
}

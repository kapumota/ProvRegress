//! Referencia Rust P2 con proyección y validación DAG, sin comparar grafos.

pub mod canonical;
pub mod projector;
pub mod schema;

pub use canonical::{canonical_hash, canonical_json_bytes, sha256_hex};
pub use schema::{
    AppId, ArtifactRef, ComponentType, DeltaG, EdgeAmbiguous, EdgeChange, EdgeKind, EventError,
    EventType, GraphEdge, GraphNode, HashRef, NodeAmbiguous, NodeChanged, ProvenanceGraph,
    SchemaError,
};

pub use projector::{
    project_trace, validate_dag, EventEnvelope, GraphValidationError, ProjectionError,
};

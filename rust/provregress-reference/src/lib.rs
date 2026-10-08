//! Contratos tipados de la referencia Rust R0.9, sin ejecutar proyección P2/P3.

pub mod canonical;
pub mod schema;

pub use canonical::{canonical_hash, canonical_json_bytes, sha256_hex};
pub use schema::{
    AppId, ArtifactRef, ComponentType, DeltaG, EdgeAmbiguous, EdgeChange, EdgeKind, EventError,
    EventType, GraphEdge, GraphNode, HashRef, NodeAmbiguous, NodeChanged, ProvenanceGraph,
    SchemaError,
};

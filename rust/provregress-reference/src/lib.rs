//! Referencia Rust P2/P3 con proyección, alineamiento y DeltaG observables.

pub mod alignment;
pub mod canonical;
pub mod diff;
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

pub use alignment::{
    align_graphs, semantic_key, AlignedNode, AlignmentError, AmbiguousGroup, GraphAlignment,
    UnmatchedNode,
};
pub use diff::{diff_graphs, GraphDiffError};

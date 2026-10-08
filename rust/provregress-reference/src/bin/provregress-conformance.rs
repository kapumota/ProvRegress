//! Adaptador de conformidad, entrada JSON por stdin, salida JSON canónica por stdout.
//! Se utiliza en tests; no es una interfaz pública ni un motor experimental.

use std::error::Error;
use std::io::{self, Read, Write};

use provregress_reference::{
    canonical_json_bytes, diff_graphs, project_trace, validate_dag, EventEnvelope, ProvenanceGraph,
};
use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Canonical {
        value: Value,
    },
    Project {
        events: Vec<EventEnvelope>,
    },
    Diff {
        baseline: Vec<EventEnvelope>,
        candidate: Vec<EventEnvelope>,
    },
    ValidateDag {
        graph: ProvenanceGraph,
    },
}

fn execute() -> Result<(), Box<dyn Error>> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let request: Request = serde_json::from_str(&input)?;
    let output = match request {
        Request::Canonical { value } => value,
        Request::Project { events } => serde_json::to_value(project_trace(&events)?)?,
        Request::Diff {
            baseline,
            candidate,
        } => {
            let left = project_trace(&baseline)?;
            let right = project_trace(&candidate)?;
            serde_json::to_value(diff_graphs(&left, &right)?)?
        }
        Request::ValidateDag { graph } => {
            validate_dag(&graph)?;
            serde_json::json!({"valid": true})
        }
    };
    let encoded = canonical_json_bytes(&output)?;
    io::stdout().write_all(&encoded)?;
    io::stdout().write_all(b"\n")?;
    Ok(())
}

fn main() {
    if let Err(error) = execute() {
        // El error no debe generar un JSON parcial en stdout.
        eprintln!("Conformidad rechazada: {error}");
        std::process::exit(2);
    }
}

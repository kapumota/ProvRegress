"""Comprueba el dictamen R0.10-F3 sin elevar evidencia local a freeze v2.

Este script es un gate de integridad y de decisiones metodológicas. No verifica
GitHub en línea ni sustituye la revisión independiente de un conjunto externo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RECORD = Path("research/verification/R0.10-F3-evidence.json")
EXPECTED_I2_COMMIT = "6a503c3f6cd253c3a8f776e41d8ab9d05aa4cfa3"
EXPECTED_CI_URL = "https://github.com/kapumota/ProvRegress/actions/runs/37869140801"
EXPECTED_I2_HASH = "c5d7b0f6128cd391d25acdaf14908d3a10cbfcef6cd1d8f05ca680069f6004fe"
EXPECTED_DECISION = {
    "technical_audit": "closed_with_conditions",
    "provenance_v2_contract": "candidate_not_frozen",
    "rust_reference": "v1_frozen_unchanged",
    "mutation_harness": "experimental_execution_blocked",
    "confirmatory_study": "blocked",
}
REQUIRED_OPEN = frozenset({
    "independent_ground_truth_for_a2_a3",
    "runtime_generated_keys_without_plan_ordinal",
    "external_or_representative_trace_cohort",
    "v2_persistent_sink_and_content_hash_integrity",
    "application_specific_policy_calibration",
    "pilot_ambiguity_and_target_gates_on_external_cohort",
    "fair_comparator_empirical_evaluation",
})
REQUIRED_FILES = frozenset({
    *(f"provregress/provenance_v2/{name}.py" for name in
      ("__init__", "schema", "projector", "comparison", "live_workloads", "pilot_audit")),
    *(f"research/verification/{name}.py" for name in
      ("r010_f2_reference_oracle", "r010_i1_live_runs", "r010_i2_pilot_audit")),
    *(f"tests/fixtures/provenance/{folder}/{name}" for folder in
      ("r0_8", "r0_10", "r0_10_f2") for name in
      ("SHA256SUMS", "inputs.json" if folder == "r0_8" else "cases.json", "expected.json")),
})
FIXTURE_DIRS = ("r0_8", "r0_10", "r0_10_f2")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class AuditReleaseError(ValueError):
    """Un supuesto del cierre de auditoría no se puede verificar."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditReleaseError("El documento contiene claves JSON duplicadas.")
        result[key] = value
    return result


def _load_record(data: bytes) -> dict[str, Any]:
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except AuditReleaseError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise AuditReleaseError("El registro F3 no es JSON válido y único.") from exc
    if not isinstance(result, dict):
        raise AuditReleaseError("El registro F3 debe ser un objeto.")
    return result


def _read_file(root: Path, name: str) -> bytes:
    path = Path(name)
    if (path.is_absolute() or "\\" in name or not name or
            any(part in {"", ".", ".."} for part in name.split("/"))):
        raise AuditReleaseError("Ruta no canónica en la evidencia.")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise AuditReleaseError("No se admiten symlinks en archivos auditados.")
    if not current.is_file():
        raise AuditReleaseError(f"No existe el archivo requerido: {name}")
    return current.read_bytes()


def _verify_sha256sums(root: Path, folder: str) -> None:
    prefix = f"tests/fixtures/provenance/{folder}/"
    raw = _read_file(root, prefix + "SHA256SUMS")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise AuditReleaseError("SHA256SUMS no utiliza UTF-8.") from exc
    expected_names = {"expected.json", "inputs.json" if folder == "r0_8" else "cases.json"}
    seen: set[str] = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([a-z_]+\.json)", line)
        if match is None:
            raise AuditReleaseError("Formato inesperado de SHA256SUMS.")
        digest, filename = match.groups()
        if filename in seen or filename not in expected_names:
            raise AuditReleaseError("SHA256SUMS contiene entradas inesperadas o repetidas.")
        seen.add(filename)
        if hashlib.sha256(_read_file(root, prefix + filename)).hexdigest() != digest:
            raise AuditReleaseError(f"Fixture alterado: {folder}/{filename}")
    if seen != expected_names:
        raise AuditReleaseError("SHA256SUMS no enumera todos los fixtures requeridos.")


def verify_audit_record(root: Path = ROOT, record: Path = RECORD) -> dict[str, Any]:
    """Verifica evidencias fijadas, invariantes v1/v2 y bloqueos restantes."""
    raw = _read_file(root, record.as_posix())
    item = _load_record(raw)
    if set(item) != {"schema_version", "baseline", "decision", "open_requirements",
                     "local_i2_expected", "files_sha256"}:
        raise AuditReleaseError("Campos de F3 inesperados o ausentes.")
    if item["schema_version"] != "r0.10-f3-audit-decision-v1":
        raise AuditReleaseError("Versión de dictamen inesperada.")
    baseline = item["baseline"]
    if baseline != {
        "branch": "r0.10-provenance-v2", "i2_commit": EXPECTED_I2_COMMIT,
        "i2_ci_url": EXPECTED_CI_URL,
        "i2_ci_observation": "success_verified_by_reviewer",
    }:
        raise AuditReleaseError("El dictamen no apunta al baseline I2 aprobado.")
    if item["decision"] != EXPECTED_DECISION:
        raise AuditReleaseError("La evidencia no autoriza un freeze v2 ni experimentos R1.0.")
    open_items = item["open_requirements"]
    if (not isinstance(open_items, dict) or set(open_items) != REQUIRED_OPEN
            or any(v is not False for v in open_items.values())):
        raise AuditReleaseError("No se pueden cerrar requisitos sin evidencia nueva auditada.")
    expected = item["local_i2_expected"]
    if expected != {
        "audit_hash": EXPECTED_I2_HASH,
        "repeats": 3, "positive_pairs_per_app": 18,
        "negative_rekey_rejections": 6,
        "max_ambiguity_rate": "0.05", "minimum_target_coverage": "1",
        "maximum_false_pairs": 0, "maximum_missed_pairs": 0,
    }:
        raise AuditReleaseError("Los gates locales I2 cambiaron después de su evaluación.")
    files = item["files_sha256"]
    if not isinstance(files, dict) or set(files) != REQUIRED_FILES:
        raise AuditReleaseError("La evidencia de integridad no incluye todos los archivos.")
    for name, digest in sorted(files.items()):
        if not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            raise AuditReleaseError("SHA-256 inválido en el índice F3.")
        if hashlib.sha256(_read_file(root, name)).hexdigest() != digest:
            raise AuditReleaseError(f"Deriva de contenido respecto de I2: {name}")
    for folder in FIXTURE_DIRS:
        _verify_sha256sums(root, folder)
    return {
        "schema_version": item["schema_version"],
        "baseline_i2_commit": EXPECTED_I2_COMMIT,
        "technical_audit": EXPECTED_DECISION["technical_audit"],
        "provenance_v2_contract": EXPECTED_DECISION["provenance_v2_contract"],
        "mutation_harness": EXPECTED_DECISION["mutation_harness"],
        "verified_files": len(files),
        "open_requirements": len(open_items),
        "ci_observation": "registrada; comprobar estado remoto independientemente",
    }


def verify_local_i2() -> dict[str, Any]:
    """Vuelve a ejecutar I2, sin elegir repeticiones ni conservar solo aprobados."""
    # Admite tanto `python -m research.verification...` como ejecución
    # directa del archivo desde la raíz del repositorio.
    if __package__:
        from .r010_i2_pilot_audit import audit_i2_local
    else:
        from r010_i2_pilot_audit import audit_i2_local

    result = audit_i2_local(repeats=3)
    if (result.get("schema_version") != "r0.10-i2-audit-v1"
            or result.get("status") != "pass_local_instrumentation"
            or result.get("audit_hash") != EXPECTED_I2_HASH
            or result.get("repeats") != 3
            or result.get("negative_rekey_rejections") != 6):
        raise AuditReleaseError("El resultado I2 ya no coincide con la evidencia F3.")
    applications = result.get("applications")
    if not isinstance(applications, dict) or set(applications) != {"a2_rag", "a3_tools"}:
        raise AuditReleaseError("El conjunto de aplicaciones I2 es incompleto.")
    for app, values in applications.items():
        if not isinstance(values, dict) or any((
            values.get("pairs") != 18,
            values.get("branched_pairs") != 18,
            values.get("false_pairs") != 0,
            values.get("missed_pairs") != 0,
            values.get("ambiguity_rate") != "0",
            values.get("target_coverage") != "1",
        )):
            raise AuditReleaseError(f"I2 no cumple todos los requisitos en {app}.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="R0.10-F3, decisión y auditoría de integridad")
    parser.add_argument("--rerun-i2", action="store_true",
                        help="Repetir íntegramente los escenarios locales I2")
    args = parser.parse_args()
    result = verify_audit_record()
    if args.rerun_i2:
        verify_local_i2()
        result["local_i2"] = "pass_reexecuted"
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

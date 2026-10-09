"""Auditoría I2 de identidades v2 con testigos externos al diferencial.

Los testigos se usan exclusivamente en este canal privilegiado. No se importan
por P2/P3 y nunca participan en la construcción de GraphV2 o DeltaV2.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from provregress.provenance_v2.comparison import (
    assert_pilot_alignment_v2, compare_graphs_v2,
    sequential_baseline_view_v2, topology_profile_v2,
)
from provregress.provenance_v2.live_workloads import ExecutedRun
from provregress.provenance_v2.projector import project_trace_v2
from provregress.provenance_v2.schema import ComparisonPolicyV2, V2Error, canonical_v2
from provregress.schema.common import AppId
from provregress.storage.hashing import sha256_hex


Key = tuple[str, ...]
MAX_AMBIGUITY_BY_APP = {AppId.A2: Decimal("0.05"), AppId.A3: Decimal("0.05")}


@dataclass(frozen=True, slots=True)
class PairAuditV2:
    """Dictamen de una pareja, exclusivo de auditoría, no evento observable."""

    app_id: AppId
    scenario: str
    baseline_events: int
    candidate_events: int
    true_pairs: int
    false_pairs: int
    missed_pairs: int
    ambiguous_members: int
    target_count: int
    target_covered: int
    functional_false_positives: int
    functional_false_negatives: int
    added_false_positives: int
    added_false_negatives: int
    branched_both: bool
    equivalent_sequential_input: bool
    delta_hash: str
    target_keys: tuple[Key, ...]
    target_logical_ids: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ambiguity_rate(self) -> Decimal:
        return Decimal(self.ambiguous_members) / Decimal(self.baseline_events + self.candidate_events)

    @property
    def passed(self) -> bool:
        return (
            not self.errors
            and self.false_pairs == 0 and self.missed_pairs == 0
            and self.functional_false_positives == 0
            and self.functional_false_negatives == 0
            and self.added_false_positives == 0
            and self.added_false_negatives == 0
            and self.target_count > 0 and self.target_count == self.target_covered
            and self.branched_both and self.equivalent_sequential_input
            and self.ambiguity_rate <= MAX_AMBIGUITY_BY_APP[self.app_id]
        )

    def privileged_dict(self) -> dict[str, Any]:
        """Incluye identidades de objetivo: nunca escribir en observable/."""
        return {**self.public_dict(), "target_keys": [list(x) for x in self.target_keys],
                "target_logical_ids": list(self.target_logical_ids),
                "errors": list(self.errors)}

    def public_dict(self) -> dict[str, Any]:
        """Solo estadísticas, sin logical_id, invocation_key ni testigos."""
        return {
            "app_id": self.app_id.value, "scenario": self.scenario,
            "baseline_events": self.baseline_events, "candidate_events": self.candidate_events,
            "true_pairs": self.true_pairs, "false_pairs": self.false_pairs,
            "missed_pairs": self.missed_pairs, "ambiguous_members": self.ambiguous_members,
            "ambiguity_rate": format(self.ambiguity_rate, "f"),
            "target_count": self.target_count, "target_covered": self.target_covered,
            "functional_false_positives": self.functional_false_positives,
            "functional_false_negatives": self.functional_false_negatives,
            "added_false_positives": self.added_false_positives,
            "added_false_negatives": self.added_false_negatives,
            "branched_both": self.branched_both,
            "equivalent_sequential_input": self.equivalent_sequential_input,
            "passed": self.passed,
        }


def _witness_index(run: ExecutedRun) -> tuple[dict[str, Key], dict[Key, str]]:
    """Reconstruye identidades desde el plan externo; falla ante testigos incompletos."""
    if not isinstance(run, ExecutedRun):
        raise V2Error("Se requiere ExecutedRun verificado.")
    event_by_id = {x.event_id: x for x in run.events}
    if len(event_by_id) != len(run.events) or len(run.witness) != len(run.events):
        raise V2Error("Testigos incompletos o IDs de evento duplicados.")
    logical_to_key: dict[str, Key] = {}
    key_to_logical: dict[Key, str] = {}
    for witness in run.witness:
        if witness.event_id not in event_by_id or not witness.logical_id.strip():
            raise V2Error("Testigo sin operación observable válida.")
        key = tuple(event_by_id[witness.event_id].key)
        if witness.logical_id in logical_to_key or key in key_to_logical:
            raise V2Error("Testigo no biyectivo, clave repetida o lógico duplicado.")
        logical_to_key[witness.logical_id] = key
        key_to_logical[key] = witness.logical_id
    if Counter(run.completed_calls) != Counter(logical_to_key.keys()):
        raise V2Error("El historial de funciones ejecutadas no coincide con el testigo.")
    return logical_to_key, key_to_logical


def _equivalent_sequential_input(graph: Any, run: ExecutedRun) -> bool:
    """Conserva todos los padres y señales del grafo en el baseline fuerte."""
    rows = sequential_baseline_view_v2(graph, include_parent_relations=True)
    actual = {x.event_id: x for x in run.events}
    if len(rows) != len(actual):
        return False
    for row in rows:
        event = actual.get(row["event_id"])
        if event is None or (
            tuple(row["semantic_key"]) != tuple(event.key)
            or sorted(row["parent_event_ids"]) != sorted(event.parent_event_ids)
            or canonical_v2(row["semantic_values"]) != canonical_v2(event.semantic_values)
            or canonical_v2(row["attributes"]) != canonical_v2(event.attributes)
        ):
            return False
    return True


def audit_execution_pair_v2(
    baseline: ExecutedRun, candidate: ExecutedRun, policy: ComparisonPolicyV2,
    *, scenario: str, target_logical_ids: tuple[str, ...],
    expected_changed_logical_ids: tuple[str, ...] = (),
    expected_added_logical_ids: tuple[str, ...] = (),
) -> PairAuditV2:
    """Mide errores de correspondencia usando el testigo, nunca el hash de payload.

    No se detiene ante rekey: el dictamen registra los emparejamientos falsos,
    que el gate rechaza. Sí falla inmediatamente si el testigo es inconsistente.
    """
    if not isinstance(policy, ComparisonPolicyV2) or policy.app_id not in MAX_AMBIGUITY_BY_APP:
        raise V2Error("I2 requiere una política para A2 o A3.")
    if not isinstance(scenario, str) or not scenario.strip():
        raise V2Error("Escenario de auditoría vacío.")
    for name, value in (("target", target_logical_ids),
                        ("changed", expected_changed_logical_ids),
                        ("added", expected_added_logical_ids)):
        if type(value) is not tuple or len(set(value)) != len(value) or any(
            not isinstance(x, str) or not x.strip() for x in value
        ):
            raise V2Error(f"Identidades declaradas inválidas: {name}.")
    if not target_logical_ids:
        raise V2Error("La auditoría exige objetivos declarados antes de ejecutar.")

    before_by_id, before_by_key = _witness_index(baseline)
    after_by_id, after_by_key = _witness_index(candidate)
    before = project_trace_v2(baseline.events)
    after = project_trace_v2(candidate.events)
    delta = compare_graphs_v2(before, after, policy)
    common_keys = before_by_key.keys() & after_by_key.keys()
    observed_pairs = {(before_by_key[k], after_by_key[k]) for k in common_keys}
    true_pairs = sum(a == b for a, b in observed_pairs)
    false_pairs = len(observed_pairs) - true_pairs
    expected_shared = before_by_id.keys() & after_by_id.keys()
    correctly_paired_ids = {a for a, b in observed_pairs if a == b}
    missed_pairs = len(expected_shared - correctly_paired_ids)

    observed_changed = {before_by_key[tuple(item.key)] for item in delta.changed_events
                        if tuple(item.key) in before_by_key}
    expected_changed = set(expected_changed_logical_ids)
    observed_added = {after_by_key[tuple(key)] for key in delta.added_events
                      if tuple(key) in after_by_key}
    expected_added = set(expected_added_logical_ids)
    assessed = {tuple(k) for k in delta.unchanged_events}
    assessed.update(tuple(x.key) for x in delta.changed_events)
    unambiguous = {k for k in common_keys if before_by_key[k] == after_by_key[k]}
    targets = set(target_logical_ids)
    covered = {logical for logical in targets if logical in before_by_id
               and logical in after_by_id and before_by_id[logical] == after_by_id[logical]
               and before_by_id[logical] in unambiguous and before_by_id[logical] in assessed}
    ambiguity_members = sum(x.baseline_count + x.candidate_count for x in delta.ambiguous_events)
    errors: list[str] = []
    if before.app_id != policy.app_id or after.app_id != policy.app_id:
        raise V2Error("Aplicaciones distintas del protocolo I2.")
    if false_pairs:
        errors.append("Se detectaron pares incorrectos mediante el testigo lógico.")
    if missed_pairs:
        errors.append("Hay operaciones compartidas sin correspondencia correcta.")
    if covered != targets:
        errors.append("Uno o más objetivos no se pueden localizar de forma evaluable.")
    if (Decimal(ambiguity_members) / Decimal(len(before.events) + len(after.events))
            > MAX_AMBIGUITY_BY_APP[policy.app_id]):
        errors.append("Se supera el umbral de ambigüedad por aplicación.")
    try:
        assert_pilot_alignment_v2(
            before, after, delta, policy=policy,
            target_keys=[before_by_id[x] for x in sorted(covered)],
        )
    except V2Error:
        errors.append("El gate v2 de integridad o ambigüedad rechazó la pareja.")
    return PairAuditV2(
        app_id=policy.app_id, scenario=scenario,
        baseline_events=len(before.events), candidate_events=len(after.events),
        true_pairs=true_pairs, false_pairs=false_pairs, missed_pairs=missed_pairs,
        ambiguous_members=ambiguity_members, target_count=len(targets),
        target_covered=len(covered),
        functional_false_positives=len(observed_changed - expected_changed),
        functional_false_negatives=len(expected_changed - observed_changed),
        added_false_positives=len(observed_added - expected_added),
        added_false_negatives=len(expected_added - observed_added),
        branched_both=bool(topology_profile_v2(before)["branched"]
                           and topology_profile_v2(after)["branched"]),
        equivalent_sequential_input=(
            _equivalent_sequential_input(before, baseline)
            and _equivalent_sequential_input(after, candidate)
        ),
        delta_hash=delta.delta_hash,
        target_keys=tuple(sorted(before_by_id[x] for x in covered)),
        target_logical_ids=tuple(sorted(targets)),
        errors=tuple(errors),
    )


def assert_i2_cohort_gate(reports: list[PairAuditV2], *, repeats: int) -> dict[str, Any]:
    """Agrega por aplicación sin esconder fallos en promedios ni en redondeos."""
    required = {"baseline", "insert", "reorder", "noise", "functional", "retry"}
    if type(repeats) is not int or repeats < 1 or not isinstance(reports, list):
        raise V2Error("El tamaño del cohort I2 no es válido.")
    summary: dict[str, Any] = {"schema_version": "r0.10-i2-audit-v1", "repeats": repeats,
                               "applications": {}}
    for app in (AppId.A2, AppId.A3):
        subset = [x for x in reports if x.app_id == app]
        counts = Counter(x.scenario for x in subset)
        if counts != Counter({x: repeats for x in required}):
            raise V2Error("Faltan escenarios obligatorios o existen duplicados en I2.")
        total = sum(x.baseline_events + x.candidate_events for x in subset)
        ambiguous = sum(x.ambiguous_members for x in subset)
        exact_rate = Decimal(ambiguous) / Decimal(total)
        if any(not x.passed for x in subset) or exact_rate > MAX_AMBIGUITY_BY_APP[app]:
            raise V2Error("El cohort no supera el gate de identidad, cobertura o topología.")
        summary["applications"][app.value] = {
            "pairs": len(subset), "events": total,
            "ambiguity_rate": format(exact_rate, "f"),
            "false_pairs": sum(x.false_pairs for x in subset),
            "missed_pairs": sum(x.missed_pairs for x in subset),
            "target_coverage": "1", "branched_pairs": len(subset),
        }
    return summary


def audit_digest_v2(value: dict[str, Any]) -> str:
    """Huella de reportes reproducibles; no incorpora tiempos ni hashes de runs."""
    return sha256_hex(canonical_v2(value))

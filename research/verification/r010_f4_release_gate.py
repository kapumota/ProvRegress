"""Verifica la aceptación técnica R0.10-F4, sin declarar un freeze científico.

Este gate verifica integridad versionada, decisiones y, opcionalmente, ejecuta
la cohorte I4. Una referencia a CI remoto no es una consulta de GitHub en vivo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RECORD = Path('research/verification/R0.10-F4-acceptance.json')
RECORD_SHA256 = 'f5ef43bd8138079d0e2b37a0611d3841e9c656b88ed5d70ab1b956e3369b1295'
COHORT_SHA256 = '813970ca018b2249cadf6e050df5809f64302b9d587240628c793435943ac3a3'
SUMMARY_SHA256 = '4241fa7d975270ff4cb00934f8aa77aa1a30cbab43b43e067347dc1a8810c58c'
F3_SHA256 = '583b8fa73e644cd715a814c6ecab7638891bd07bba0502a62724d2507c854666'
HEX64 = re.compile(r'[0-9a-f]{64}\Z')

EXPECTED_DECISION = {
    'technical_baseline': 'accepted_for_nonconfirmatory_development',
    'technical_audit': 'closed_with_conditions',
    'provenance_v2_contract': 'candidate_not_scientifically_frozen',
    'r1_m1_scaffolding': 'permitted_without_experimental_claims',
    'r1_experimental_mutations': 'blocked',
    'confirmatory_study': 'blocked',
    'rust_reference': 'v1_frozen_unchanged',
    'graph_superiority': 'not_demonstrated',
}
EXPECTED_OPEN = {
    'independent_ground_truth_for_a2_a3': 'blocking',
    'runtime_generated_keys_without_plan_ordinal': 'blocking_external_validation',
    'external_or_representative_trace_cohort': 'blocking',
    'v2_persistent_sink_and_content_hash_integrity': 'blocking_integrated_scope',
    'application_specific_policy_calibration': 'blocking',
    'pilot_ambiguity_and_target_gates_on_external_cohort': 'blocking',
    'fair_comparator_empirical_evaluation': 'blocking',
}
EXPECTED_BASELINE = {
    'repository': 'kapumota/ProvRegress',
    'branch': 'main',
    'merge_pr': 4,
    'merge_sha': '94e85677fc612bd47db9dc6747bab785c0e145d2',
    'i4_sha': 'cc506eeca94ccc48fc11efdae618274c7b9c742c',
    'main_ci_url': 'https://github.com/kapumota/ProvRegress/actions/runs/37875343469',
    'main_ci_observation': 'success_verified_during_f4_preparation',
}
EXPECTED_I4 = {
    'protocol_sha256': COHORT_SHA256,
    'summary_sha256': SUMMARY_SHA256,
    'expected_applications': ['a2_rag', 'a3_tools'],
    'total_pairs': 30,
    'pairs_per_application': 15,
    'false_pairs': 0,
    'missed_pairs': 0,
    'minimum_target_coverage': '1',
    'maximum_ambiguity_rate': '0',
    'strong_sequence_parity_pairs': 30,
    'scientific_freeze': 'blocked_pending_external_validation',
    'superiority_over_sequence': 'not_demonstrated',
}
EXPECTED_FILES = frozenset({
    'research/verification/R0.10-F3-evidence.json',
    'research/preregistration/R0.10-F3-final-audit-decision.md',
    'research/preregistration/R0.10-I4-cohort.json',
    'research/preregistration/R0.10-I4-cohort-evaluation.md',
    'research/verification/r010_f3_release_gate.py',
    'research/verification/r010_i4_cohort_eval.py',
    'provregress/provenance_v2/cohort_audit.py',
    'provregress/provenance_v2/dynamic_adapters.py',
    'provregress/provenance_v2/independent_audit.py',
    'provregress/provenance_v2/persistent.py',
    'tests/fixtures/provenance/r0_10_i3/annotations.json',
    'tests/fixtures/provenance/r0_10_i3/SHA256SUMS',
    'tests/provregress/test_provenance_v2_i4_cohort.py',
})


class F4ReleaseError(ValueError):
    """La evidencia del cierre técnico F4 no cumple el contrato."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise F4ReleaseError('Se detectaron claves JSON duplicadas.')
        values[key] = value
    return values


def _read_bytes(root: Path, name: str) -> bytes:
    """Lee únicamente rutas relativas canónicas y archivos regulares sin symlinks."""
    if (not isinstance(name, str) or not name or name.startswith('/') or
            '\\' in name or any(part in ('', '.', '..') for part in name.split('/'))):
        raise F4ReleaseError('Ruta de evidencia no canónica.')
    current = root
    for segment in name.split('/'):
        current = current / segment
        if current.is_symlink():
            raise F4ReleaseError('No se permiten symlinks en la evidencia.')
    if not current.is_file():
        raise F4ReleaseError(f'No existe el archivo requerido: {name}')
    return current.read_bytes()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_f4(root: Path = ROOT, *, check_f3: bool = True) -> dict[str, Any]:
    """Audita el baseline I4 sin atribuir evidencia externa o superioridad."""
    manifest = _read_bytes(root, RECORD.as_posix())
    if _sha256(manifest) != RECORD_SHA256:
        raise F4ReleaseError('El manifiesto F4 difiere del dictamen versionado.')
    try:
        record = json.loads(manifest.decode('utf-8'), object_pairs_hook=_unique_pairs)
    except (UnicodeError, ValueError) as exc:
        raise F4ReleaseError('El manifiesto F4 no es JSON válido y único.') from exc
    if (not isinstance(record, dict) or
            set(record) != {'schema_version', 'baseline', 'decision',
                            'i4_cohort_evidence', 'open_scientific_requirements',
                            'integrity_sha256'}):
        raise F4ReleaseError('El registro F4 tiene campos inesperados o ausentes.')
    if record['schema_version'] != 'r0.10-f4-technical-acceptance-v1':
        raise F4ReleaseError('Versión F4 desconocida.')
    if record['baseline'] != EXPECTED_BASELINE:
        raise F4ReleaseError('El baseline F4 no corresponde al PR integrado.')
    if record['decision'] != EXPECTED_DECISION:
        raise F4ReleaseError('F4 no autoriza un freeze científico ni R1.0 experimental.')
    if record['i4_cohort_evidence'] != EXPECTED_I4:
        raise F4ReleaseError('El resumen I4 difiere del protocolo predeclarado.')
    if record['open_scientific_requirements'] != EXPECTED_OPEN:
        raise F4ReleaseError('Los requisitos científicos no se cierran sin nueva evidencia.')
    files = record['integrity_sha256']
    if not isinstance(files, dict) or set(files) != EXPECTED_FILES:
        raise F4ReleaseError('La cobertura de integridad F4 está incompleta.')
    for path, digest in sorted(files.items()):
        if not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            raise F4ReleaseError('Huella SHA-256 mal formada.')
        if _sha256(_read_bytes(root, path)) != digest:
            raise F4ReleaseError(f'Deriva detectada respecto de I4: {path}')
    if files['research/verification/R0.10-F3-evidence.json'] != F3_SHA256:
        raise F4ReleaseError('El dictamen F3 no corresponde al original.')
    if files['research/preregistration/R0.10-I4-cohort.json'] != COHORT_SHA256:
        raise F4ReleaseError('Se modificó el protocolo de cohorte predeclarado.')
    if check_f3:
        # La evidencia v1 y los tres oráculos preexistentes deben verificarse
        # con el gate publicado, no con una copia alternativa en F4.
        from research.verification.r010_f3_release_gate import verify_audit_record
        try:
            f3 = verify_audit_record(root=root)
        except (ValueError, OSError) as exc:
            raise F4ReleaseError(f'F3 no verificó su evidencia: {exc}') from exc
        if (f3.get('technical_audit') != 'closed_with_conditions' or
                f3.get('provenance_v2_contract') != 'candidate_not_frozen'):
            raise F4ReleaseError('La decisión heredada de F3 no coincide.')
    return {
        'schema_version': record['schema_version'],
        'baseline_merge_sha': EXPECTED_BASELINE['merge_sha'],
        'technical_baseline': EXPECTED_DECISION['technical_baseline'],
        'scientific_freeze': EXPECTED_DECISION['provenance_v2_contract'],
        'r1_m1_scaffolding': EXPECTED_DECISION['r1_m1_scaffolding'],
        'r1_experimental_mutations': EXPECTED_DECISION['r1_experimental_mutations'],
        'graph_superiority': EXPECTED_DECISION['graph_superiority'],
        'open_scientific_gates': len(EXPECTED_OPEN),
        'verified_files': len(files),
        'f3_rechecked': check_f3,
        'remote_ci': 'observacion registrada, no consulta en vivo',
    }


def verify_i4_reexecution(root: Path = ROOT) -> dict[str, Any]:
    """Reejecuta las 30 parejas y compara el resumen con el oráculo previo."""
    from provregress.provenance_v2.cohort_audit import run_cohort

    with tempfile.TemporaryDirectory(prefix='provregress-f4-i4-') as temp:
        report = run_cohort(
            cohort_path=root / 'research/preregistration/R0.10-I4-cohort.json',
            annotations_path=root / 'tests/fixtures/provenance/r0_10_i3/annotations.json',
            output_dir=Path(temp) / 'i4',
        )
    if (report.get('schema_version') != 'r0.10-i4-cohort-report-v1' or
            report.get('cohort_sha256') != COHORT_SHA256 or
            report.get('summary_sha256') != SUMMARY_SHA256 or
            report.get('technical_gate') != 'pass_local_controlled' or
            report.get('pairs') != 30 or
            report.get('scientific_freeze') != 'blocked_pending_external_validation' or
            report.get('superiority_over_sequence') != 'not_demonstrated'):
        raise F4ReleaseError('La cohorte I4 no reprodujo el resultado fijado.')
    apps = report.get('per_app')
    if not isinstance(apps, dict) or set(apps) != {'a2_rag', 'a3_tools'}:
        raise F4ReleaseError('Faltan aplicaciones en la reejecución I4.')
    for name, stats in apps.items():
        if (stats.get('pairs') != 15 or stats.get('false_pairs') != 0 or
                stats.get('missed_pairs') != 0 or
                stats.get('minimum_target_coverage') != '1' or
                stats.get('maximum_ambiguity') != '0' or
                stats.get('strong_sequence_parity_pairs') != 15):
            raise F4ReleaseError(f'Falló I4 para la aplicación {name}.')
    return {'i4': 'pass_reexecuted', 'pairs': 30,
            'summary_sha256': SUMMARY_SHA256}


def main() -> None:
    parser = argparse.ArgumentParser(description='R0.10-F4: aceptación técnica con reservas')
    parser.add_argument('--rerun-i4', action='store_true',
                        help='Ejecutar las 30 parejas y verificar el resumen fijado')
    args = parser.parse_args()
    result = verify_f4()
    if args.rerun_i4:
        result.update(verify_i4_reexecution())
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

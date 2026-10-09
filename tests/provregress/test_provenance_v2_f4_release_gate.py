"""Pruebas del dictamen F4, incluidas alteraciones maliciosas de la evidencia."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from research.verification.r010_f4_release_gate import (
    EXPECTED_DECISION, EXPECTED_FILES, EXPECTED_OPEN, RECORD, ROOT,
    F4ReleaseError, verify_f4,
)


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    """Construye una copia restringida para ensayar corrupción y omisiones."""
    paths = set(EXPECTED_FILES) | {RECORD.as_posix()}
    f3 = json.loads((ROOT / 'research/verification/R0.10-F3-evidence.json').read_bytes())
    paths.update(f3['files_sha256'])
    for path in paths:
        origin = ROOT / path
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
    return tmp_path


def test_acceptance_verifies_f3_and_rejects_scientific_freeze():
    result = verify_f4()
    assert result['technical_baseline'] == 'accepted_for_nonconfirmatory_development'
    assert result['scientific_freeze'] == 'candidate_not_scientifically_frozen'
    assert result['r1_experimental_mutations'] == 'blocked'
    assert result['graph_superiority'] == 'not_demonstrated'
    assert result['verified_files'] == 13
    assert result['open_scientific_gates'] == 7
    assert result['f3_rechecked'] is True


def test_i4_evidence_is_explicitly_nonconfirmatory():
    record = json.loads((ROOT / RECORD).read_bytes())
    assert record['decision'] == EXPECTED_DECISION
    assert record['open_scientific_requirements'] == EXPECTED_OPEN
    report = record['i4_cohort_evidence']
    assert report['total_pairs'] == 30
    assert report['strong_sequence_parity_pairs'] == 30
    assert report['scientific_freeze'] == 'blocked_pending_external_validation'
    assert report['superiority_over_sequence'] == 'not_demonstrated'
    assert record['baseline']['merge_pr'] == 4


@pytest.mark.parametrize('path', [
    'research/preregistration/R0.10-I4-cohort.json',
    'research/preregistration/R0.10-I4-cohort-evaluation.md',
    'provregress/provenance_v2/cohort_audit.py',
    'provregress/provenance_v2/persistent.py',
    'tests/fixtures/provenance/r0_10_i3/annotations.json',
    'research/verification/R0.10-F3-evidence.json',
])
def test_modified_evidence_cannot_pass_gate(evidence: Path, path: str):
    target = evidence / path
    target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(F4ReleaseError, match='Deriva'):
        verify_f4(evidence)


@pytest.mark.parametrize('field,value', [
    ('provenance_v2_contract', 'scientifically_frozen'),
    ('r1_experimental_mutations', 'permitted'),
    ('graph_superiority', 'demonstrated'),
])
def test_no_manual_freeze_or_unblocking(evidence: Path, field: str, value: str):
    target = evidence / RECORD
    item = json.loads(target.read_bytes())
    item['decision'][field] = value
    target.write_text(json.dumps(item), encoding='utf-8')
    with pytest.raises(F4ReleaseError, match='manifiesto'):
        verify_f4(evidence)


def test_missing_and_duplicate_manifest_records_rejected(evidence: Path):
    target = evidence / RECORD
    target.unlink()
    with pytest.raises(F4ReleaseError, match='No existe'):
        verify_f4(evidence)


def test_missing_evidence_rejected(evidence: Path):
    target = evidence / 'provregress/provenance_v2/cohort_audit.py'
    target.unlink()
    with pytest.raises(F4ReleaseError, match='No existe'):
        verify_f4(evidence)


def test_symlink_evidence_rejected(evidence: Path):
    target = evidence / 'provregress/provenance_v2/persistent.py'
    target.unlink()
    target.symlink_to(evidence / 'research/verification/R0.10-F3-evidence.json')
    with pytest.raises(F4ReleaseError, match='symlinks'):
        verify_f4(evidence)


def test_complete_manifest_matches_source_digests():
    item = json.loads((ROOT / RECORD).read_bytes())
    assert set(item['integrity_sha256']) == EXPECTED_FILES
    for path, digest in item['integrity_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest


def test_manifest_is_canonical_at_the_byte_level():
    data = (ROOT / RECORD).read_bytes()
    assert data.endswith(b'\n')
    item = json.loads(data)
    expected = (json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2)
                + '\n').encode('utf-8')
    assert expected == data


def test_no_f4_release_file_modifies_frozen_fixtures():
    record = json.loads((ROOT / RECORD).read_bytes())
    for folder in ('r0_8', 'r0_10', 'r0_10_f2'):
        names = (ROOT / 'tests/fixtures/provenance' / folder / 'SHA256SUMS')
        for line in names.read_text(encoding='utf-8').splitlines():
            digest, filename = line.split('  ', 1)
            assert hashlib.sha256((names.parent / filename).read_bytes()).hexdigest() == digest

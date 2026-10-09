"""R0.10-F3: evidencias reproducibles y prohibición de un freeze injustificado."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from research.verification.r010_f3_release_gate import (
    AuditReleaseError, REQUIRED_FILES, ROOT, RECORD,
    verify_audit_record, verify_local_i2,
)


@pytest.fixture
def audit_copy(tmp_path: Path) -> Path:
    """Copia mínima para probar alteraciones sin modificar la evidencia publicada."""
    for name in [*REQUIRED_FILES, RECORD.as_posix()]:
        source, target = ROOT / name, tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return tmp_path


def _change_record(root: Path, transform) -> None:
    path = root / RECORD
    content = json.loads(path.read_text(encoding="utf-8"))
    transform(content)
    path.write_text(json.dumps(content, sort_keys=True) + "\n", encoding="utf-8")


def test_contract_status_is_conditional_not_frozen():
    result = verify_audit_record()
    assert result["technical_audit"] == "closed_with_conditions"
    assert result["provenance_v2_contract"] == "candidate_not_frozen"
    assert result["mutation_harness"] == "experimental_execution_blocked"
    assert result["open_requirements"] == 7
    assert result["verified_files"] == len(REQUIRED_FILES)


@pytest.mark.parametrize("field,value", [
    ("provenance_v2_contract", "frozen_v2"),
    ("mutation_harness", "unblocked"),
    ("technical_audit", "closed_unconditionally"),
    ("rust_reference", "v2_conformant"),
])
def test_rejects_overclaimed_decision(audit_copy, field, value):
    _change_record(audit_copy, lambda record: record["decision"].__setitem__(field, value))
    with pytest.raises(AuditReleaseError):
        verify_audit_record(audit_copy)


def test_rejects_asserting_external_evidence_is_complete(audit_copy):
    _change_record(audit_copy, lambda r: r["open_requirements"].__setitem__(
        "independent_ground_truth_for_a2_a3", True))
    with pytest.raises(AuditReleaseError):
        verify_audit_record(audit_copy)


def test_rejects_silent_source_change(audit_copy):
    victim = audit_copy / "provregress/provenance_v2/comparison.py"
    victim.write_bytes(victim.read_bytes() + b"# cambio inadvertido\n")
    with pytest.raises(AuditReleaseError, match="Deriva de contenido"):
        verify_audit_record(audit_copy)


@pytest.mark.parametrize("fixture", ["r0_8", "r0_10", "r0_10_f2"])
def test_rejects_altered_fixture_bytes(audit_copy, fixture):
    name = "inputs.json" if fixture == "r0_8" else "cases.json"
    target = audit_copy / "tests/fixtures/provenance" / fixture / name
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(AuditReleaseError):
        verify_audit_record(audit_copy)


def test_rejects_missing_manifest_entries_even_if_index_recomputed(audit_copy):
    name = "tests/fixtures/provenance/r0_10_f2/SHA256SUMS"
    target = audit_copy / name
    target.write_bytes(target.read_bytes().splitlines(keepends=True)[0])
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    _change_record(audit_copy, lambda r: r["files_sha256"].__setitem__(name, digest))
    with pytest.raises(AuditReleaseError, match="no enumera"):
        verify_audit_record(audit_copy)


def test_rejects_symlinks_to_audited_files(audit_copy, tmp_path):
    victim = audit_copy / "provregress/provenance_v2/schema.py"
    data = victim.read_bytes()
    victim.unlink()
    outside = tmp_path / "source-replacement.py"
    outside.write_bytes(data)
    victim.symlink_to(outside)
    with pytest.raises(AuditReleaseError, match="symlinks"):
        verify_audit_record(audit_copy)


def test_rejects_forged_i2_audit_hash(audit_copy):
    _change_record(audit_copy, lambda r: r["local_i2_expected"].__setitem__(
        "audit_hash", "0" * 64))
    with pytest.raises(AuditReleaseError):
        verify_audit_record(audit_copy)


def test_detects_duplicate_json_keys(audit_copy):
    target = audit_copy / RECORD
    content = target.read_text(encoding="utf-8")
    target.write_text(content.replace('"schema_version":',
        '"schema_version": "fake", "schema_version":', 1), encoding="utf-8")
    with pytest.raises(AuditReleaseError, match="duplicadas"):
        verify_audit_record(audit_copy)


def test_decision_rejects_a_renamed_baseline(audit_copy):
    _change_record(audit_copy, lambda r: r["baseline"].__setitem__("i2_commit", "0" * 40))
    with pytest.raises(AuditReleaseError):
        verify_audit_record(audit_copy)


def test_can_replay_i2_cohort_without_using_privileged_data_as_features():
    result = verify_local_i2()
    assert result["status"] == "pass_local_instrumentation"
    assert result["negative_rekey_rejections"] == 6
    assert all(app["false_pairs"] == app["missed_pairs"] == 0
               for app in result["applications"].values())

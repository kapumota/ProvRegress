"""Pruebas de direccionamiento por contenido e integridad en R0.7-C7."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from provregress.schema import ArtifactRef, HashRef
from provregress.storage.artifacts import (
    ArtifactIntegrityError,
    ArtifactStore,
    ArtifactStoreError,
)


def _path(store: ArtifactStore, ref: ArtifactRef) -> Path:
    return store.root / ref.relative_path


def test_put_bytes_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "objects")
    first = store.put_bytes(b"exact content", media_type="text/plain")
    target = _path(store, first)
    inode = target.stat().st_ino
    second = store.put_bytes(b"exact content", media_type="text/plain")
    assert first == second
    assert target.stat().st_ino == inode
    assert store.get_bytes(second) == b"exact content"
    assert list(store.root.rglob(first.hash.value)) == [target]


def test_store_digest_matches_hashlib_and_uses_derived_path(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = b"\x00\xff\n\r\x00"
    ref = store.put_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert ref.hash == HashRef(algorithm="sha256", value=digest)
    assert ref.relative_path == f"sha256/{digest[:2]}/{digest}"
    assert ref.size_bytes == len(payload)
    assert ref.media_type is None
    assert _path(store, ref).read_bytes() == payload


def test_empty_and_large_payloads(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    for payload in (b"", b"a" * (1024 * 1024 + 17)):
        ref = store.put_bytes(payload)
        assert store.get_bytes(ref) == payload
        assert store.exists(ref)


def test_different_content_has_different_paths(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first = store.put_bytes(b"one")
    second = store.put_bytes(b"two")
    assert first.hash != second.hash
    assert first.relative_path != second.relative_path


def test_media_type_does_not_change_content_identity(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    one = store.put_bytes(b"test", media_type="text/plain")
    two = store.put_bytes(b"test", media_type="application/octet-stream")
    assert one.relative_path == two.relative_path
    assert one.hash == two.hash
    assert one.media_type != two.media_type


@pytest.mark.parametrize("payload", ["abc", bytearray(b"abc"), None, 3])
def test_put_requires_strict_bytes(tmp_path: Path, payload: object) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(TypeError):
        store.put_bytes(payload)  # type: ignore[arg-type]


@pytest.mark.parametrize("media_type", ["", "  ", b"text/plain", 4])
def test_put_rejects_invalid_media_type(tmp_path: Path, media_type: object) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError):
        store.put_bytes(b"hello", media_type=media_type)  # type: ignore[arg-type]


def test_exists_false_for_missing_valid_reference(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    digest = hashlib.sha256(b"missing").hexdigest()
    ref = ArtifactRef(
        hash=HashRef(algorithm="sha256", value=digest),
        relative_path=f"sha256/{digest[:2]}/{digest}",
        size_bytes=len(b"missing"),
    )
    assert not store.exists(ref)
    with pytest.raises(FileNotFoundError):
        store.get_bytes(ref)


def test_get_detects_corrupted_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.put_bytes(b"original")
    _path(store, ref).write_bytes(b"tampered!")
    with pytest.raises(ArtifactIntegrityError):
        store.get_bytes(ref)
    with pytest.raises(ArtifactIntegrityError):
        store.exists(ref)
    with pytest.raises(ArtifactIntegrityError):
        store.put_bytes(b"original")
    assert _path(store, ref).read_bytes() == b"tampered!"


def test_get_detects_truncated_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.put_bytes(b"full content")
    _path(store, ref).write_bytes(b"short")
    with pytest.raises(ArtifactIntegrityError):
        store.get_bytes(ref)


def test_get_rejects_wrong_digest_and_size(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.put_bytes(b"original")
    forged_size = ref.model_copy(update={"size_bytes": 100})
    with pytest.raises(ArtifactIntegrityError):
        store.get_bytes(forged_size)
    forged_hash = ref.model_copy(update={"hash": HashRef(algorithm="sha256", value="a" * 64)})
    with pytest.raises(ArtifactStoreError):
        store.get_bytes(forged_hash)


def test_get_rejects_forged_relative_path(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.put_bytes(b"data")
    for forged in ("../outside", "/tmp/outside", "sha256/00/" + ref.hash.value):
        with pytest.raises(ArtifactStoreError):
            store.get_bytes(ref.model_copy(update={"relative_path": forged}))


def test_get_rejects_forged_ref_metadata(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.put_bytes(b"data")
    forged = ref.model_copy(update={"size_bytes": "4"})
    with pytest.raises(ArtifactStoreError):
        store.get_bytes(forged)


def test_get_requires_artifact_ref(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ArtifactStoreError):
        store.get_bytes({})  # type: ignore[arg-type]


def test_rejects_symlink_as_artifact(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    ref = store.put_bytes(b"safe")
    target = _path(store, ref)
    target.unlink()
    external = tmp_path / "external"
    external.write_bytes(b"safe")
    target.symlink_to(external)
    with pytest.raises(ArtifactIntegrityError):
        store.get_bytes(ref)
    with pytest.raises(ArtifactIntegrityError):
        store.put_bytes(b"safe")
    assert external.read_bytes() == b"safe"


def test_rejects_symlink_as_store_directory(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "sha256").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactStoreError):
        store.put_bytes(b"safe")
    assert list(outside.iterdir()) == []


def test_atomic_concurrent_same_payload(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = b"parallel" * 1024
    with ThreadPoolExecutor(max_workers=8) as executor:
        refs = list(executor.map(store.put_bytes, [payload] * 16))
    assert all(ref == refs[0] for ref in refs)
    assert store.get_bytes(refs[0]) == payload
    assert list(store.root.rglob(refs[0].hash.value)) == [_path(store, refs[0])]
    assert not list(store.root.rglob(".artifact-*"))


def test_public_api_excludes_overwrite_or_delete(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    assert not hasattr(store, "overwrite")
    assert not hasattr(store, "delete")
    assert issubclass(ArtifactIntegrityError, ArtifactStoreError)


def test_does_not_modify_input_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = b"\x00\x01\xff"
    store.put_bytes(payload)
    assert payload == b"\x00\x01\xff"

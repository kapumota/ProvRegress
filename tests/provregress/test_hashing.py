"""Pruebas de hashing determinista y rechazo de entradas ambiguas."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from provregress.schema import HashRef
from provregress.storage import (
    canonical_json_bytes,
    hash_case_ids,
    hash_file,
    hash_model,
    sha256_hex,
)


class ExampleModel(BaseModel):
    """Modelo controlado utilizado exclusivamente durante las pruebas."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    count: int
    timestamp_utc: datetime


def test_canonical_json_bytes_are_utf8_sorted_and_compact() -> None:
    assert canonical_json_bytes({"z": 3, "á": "niño", "a": [True, None]}) == (
        '{"a":[true,null],"z":3,"á":"niño"}'.encode("utf-8")
    )


def test_canonical_json_hash_is_key_order_independent() -> None:
    left = {"a": {"x": 1, "y": 2}, "b": [2, 1]}
    right = {"b": [2, 1], "a": {"y": 2, "x": 1}}
    assert sha256_hex(canonical_json_bytes(left)) == sha256_hex(canonical_json_bytes(right))


def test_canonical_json_preserves_array_order() -> None:
    assert canonical_json_bytes([1, 2]) != canonical_json_bytes([2, 1])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"nested": [value]})


@pytest.mark.parametrize("value", [{1: "x"}, {"nested": [{False: "x"}]}])
def test_canonical_json_rejects_non_string_keys(value: dict[Any, Any]) -> None:
    with pytest.raises(TypeError):
        canonical_json_bytes(value)


def test_canonical_json_rejects_unsupported_types() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"items": {"uno", "dos"}})


def test_canonical_json_rejects_circular_references() -> None:
    cyclic: list[Any] = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="circulares"):
        canonical_json_bytes(cyclic)


def test_sha256_hex_matches_known_vector() -> None:
    assert sha256_hex(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_hex_rejects_non_bytes() -> None:
    with pytest.raises(TypeError):
        sha256_hex("abc")  # type: ignore[arg-type]


def test_hash_model_is_stable_for_same_model() -> None:
    model = ExampleModel(name="versión", count=2, timestamp_utc=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert hash_model(model) == hash_model(model)
    assert hash_model(model).algorithm == "sha256"
    assert len(hash_model(model).value) == 64


def test_hash_model_uses_pydantic_json_mode() -> None:
    model = ExampleModel(name="caso", count=1, timestamp_utc=datetime(2026, 10, 8, tzinfo=timezone.utc))
    expected = sha256_hex(canonical_json_bytes(model.model_dump(mode="json")))
    assert hash_model(model) == HashRef(algorithm="sha256", value=expected)
    assert canonical_json_bytes(model) == canonical_json_bytes(model.model_dump(mode="json"))


def test_hash_model_changes_when_value_changes() -> None:
    first = ExampleModel(name="a", count=1, timestamp_utc=datetime(2026, 10, 8, tzinfo=timezone.utc))
    second = first.model_copy(update={"count": 2})
    assert hash_model(first) != hash_model(second)


def test_hash_model_rejects_non_model() -> None:
    with pytest.raises(TypeError):
        hash_model({"name": "caso"})  # type: ignore[arg-type]


def test_hash_file_matches_exact_binary_content(tmp_path: Path) -> None:
    payload = b"\x00\xff\x10abc\r\n"
    path = tmp_path / "trace.bin"
    path.write_bytes(payload)
    assert hash_file(path) == HashRef(algorithm="sha256", value=hashlib.sha256(payload).hexdigest())
    assert path.read_bytes() == payload


def test_hash_file_distinguishes_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"{\"a\":1}\n")
    first = hash_file(path)
    path.write_bytes(b"{\"a\":1}\r\n")
    assert first != hash_file(path)


def test_hash_file_reads_large_payload_in_chunks(tmp_path: Path) -> None:
    payload = b"a" * (1024 * 1024 + 17)
    path = tmp_path / "large.bin"
    path.write_bytes(payload)
    assert hash_file(path).value == hashlib.sha256(payload).hexdigest()


def test_hash_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        hash_file(tmp_path / "missing.bin")


def test_case_id_hash_is_order_independent_but_duplicate_rejecting() -> None:
    first = hash_case_ids(["case-3", "case-1", "case-2"])
    second = hash_case_ids(["case-2", "case-3", "case-1"])
    assert first == second
    assert first.value == sha256_hex(canonical_json_bytes(["case-1", "case-2", "case-3"]))
    with pytest.raises(ValueError, match="repetirse"):
        hash_case_ids(["case-1", "case-1"])


@pytest.mark.parametrize("case_ids", [[""], ["  "], ["a", "\t"]])
def test_hash_case_ids_rejects_blank_ids(case_ids: list[str]) -> None:
    with pytest.raises(ValueError, match="vacíos"):
        hash_case_ids(case_ids)


def test_hash_case_ids_rejects_invalid_containers() -> None:
    for invalid in ["case-1", b"case-1", {"case-1", "case-2"}]:
        with pytest.raises(TypeError):
            hash_case_ids(invalid)  # type: ignore[arg-type]


def test_hash_case_ids_rejects_non_string_elements() -> None:
    with pytest.raises(TypeError):
        hash_case_ids(["case-1", 2])  # type: ignore[list-item]


def test_hash_case_ids_does_not_mutate_input() -> None:
    case_ids = ["case-2", "case-1"]
    hash_case_ids(case_ids)
    assert case_ids == ["case-2", "case-1"]


def test_hash_case_ids_allows_empty_sequence_without_inventing_ids() -> None:
    assert hash_case_ids([]).value == sha256_hex(b"[]")

"""Pruebas del gate PG1 para impedir contaminación confirmatoria."""

from collections.abc import Callable

import pytest

from provregress.pilot import (
    PilotContaminationError,
    PilotFirewall,
    PilotFirewallError,
    UnknownPilotCaseError,
)
from provregress.schema.manifests import PilotStudyManifest
from provregress.storage.hashing import hash_case_ids


@pytest.fixture
def study() -> PilotStudyManifest:
    """Construye un estudio con conjuntos piloto y confirmatorio disjuntos."""
    return PilotStudyManifest(
        pilot_id="pilot-01",
        protocol_version="r0.5",
        pilot_case_ids=["pilot-a", "pilot-b"],
        confirmatory_case_ids=["confirmatory-a", "confirmatory-b"],
        pilot_case_ids_hash=hash_case_ids(["pilot-a", "pilot-b"]),
        confirmatory_case_ids_hash=hash_case_ids(["confirmatory-a", "confirmatory-b"]),
        analysis_plan_version="v1",
    )


@pytest.fixture
def firewall(study: PilotStudyManifest) -> PilotFirewall:
    return PilotFirewall(study)


@pytest.mark.parametrize("case_id", ["pilot-a", "pilot-b"])
def test_firewall_allows_pilot_case(firewall: PilotFirewall, case_id: str) -> None:
    assert firewall.assert_pilot_case(case_id) is None


@pytest.mark.parametrize("case_id", ["confirmatory-a", "confirmatory-b"])
def test_firewall_rejects_confirmatory_case(
    firewall: PilotFirewall, case_id: str
) -> None:
    with pytest.raises(PilotContaminationError):
        firewall.assert_pilot_case(case_id)


@pytest.mark.parametrize("case_id", ["outside", "pilot-A", "pilot-a ", " pilot-a"])
def test_firewall_rejects_unknown_case(firewall: PilotFirewall, case_id: str) -> None:
    with pytest.raises(UnknownPilotCaseError):
        firewall.assert_pilot_case(case_id)


@pytest.mark.parametrize("case_id", ["", "  ", "\n", None, 0, b"pilot-a"])
def test_firewall_rejects_blank_and_nonstrict_ids(
    firewall: PilotFirewall, case_id: object
) -> None:
    with pytest.raises(UnknownPilotCaseError):
        firewall.assert_pilot_case(case_id)  # type: ignore[arg-type]


def guarded_call(
    firewall: PilotFirewall, case_id: str, callback: Callable[[], None]
) -> None:
    """Simula el orden obligatorio del caller sin implementar un ejecutor."""
    firewall.assert_pilot_case(case_id)
    callback()


@pytest.mark.parametrize(
    "case_id,error",
    [
        ("confirmatory-a", PilotContaminationError),
        ("outside", UnknownPilotCaseError),
    ],
)
def test_firewall_rejects_before_execution_callback(
    firewall: PilotFirewall, case_id: str, error: type[PilotFirewallError]
) -> None:
    called: list[bool] = []
    with pytest.raises(error):
        guarded_call(firewall, case_id, lambda: called.append(True))
    assert called == []


def test_firewall_allows_callback_only_after_check(firewall: PilotFirewall) -> None:
    called: list[bool] = []
    guarded_call(firewall, "pilot-a", lambda: called.append(True))
    assert called == [True]


def test_filter_pilot_cases_preserves_order_and_repeats(firewall: PilotFirewall) -> None:
    case_ids = ["pilot-b", "pilot-a", "pilot-b"]
    assert firewall.filter_pilot_cases(case_ids) == case_ids


def test_filter_pilot_cases_accepts_iterator(firewall: PilotFirewall) -> None:
    assert firewall.filter_pilot_cases(iter(["pilot-a", "pilot-b"])) == [
        "pilot-a", "pilot-b"
    ]


def test_filter_pilot_cases_accepts_empty_iterable(firewall: PilotFirewall) -> None:
    assert firewall.filter_pilot_cases([]) == []


@pytest.mark.parametrize(
    "case_ids,error",
    [
        (["pilot-a", "confirmatory-a"], PilotContaminationError),
        (["outside", "pilot-b"], UnknownPilotCaseError),
        (["pilot-a", "outside"], UnknownPilotCaseError),
    ],
)
def test_filter_pilot_cases_does_not_silently_skip_forbidden_ids(
    firewall: PilotFirewall, case_ids: list[str], error: type[PilotFirewallError]
) -> None:
    with pytest.raises(error):
        firewall.filter_pilot_cases(case_ids)


@pytest.mark.parametrize("case_ids", ["pilot-a", b"pilot-a", None, 17])
def test_filter_pilot_cases_requires_an_iterable_of_ids(
    firewall: PilotFirewall, case_ids: object
) -> None:
    with pytest.raises(PilotFirewallError):
        firewall.filter_pilot_cases(case_ids)  # type: ignore[arg-type]


def test_filter_pilot_cases_checks_lazy_iterator(firewall: PilotFirewall) -> None:
    yielded: list[str] = []

    def source():
        for item in ["pilot-a", "confirmatory-a", "pilot-b"]:
            yielded.append(item)
            yield item

    with pytest.raises(PilotContaminationError):
        firewall.filter_pilot_cases(source())
    assert yielded == ["pilot-a", "confirmatory-a"]


def test_firewall_requires_valid_manifest() -> None:
    with pytest.raises(PilotFirewallError):
        PilotFirewall({})  # type: ignore[arg-type]


def test_firewall_revalidates_manifest_with_forged_overlap(
    study: PilotStudyManifest,
) -> None:
    forged = study.model_copy(
        update={
            "confirmatory_case_ids": ["pilot-a"],
            "confirmatory_case_ids_hash": hash_case_ids(["pilot-a"]),
        }
    )
    with pytest.raises(PilotFirewallError):
        PilotFirewall(forged)


def test_firewall_revalidates_manifest_with_forged_hash(
    study: PilotStudyManifest,
) -> None:
    forged = study.model_copy(update={"pilot_case_ids": ["outside"]})
    with pytest.raises(PilotFirewallError):
        PilotFirewall(forged)


def test_firewall_keeps_snapshot_if_source_manifest_changes(
    study: PilotStudyManifest,
) -> None:
    firewall = PilotFirewall(study)
    study.pilot_case_ids[:] = ["outside"]
    study.confirmatory_case_ids[:] = ["pilot-a"]
    firewall.assert_pilot_case("pilot-a")
    with pytest.raises(UnknownPilotCaseError):
        firewall.assert_pilot_case("outside")
    with pytest.raises(PilotContaminationError):
        firewall.assert_pilot_case("confirmatory-a")


def test_errors_share_a_common_parent() -> None:
    assert issubclass(PilotContaminationError, PilotFirewallError)
    assert issubclass(UnknownPilotCaseError, PilotFirewallError)

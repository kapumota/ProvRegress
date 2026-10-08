"""Barrera de seguridad entre los casos piloto y los confirmatorios."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from provregress.schema.manifests import PilotStudyManifest


class PilotFirewallError(ValueError):
    """Error de validación del acceso a casos del estudio piloto."""


class PilotContaminationError(PilotFirewallError):
    """Intento de acceder a un caso reservado para el estudio confirmatorio."""


class UnknownPilotCaseError(PilotFirewallError):
    """Caso inexistente en el conjunto piloto autorizado."""


class PilotFirewall:
    """Autoriza exclusivamente IDs piloto fijados en un manifest válido."""

    def __init__(self, study: PilotStudyManifest) -> None:
        """Revalida el manifest y conserva una copia estable de sus conjuntos."""
        if not isinstance(study, PilotStudyManifest):
            raise PilotFirewallError("Se requiere un PilotStudyManifest válido.")

        try:
            # La revalidación evita aceptar instancias alteradas tras su creación.
            checked = PilotStudyManifest.model_validate(study.model_dump(mode="python"))
        except (ValidationError, TypeError, ValueError) as exc:
            raise PilotFirewallError("El manifest piloto no supera la validación.") from exc

        self._pilot_case_ids = frozenset(checked.pilot_case_ids)
        self._confirmatory_case_ids = frozenset(checked.confirmatory_case_ids)

    def assert_pilot_case(self, case_id: str) -> None:
        """Autoriza un ID piloto exacto o rechaza el intento sin ejecutarlo."""
        if not isinstance(case_id, str) or not case_id.strip():
            raise UnknownPilotCaseError("El identificador de caso no es válido.")
        if case_id in self._confirmatory_case_ids:
            raise PilotContaminationError(
                "El caso pertenece al conjunto confirmatorio y está bloqueado."
            )
        if case_id not in self._pilot_case_ids:
            raise UnknownPilotCaseError("El caso no pertenece al conjunto piloto autorizado.")

    def filter_pilot_cases(self, case_ids: Iterable[str]) -> list[str]:
        """Valida todos los IDs sin descartar silenciosamente casos prohibidos."""
        if isinstance(case_ids, (str, bytes)):
            raise PilotFirewallError("Se requiere un iterable de identificadores, no texto.")
        try:
            iterator = iter(case_ids)
        except TypeError as exc:
            raise PilotFirewallError("Se requiere un iterable de identificadores.") from exc

        approved: list[str] = []
        for case_id in iterator:
            self.assert_pilot_case(case_id)
            approved.append(case_id)
        return approved

"""Contrato base de providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from llmtestlab.models import LLMOutput, ProviderConfig, TestCase


class BaseProvider(ABC):
    """Interfaz mínima de un provider."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def generate(self, test: TestCase) -> LLMOutput:
        """Genera una salida para un caso de prueba."""

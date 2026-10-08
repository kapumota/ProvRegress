"""Contratos comunes para identificar aplicaciones, ejecuciones y artefactos."""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AppId(str, Enum):
    """Aplicaciones experimentales identificadas en el protocolo científico."""

    A1 = "a1_extraction"
    A2 = "a2_rag"
    A3 = "a3_tools"


class ComponentType(str, Enum):
    """Vocabulario cerrado de los 21 tipos de componente."""

    INPUT_CASE = "input_case"
    SYSTEM_VERSION = "system_version"
    PROMPT = "prompt"
    MODEL = "model"
    RETRIEVER = "retriever"
    CORPUS = "corpus"
    CHUNK = "chunk"
    RANKER = "ranker"
    AGENT = "agent"
    TOOL = "tool"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SCHEMA = "schema"
    GENERATED_ARTIFACT = "generated_artifact"
    CLAIM = "claim"
    CITATION = "citation"
    EVALUATOR = "evaluator"
    EVALUATION = "evaluation"
    OUTCOME = "outcome"
    FAILURE = "failure"
    RUNTIME = "runtime"


class RunStatus(str, Enum):
    """Estados admitidos durante el ciclo de una ejecución."""

    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class HashRef(BaseModel):
    """Identifica contenido mediante un digest SHA-256 en hexadecimal minúsculo."""

    model_config = ConfigDict(extra="forbid", strict=True)

    algorithm: Literal["sha256"]
    value: str = Field(pattern=r"^[a-f0-9]{64}$")


class ArtifactRef(BaseModel):
    """Referencia un artefacto mediante su digest y una ruta local relativa."""

    model_config = ConfigDict(extra="forbid", strict=True)

    hash: HashRef
    relative_path: str = Field(min_length=1)
    media_type: str | None = None
    size_bytes: int = Field(ge=0)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        """Impide rutas absolutas, recorridos ascendentes y rutas ambiguas."""
        if (
            "\\" in value
            or "\x00" in value
            or PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).drive
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("La ruta del artefacto debe ser relativa y canónica.")
        return value

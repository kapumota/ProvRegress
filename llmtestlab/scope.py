"""Definición estricta del alcance para la Fase 0 de LLMTestLab.

La Fase 0 no ejecuta modelos, no evalúa respuestas y no llama APIs externas.
Su único propósito es dejar por escrito qué se construirá, qué queda fuera y
cuáles son los criterios mínimos para avanzar a la Fase 1.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class AppType(str, Enum):
    """Tipos de aplicaciones LLM permitidas en la primera versión."""

    SIMPLE_CHATBOT = "simple_chatbot"
    JSON_EXTRACTOR = "json_extractor"
    BASIC_RAG = "basic_rag"


@dataclass(frozen=True)
class AppEvaluationProfile:
    """Describe un tipo de aplicación y qué se evaluará en fases posteriores."""

    app_type: AppType
    display_name: str
    evaluation_target: str
    example_tests: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convierte el perfil a un diccionario serializable."""
        return {
            "app_type": self.app_type.value,
            "display_name": self.display_name,
            "evaluation_target": self.evaluation_target,
            "example_tests": list(self.example_tests),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppEvaluationProfile":
        """Construye un perfil desde un diccionario cargado desde JSON."""
        return cls(
            app_type=AppType(str(data.get("app_type", ""))),
            display_name=str(data.get("display_name", "")),
            evaluation_target=str(data.get("evaluation_target", "")),
            example_tests=list(data.get("example_tests", [])),
        )


@dataclass(frozen=True)
class ProjectScope:
    """Representa el contrato de alcance acordado para la Fase 0."""

    project_name: str
    version: str
    focus: str
    differentiator: str
    product_summary: str
    primary_goal: str
    supported_app_profiles: list[AppEvaluationProfile] = field(default_factory=list)
    in_scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_phase: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convierte el alcance a un diccionario serializable como JSON."""
        data = asdict(self)
        data["supported_app_profiles"] = [
            profile.to_dict() for profile in self.supported_app_profiles
        ]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectScope":
        """Construye un alcance desde un diccionario cargado desde JSON."""
        profiles = [
            AppEvaluationProfile.from_dict(profile)
            for profile in data.get("supported_app_profiles", [])
        ]
        return cls(
            project_name=str(data.get("project_name", "")),
            version=str(data.get("version", "")),
            focus=str(data.get("focus", "")),
            differentiator=str(data.get("differentiator", "")),
            product_summary=str(data.get("product_summary", "")),
            primary_goal=str(data.get("primary_goal", "")),
            supported_app_profiles=profiles,
            in_scope=list(data.get("in_scope", [])),
            out_of_scope=list(data.get("out_of_scope", [])),
            success_criteria=list(data.get("success_criteria", [])),
            risks=list(data.get("risks", [])),
            next_phase=str(data.get("next_phase", "")),
        )


def build_default_app_profiles() -> list[AppEvaluationProfile]:
    """Crea los tres perfiles exactos soportados por la primera versión."""
    return [
        AppEvaluationProfile(
            app_type=AppType.SIMPLE_CHATBOT,
            display_name="Chatbot simple",
            evaluation_target="calidad de respuesta",
            example_tests=[
                "La respuesta incluye hechos obligatorios.",
                "La respuesta evita afirmaciones explícitamente prohibidas.",
                "La respuesta cumple un formato mínimo definido por la suite.",
            ],
        ),
        AppEvaluationProfile(
            app_type=AppType.JSON_EXTRACTOR,
            display_name="Extractor JSON",
            evaluation_target="estructura y campos correctos",
            example_tests=[
                "La salida es JSON válido.",
                "La salida cumple un JSON Schema.",
                "Los campos obligatorios existen y tienen el tipo esperado.",
            ],
        ),
        AppEvaluationProfile(
            app_type=AppType.BASIC_RAG,
            display_name="RAG básico",
            evaluation_target="respuesta sustentada por documentos",
            example_tests=[
                "La respuesta está basada en los documentos recuperados.",
                "La respuesta cita la fuente esperada cuando sea obligatorio.",
                "La respuesta no agrega afirmaciones sin soporte documental.",
            ],
        ),
    ]


def build_default_scope() -> ProjectScope:
    """Crea el alcance base recomendado para comenzar LLMTestLab."""
    return ProjectScope(
        project_name="LLMTestLab",
        version="0.0.1",
        focus="unit testing + regression testing para apps LLM",
        differentiator="detectar regresiones, no solo evaluar respuestas aisladas",
        product_summary=(
            "Framework estilo Pytest para definir pruebas unitarias y pruebas de regresión "
            "en aplicaciones basadas en LLMs, empezando con chatbots simples, extractores "
            "JSON y sistemas RAG básicos."
        ),
        primary_goal=(
            "Definir exactamente qué se construirá antes de programar el motor de pruebas: "
            "alcance, límites, tipos de aplicación soportados y criterios de éxito."
        ),
        supported_app_profiles=build_default_app_profiles(),
        in_scope=[
            "Definir el nombre oficial del proyecto: LLMTestLab.",
            "Definir el foco: unit testing + regression testing para apps LLM.",
            "Definir el diferenciador: detectar regresiones, no solo evaluar respuestas aisladas.",
            "Limitar la primera versión a chatbot simple, extractor JSON y RAG básico.",
            "Crear una CLI inicial para generar, validar y resumir el alcance.",
            "Generar un archivo scope.json versionable.",
            "Generar un documento PHASE_0_SCOPE.md legible para revisión humana.",
            "Validar que el alcance tenga tipos soportados, límites y criterios de éxito.",
        ],
        out_of_scope=[
            "No ejecutar llamadas reales a modelos LLM en Fase 0.",
            "No implementar assertions ni evaluadores en Fase 0.",
            "No comparar baseline contra candidate en Fase 0.",
            "No construir dashboard web en Fase 0.",
            "No integrar CI/CD en Fase 0.",
            "No soportar agentes complejos ni agentes con tools en la primera versión.",
            "No soportar evaluación multimodal en la primera versión.",
        ],
        success_criteria=[
            "El repositorio puede instalarse en modo desarrollo.",
            "El comando init genera scope.json y PHASE_0_SCOPE.md.",
            "El comando validate detecta alcances incompletos o fuera del alcance inicial.",
            "El alcance incluye exactamente tres tipos de app: chatbot simple, extractor JSON y RAG básico.",
            "Cada tipo de app indica claramente qué se evaluará.",
            "El alcance excluye explícitamente agentes con tools para una fase posterior.",
            "Los tests unitarios de Fase 0 pasan localmente.",
        ],
        risks=[
            "Intentar construir agentes con tools antes de tener un runner estable.",
            "Confundir evaluación aislada con regression testing versionado.",
            "Agregar demasiados tipos de aplicación antes de validar el MVP.",
            "Construir dashboard o CI/CD antes de validar el contrato de pruebas.",
        ],
        next_phase=(
            "Fase 1: diseñar el formato evals.yaml para declarar suites, providers, "
            "casos de prueba, assertions, severidades y umbrales."
        ),
    )


def get_supported_app_types(scope: ProjectScope) -> set[AppType]:
    """Devuelve los tipos de aplicación soportados por el alcance."""
    return {profile.app_type for profile in scope.supported_app_profiles}


def validate_scope(scope: ProjectScope) -> list[str]:
    """Devuelve una lista de problemas encontrados en el alcance."""
    errors: list[str] = []

    if scope.project_name.strip() != "LLMTestLab":
        errors.append("El nombre del proyecto debe ser exactamente LLMTestLab.")

    if not scope.version.strip():
        errors.append("La versión no puede estar vacía.")

    focus_lower = scope.focus.lower()
    if "unit testing" not in focus_lower or "regression testing" not in focus_lower:
        errors.append(
            "El foco debe incluir unit testing y regression testing para apps LLM."
        )

    if "regresion" not in normalize_spanish(scope.differentiator):
        errors.append("El diferenciador debe mencionar la detección de regresiones.")

    if not scope.product_summary.strip():
        errors.append("El resumen del producto no puede estar vacío.")

    if not scope.primary_goal.strip():
        errors.append("La meta principal no puede estar vacía.")

    required_app_types = {
        AppType.SIMPLE_CHATBOT,
        AppType.JSON_EXTRACTOR,
        AppType.BASIC_RAG,
    }
    supported_app_types = get_supported_app_types(scope)

    if supported_app_types != required_app_types:
        errors.append(
            "La primera versión debe soportar exactamente: chatbot simple, extractor JSON y RAG básico."
        )

    for profile in scope.supported_app_profiles:
        if not profile.display_name.strip():
            errors.append(f"El perfil {profile.app_type.value} no tiene nombre visible.")
        if not profile.evaluation_target.strip():
            errors.append(f"El perfil {profile.app_type.value} no indica qué evalúa.")
        if len(profile.example_tests) < 2:
            errors.append(
                f"El perfil {profile.app_type.value} debe incluir al menos dos ejemplos de prueba."
            )

    if len(scope.in_scope) < 5:
        errors.append("El alcance incluido debe tener al menos cinco elementos.")

    if len(scope.out_of_scope) < 5:
        errors.append("El alcance excluido debe tener al menos cinco elementos.")

    out_scope_text = normalize_spanish(" ".join(scope.out_of_scope))
    if "agentes" not in out_scope_text or "tools" not in out_scope_text:
        errors.append("El alcance excluido debe dejar fuera agentes con tools.")

    if len(scope.success_criteria) < 5:
        errors.append("Deben existir al menos cinco criterios de éxito.")

    duplicated = set(scope.in_scope).intersection(set(scope.out_of_scope))
    if duplicated:
        duplicated_text = ", ".join(sorted(duplicated))
        errors.append(f"Hay elementos repetidos entre in_scope y out_of_scope: {duplicated_text}")

    return errors


def normalize_spanish(value: str) -> str:
    """Normaliza texto simple para validaciones tolerantes a tildes frecuentes."""
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "Á": "a",
        "É": "e",
        "Í": "i",
        "Ó": "o",
        "Ú": "u",
    }
    normalized = value
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized.lower()


def write_scope_json(scope: ProjectScope, output_path: Path) -> None:
    """Escribe el alcance como JSON con indentación legible."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(scope.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_scope_json(input_path: Path) -> ProjectScope:
    """Carga un archivo JSON de alcance."""
    raw_text = input_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    return ProjectScope.from_dict(data)


def render_scope_markdown(scope: ProjectScope) -> str:
    """Genera una versión Markdown del alcance para revisión humana."""
    app_table = "\n".join(
        [
            "| Tipo de app | Qué evalúas | Ejemplos de prueba |",
            "|---|---|---|",
            *[
                (
                    f"| {profile.display_name} | {profile.evaluation_target} | "
                    f"{'<br>'.join(profile.example_tests)} |"
                )
                for profile in scope.supported_app_profiles
            ],
        ]
    )
    in_scope = "\n".join(f"- {item}" for item in scope.in_scope)
    out_scope = "\n".join(f"- {item}" for item in scope.out_of_scope)
    success = "\n".join(f"- {item}" for item in scope.success_criteria)
    risks = "\n".join(f"- {item}" for item in scope.risks)

    return f"""# {scope.project_name} - Fase 0: Definición del alcance

## Nombre

{scope.project_name}

## Foco

{scope.focus}

## Diferenciador

{scope.differentiator}

## Versión

{scope.version}

## Resumen del producto

{scope.product_summary}

## Meta principal

{scope.primary_goal}

## Tipos de aplicación soportados en la primera versión

{app_table}

## Dentro del alcance

{in_scope}

## Fuera del alcance por ahora

{out_scope}

## Criterios de éxito

{success}

## Riesgos técnicos iniciales

{risks}

## Siguiente fase

{scope.next_phase}
"""


def write_scope_markdown(scope: ProjectScope, output_path: Path) -> None:
    """Escribe el documento Markdown de alcance."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_scope_markdown(scope), encoding="utf-8")

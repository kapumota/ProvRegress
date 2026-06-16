"""CLI inicial de LLMTestLab.

La CLI de Fase 0 solo gestiona el alcance del proyecto. Las fases posteriores
agregarán ejecución de pruebas, providers, comparaciones y reportes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from llmtestlab.scope import (
    ProjectScope,
    build_default_scope,
    load_scope_json,
    render_scope_markdown,
    validate_scope,
    write_scope_json,
    write_scope_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser principal de la CLI."""
    parser = argparse.ArgumentParser(
        prog="llmtestlab",
        description="CLI inicial para definir y validar el alcance de LLMTestLab.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Genera los artefactos iniciales de Fase 0.",
    )
    init_parser.add_argument(
        "--output",
        type=Path,
        default=Path("."),
        help="Directorio donde se crearán scope.json y PHASE_0_SCOPE.md.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Sobrescribe archivos existentes.",
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="Valida un archivo scope.json.",
    )
    validate_parser.add_argument(
        "scope_file",
        type=Path,
        help="Ruta del archivo scope.json que será validado.",
    )

    summary_parser = subparsers.add_parser(
        "summary",
        help="Muestra un resumen del alcance.",
    )
    summary_parser.add_argument(
        "scope_file",
        type=Path,
        help="Ruta del archivo scope.json.",
    )
    summary_parser.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Formato de salida del resumen.",
    )

    return parser


def handle_init(args: argparse.Namespace) -> int:
    """Ejecuta el comando init."""
    output_dir: Path = args.output
    force: bool = args.force

    scope_json_path = output_dir / "scope.json"
    scope_md_path = output_dir / "PHASE_0_SCOPE.md"

    existing_files = [path for path in [scope_json_path, scope_md_path] if path.exists()]
    if existing_files and not force:
        files_text = ", ".join(str(path) for path in existing_files)
        print(
            f"No se sobrescribieron archivos existentes: {files_text}. "
            "Usa --force si quieres reemplazarlos.",
            file=sys.stderr,
        )
        return 2

    scope = build_default_scope()
    write_scope_json(scope, scope_json_path)
    write_scope_markdown(scope, scope_md_path)

    print(f"Artefactos de Fase 0 creados en: {output_dir.resolve()}")
    print(f"- {scope_json_path}")
    print(f"- {scope_md_path}")
    return 0


def handle_validate(args: argparse.Namespace) -> int:
    """Ejecuta el comando validate."""
    scope = load_scope_json(args.scope_file)
    errors = validate_scope(scope)

    if errors:
        print("El alcance tiene problemas:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("El alcance cumple la Fase 0.")
    return 0


def handle_summary(args: argparse.Namespace) -> int:
    """Ejecuta el comando summary."""
    scope = load_scope_json(args.scope_file)

    if args.format == "json":
        print(json.dumps(scope.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.format == "markdown":
        print(render_scope_markdown(scope))
        return 0

    print(render_text_summary(scope))
    return 0


def render_text_summary(scope: ProjectScope) -> str:
    """Genera un resumen corto en texto plano."""
    profile_lines = [
        f"- {profile.display_name}: {profile.evaluation_target}"
        for profile in scope.supported_app_profiles
    ]
    return "\n".join(
        [
            f"Proyecto: {scope.project_name}",
            f"Versión: {scope.version}",
            f"Foco: {scope.focus}",
            f"Diferenciador: {scope.differentiator}",
            "Tipos de aplicación soportados:",
            *profile_lines,
            f"Siguiente fase: {scope.next_phase}",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada principal de la CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "init": handle_init,
        "validate": handle_validate,
        "summary": handle_summary,
    }

    handler = handlers.get(args.command)
    if handler is None:
        print("Comando no reconocido.", file=sys.stderr)
        return 2

    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

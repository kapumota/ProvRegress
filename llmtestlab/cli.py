"""CLI de LLMTestLab.

Las firmas se mantienen en inglés. Los mensajes visibles se mantienen en español.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llmtestlab.evals import (
    EvalsYamlError,
    build_example_suite,
    load_evals_yaml,
    render_evals_spec_markdown,
    render_evals_summary,
    write_evals_yaml,
)
from llmtestlab.scope import (
    build_default_scope,
    load_scope_json,
    render_scope_markdown,
    render_scope_text,
    validate_scope,
    write_scope_json,
)


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de comandos."""
    parser = argparse.ArgumentParser(
        prog="llmtestlab",
        description="Herramientas de diseño para LLMTestLab.",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Genera artefactos de Fase 0.")
    init_parser.add_argument("--output", type=Path, default=Path("."), help="Directorio de salida.")
    init_parser.add_argument("--force", action="store_true", help="Sobrescribe archivos existentes.")

    validate_parser = subparsers.add_parser("validate", help="Valida scope.json de Fase 0.")
    validate_parser.add_argument("path", type=Path, help="Ruta del archivo scope.json.")

    summary_parser = subparsers.add_parser("summary", help="Resume scope.json de Fase 0.")
    summary_parser.add_argument("path", type=Path, help="Ruta del archivo scope.json.")
    summary_parser.add_argument(
        "--format",
        choices=["text", "markdown"],
        default="text",
        help="Formato de salida.",
    )

    evals_parser = subparsers.add_parser("evals", help="Comandos de Fase 1 para evals.yaml.")
    evals_subparsers = evals_parser.add_subparsers(dest="evals_command")

    evals_init_parser = evals_subparsers.add_parser("init", help="Genera un evals.yaml de ejemplo.")
    evals_init_parser.add_argument(
        "--profile",
        choices=["customer_support", "invoice_extractor", "rag_bot"],
        required=True,
        help="Perfil de ejemplo a generar.",
    )
    evals_init_parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals.yaml"),
        help="Ruta del evals.yaml de salida.",
    )
    evals_init_parser.add_argument("--force", action="store_true", help="Sobrescribe si existe.")

    evals_validate_parser = evals_subparsers.add_parser("validate", help="Valida un evals.yaml.")
    evals_validate_parser.add_argument("path", type=Path, help="Ruta del evals.yaml.")

    evals_summary_parser = evals_subparsers.add_parser("summary", help="Resume un evals.yaml.")
    evals_summary_parser.add_argument("path", type=Path, help="Ruta del evals.yaml.")
    evals_summary_parser.add_argument(
        "--format",
        choices=["text", "markdown"],
        default="text",
        help="Formato de salida.",
    )

    evals_spec_parser = evals_subparsers.add_parser("spec", help="Genera la especificación de evals.yaml.")
    evals_spec_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ruta de salida. Si se omite, imprime en consola.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la CLI y devuelve código de salida."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return handle_phase_zero_init(args.output, args.force)
    if args.command == "validate":
        return handle_phase_zero_validate(args.path)
    if args.command == "summary":
        return handle_phase_zero_summary(args.path, args.format)
    if args.command == "evals":
        return handle_evals_command(args)

    parser.print_help()
    return 1


def handle_phase_zero_init(output: Path, force: bool) -> int:
    """Genera archivos de alcance de Fase 0."""
    output.mkdir(parents=True, exist_ok=True)
    scope_path = output / "scope.json"
    markdown_path = output / "PHASE_0_SCOPE.md"

    if not force and (scope_path.exists() or markdown_path.exists()):
        print("No se sobrescribieron archivos existentes. Usa --force para reemplazarlos.")
        return 2

    scope = build_default_scope()
    write_scope_json(scope, scope_path)
    markdown_path.write_text(render_scope_markdown(scope), encoding="utf-8")
    print(f"Artefactos de Fase 0 creados en: {output}")
    return 0


def handle_phase_zero_validate(path: Path) -> int:
    """Valida un archivo scope.json."""
    try:
        scope = load_scope_json(path)
    except Exception as exc:
        print(f"No se pudo leer el alcance: {exc}")
        return 1

    errors = validate_scope(scope)
    if errors:
        print("El alcance no cumple la Fase 0:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("El alcance cumple la Fase 0.")
    return 0


def handle_phase_zero_summary(path: Path, output_format: str) -> int:
    """Muestra resumen de Fase 0."""
    try:
        scope = load_scope_json(path)
    except Exception as exc:
        print(f"No se pudo leer el alcance: {exc}")
        return 1

    if output_format == "markdown":
        print(render_scope_markdown(scope), end="")
    else:
        print(render_scope_text(scope), end="")
    return 0


def handle_evals_command(args: argparse.Namespace) -> int:
    """Despacha comandos de Fase 1."""
    if args.evals_command == "init":
        return handle_evals_init(args.profile, args.output, args.force)
    if args.evals_command == "validate":
        return handle_evals_validate(args.path)
    if args.evals_command == "summary":
        return handle_evals_summary(args.path, args.format)
    if args.evals_command == "spec":
        return handle_evals_spec(args.output)

    print("Debes indicar un subcomando de evals: init, validate, summary o spec.")
    return 1


def handle_evals_init(profile: str, output: Path, force: bool) -> int:
    """Genera un evals.yaml de ejemplo."""
    if output.exists() and not force:
        print("No se sobrescribió evals.yaml existente. Usa --force para reemplazarlo.")
        return 2

    try:
        suite = build_example_suite(profile)
        write_evals_yaml(suite, output)
    except EvalsYamlError as exc:
        print(str(exc))
        return 1

    print(f"evals.yaml creado en: {output}")
    return 0


def handle_evals_validate(path: Path) -> int:
    """Valida un evals.yaml."""
    try:
        load_evals_yaml(path)
    except EvalsYamlError as exc:
        print(str(exc))
        return 1

    print("El archivo evals.yaml es válido para Fase 1.")
    return 0


def handle_evals_summary(path: Path, output_format: str) -> int:
    """Muestra un resumen de evals.yaml."""
    try:
        suite = load_evals_yaml(path)
    except EvalsYamlError as exc:
        print(str(exc))
        return 1

    print(render_evals_summary(suite, output_format), end="")
    return 0


def handle_evals_spec(output: Path | None) -> int:
    """Genera la especificación de evals.yaml."""
    spec = render_evals_spec_markdown()
    if output is None:
        print(spec, end="")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(spec, encoding="utf-8")
    print(f"Especificación creada en: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

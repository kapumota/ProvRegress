"""CLI de LLMTestLab para Fase 0, Fase 1 y Fase 2."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from typer.testing import CliRunner

from llmtestlab.evals import (
    EvalsYamlError,
    build_example_suite,
    load_evals_yaml,
    render_evals_spec_markdown,
    render_evals_summary,
    write_evals_yaml,
)
from llmtestlab.reports import render_console_report, render_run_summary
from llmtestlab.runner import RunnerError, load_run_result, run_suite_file, write_run_result
from llmtestlab.scope import (
    build_default_scope,
    load_scope_json,
    render_scope_markdown,
    render_scope_text,
    validate_scope,
    write_scope_json,
)

app = typer.Typer(help="CLI para validar, ejecutar y reportar pruebas de LLMTestLab.", add_completion=False)
evals_app = typer.Typer(help="Comandos de Fase 1 para evals.yaml.", add_completion=False)
app.add_typer(evals_app, name="evals")


@app.command()
def init(
    output: Path = typer.Option(Path("."), "--output", "-o", help="Directorio de salida."),
    force: bool = typer.Option(False, "--force", help="Sobrescribe archivos existentes."),
) -> None:
    """Genera artefactos de alcance de Fase 0."""
    output.mkdir(parents=True, exist_ok=True)
    scope_path = output / "scope.json"
    markdown_path = output / "PHASE_0_SCOPE.md"

    if not force and (scope_path.exists() or markdown_path.exists()):
        typer.echo("No se sobrescribieron archivos existentes. Usa --force para reemplazarlos.")
        raise typer.Exit(code=2)

    scope = build_default_scope()
    write_scope_json(scope, scope_path)
    markdown_path.write_text(render_scope_markdown(scope), encoding="utf-8")
    typer.echo(f"Artefactos de Fase 0 creados en: {output}")


@app.command()
def validate(path: Path) -> None:
    """Valida scope.json o evals.yaml según el contenido del archivo."""
    if looks_like_evals_yaml(path):
        validate_evals_file(path, "El archivo evals.yaml es válido.")
        return
    validate_scope_file(path)


@app.command()
def summary(
    path: Path,
    output_format: str = typer.Option("text", "--format", help="Formato text o markdown."),
) -> None:
    """Muestra resumen de scope.json de Fase 0."""
    if output_format not in {"text", "markdown"}:
        typer.echo("El formato debe ser text o markdown.")
        raise typer.Exit(code=1)
    try:
        scope = load_scope_json(path)
    except Exception as exc:
        typer.echo(f"No se pudo leer el alcance: {exc}")
        raise typer.Exit(code=1) from exc

    if output_format == "markdown":
        typer.echo(render_scope_markdown(scope), nl=False)
    else:
        typer.echo(render_scope_text(scope), nl=False)


@app.command()
def run(
    path: Path,
    output: Path = typer.Option(Path("results.json"), "--output", "-o", help="Ruta del JSON de resultados."),
    provider: str = typer.Option("candidate", "--provider", help="Provider a ejecutar."),
) -> None:
    """Ejecuta cada test de evals.yaml y guarda resultados JSON."""
    try:
        result = run_suite_file(path, provider_name=provider)
        write_run_result(result, output)
    except (EvalsYamlError, RunnerError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    typer.echo(render_run_summary(result), nl=False)
    typer.echo(f"Resultados guardados en: {output}")
    if result.summary.failed > 0:
        raise typer.Exit(code=1)


@app.command()
def report(path: Path) -> None:
    """Muestra un reporte desde results.json."""
    try:
        result = load_run_result(path)
    except RunnerError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(render_console_report(result), nl=False)


@evals_app.command("init")
def evals_init(
    profile: str = typer.Option(..., "--profile", help="Perfil: customer_support, invoice_extractor o rag_bot."),
    output: Path = typer.Option(Path("evals.yaml"), "--output", "-o", help="Ruta del evals.yaml."),
    force: bool = typer.Option(False, "--force", help="Sobrescribe si existe."),
) -> None:
    """Genera un evals.yaml de ejemplo."""
    if output.exists() and not force:
        typer.echo("No se sobrescribió evals.yaml existente. Usa --force para reemplazarlo.")
        raise typer.Exit(code=2)
    try:
        suite = build_example_suite(profile)
        write_evals_yaml(suite, output)
    except EvalsYamlError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"evals.yaml creado en: {output}")


@evals_app.command("validate")
def evals_validate(path: Path) -> None:
    """Valida un evals.yaml."""
    validate_evals_file(path, "El archivo evals.yaml es válido para Fase 1.")


@evals_app.command("summary")
def evals_summary(
    path: Path,
    output_format: str = typer.Option("text", "--format", help="Formato text o markdown."),
) -> None:
    """Muestra un resumen de evals.yaml."""
    if output_format not in {"text", "markdown"}:
        typer.echo("El formato debe ser text o markdown.")
        raise typer.Exit(code=1)
    try:
        suite = load_evals_yaml(path)
    except EvalsYamlError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(render_evals_summary(suite, output_format), nl=False)


@evals_app.command("spec")
def evals_spec(output: Path | None = typer.Option(None, "--output", "-o", help="Ruta de salida.")) -> None:
    """Genera la especificación de evals.yaml."""
    spec = render_evals_spec_markdown()
    if output is None:
        typer.echo(spec, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(spec, encoding="utf-8")
    typer.echo(f"Especificación creada en: {output}")


def validate_scope_file(path: Path) -> None:
    """Valida un archivo scope.json."""
    try:
        scope = load_scope_json(path)
    except Exception as exc:
        typer.echo(f"No se pudo leer el alcance: {exc}")
        raise typer.Exit(code=1) from exc

    errors = validate_scope(scope)
    if errors:
        typer.echo("El alcance no cumple la Fase 0:")
        for error in errors:
            typer.echo(f"- {error}")
        raise typer.Exit(code=1)
    typer.echo("El alcance cumple la Fase 0.")


def validate_evals_file(path: Path, success_message: str) -> None:
    """Valida un archivo evals.yaml y muestra un mensaje estable."""
    try:
        load_evals_yaml(path)
    except EvalsYamlError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(success_message)


def looks_like_evals_yaml(path: Path) -> bool:
    """Detecta si el archivo parece ser evals.yaml."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return False
    except FileNotFoundError:
        return False
    return isinstance(data, dict) and {"suite", "providers", "tests"}.issubset(data)


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la CLI desde tests o desde consola."""
    runner = CliRunner()
    result = runner.invoke(app, argv or [])
    if result.output:
        typer.echo(result.output, nl=False)
    return int(result.exit_code)

"""CLI entrypoints for context-archive (ctxa)."""

from __future__ import annotations

import typer

from context_archive import __version__

app = typer.Typer(
    name="ctxa",
    help="Portable AI Project Context Compiler with incremental change journaling.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    """Print package version and exit."""
    if value:
        typer.echo(f"ctxa {__version__}")
        raise typer.Exit(0)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the ctxa version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Portable AI Project Context Compiler (ctxa)."""
    _ = version


@app.command()
def version() -> None:
    """Display the installed ctxa version."""
    typer.echo(f"ctxa {__version__}")

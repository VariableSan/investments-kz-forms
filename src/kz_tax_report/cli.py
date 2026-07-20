"""Command-line entry point for the tax report application."""

from pathlib import Path
from typing import Annotated

import typer

from kz_tax_report.config import get_rules_path
from kz_tax_report.app_service import calculate_files
from kz_tax_report.tax_engine import RulesError

app = typer.Typer(no_args_is_help=True)


@app.callback()
def run(
    ibkr: Annotated[
        Path, typer.Option(..., exists=True, readable=True, help="IBKR CSV")
    ],
    freedom: Annotated[
        Path, typer.Option(..., exists=True, readable=True, help="Freedom PDF")
    ],
    f1042s: Annotated[
        Path, typer.Option(..., exists=True, readable=True, help="1042-S PDF")
    ],
    year: Annotated[int, typer.Option(..., min=2000, help="Tax year")],
    out: Annotated[Path, typer.Option(..., help="Output XLSX path")],
    rules: Annotated[
        Path | None, typer.Option("--rules", exists=True, readable=True)
    ] = None,
) -> None:
    """Calculate traceable inputs for Kazakhstan tax declaration forms."""

    rules_path = rules or get_rules_path(year)
    try:
        report = calculate_files(
            year=year,
            ibkr_path=ibkr,
            freedom_path=freedom,
            f1042s_path=f1042s,
            rules_path=rules_path,
            xlsx_path=out,
            markdown_path=out.with_suffix(".md"),
        )
    except (OSError, RulesError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    markdown_path = out.with_suffix(".md")
    typer.echo(f"Wrote {out}")
    typer.echo(f"Wrote {markdown_path}")
    for warning in report.warnings:
        typer.echo(f"WARNING: {warning}", err=True)


def main() -> None:
    """Run the command-line application."""

    app()


if __name__ == "__main__":
    main()

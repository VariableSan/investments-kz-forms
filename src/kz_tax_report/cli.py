"""Command-line entry point for the tax report application."""

from pathlib import Path
import typer

from kz_tax_report.app_service import calculate_files
from kz_tax_report.tax_engine import RulesError

app = typer.Typer(no_args_is_help=True)


@app.callback()
def run(
    ibkr: Path = typer.Option(..., exists=True, readable=True, help="IBKR CSV"),  # noqa: B008
    freedom: Path | None = typer.Option(  # noqa: B008
        None, exists=True, readable=True, help="Optional Freedom PDF"
    ),
    annual_rates: Path = typer.Option(  # noqa: B008
        ..., "--annual-rates", exists=True, readable=True, help="NBK annual-rate XLSX"
    ),
    year: int = typer.Option(..., min=2000, help="Tax year"),  # noqa: B008
    out: Path = typer.Option(..., help="Output XLSX path"),  # noqa: B008
    f1042s: Path | None = typer.Option(  # noqa: B008
        None, "--f1042s", exists=True, readable=True, help="Optional 1042-S PDF"
    ),
) -> None:
    """Calculate traceable inputs for Kazakhstan tax declaration forms."""

    try:
        report = calculate_files(
            year=year,
            ibkr_path=ibkr,
            freedom_path=freedom,
            annual_rates_path=annual_rates,
            f1042s_path=f1042s,
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

"""Command-line entry point for the tax report application."""

import typer

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Calculate traceable inputs for Kazakhstan tax declaration forms."""


if __name__ == "__main__":
    app()

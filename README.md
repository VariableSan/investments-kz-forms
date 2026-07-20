# Kazakhstan Investment Tax Declaration Tool

Local-first Python 3.12 tooling for preparing traceable inputs for Kazakhstan
Form 270.00 / Appendix 270.01 from IBKR and Freedom Bank reports.

The project is currently in foundation development. The calculation pipeline
will be implemented CLI-first. A browser UI is planned as a later NiceGUI
phase and is not exposed by the current Compose file.

## Privacy Boundary

Brokerage reports contain financial data and personal identifiers. Keep real
reports under `data/`, which is excluded from Git and Docker build contexts.
Only synthetic, de-identified fixtures may be committed under `tests/fixtures`.
This project never submits data to a tax authority or stores it in the cloud.

## Prerequisites

- Python 3.12
- `uv`
- Docker and Docker Compose are optional for batch execution

```bash
uv sync
uv run python --version
```

## TDD And Ruff Workflow

Every behavior change follows a red-green-refactor loop:

1. Write one focused failing pytest test using synthetic fixture data.
2. Implement the smallest production change that makes it pass.
3. Run the focused test, then the complete suite.
4. Run Ruff lint and the non-mutating formatter check.

```bash
make test
make lint
make format-check
```

`make format` and `make lint-fix` are explicit mutating commands. Ruff is
configured in `pyproject.toml`, targets Python 3.12, and is the single project
formatter and linter.

## Available Reports

The local sample directory contains four observed report types:

- IBKR Activity Statement CSV: primary source for dividends, withholding,
	trades, positions, and IBKR's realized P&L section.
- IBKR Dividend Report HTML: optional independent dividend cross-check.
- IRS Form 1042-S PDF: foreign income and US withholding confirmation.
- Freedom Bank brokerage PDF: ETN summary and transaction ledger.

The CSV, 1042-S PDF, and Freedom PDF are the planned core inputs. The HTML
report is optional and must not be required for a normal run.

## CLI

The CLI entry point is scaffolded but calculation modules are still under
construction. The intended invocation is:

```bash
uv run kz-tax-report --ibkr path/to/activity.csv \
	--freedom path/to/freedom.pdf \
	--f1042s path/to/1042s.pdf \
	--year 2025 \
	--out output/report.xlsx
```

Generated reports will include source-row provenance, reconciliation warnings,
and a Markdown summary for manual entry. No electronic filing is supported.

## Docker Batch Mode

The current Compose service is for CLI batch execution and mounts inputs
read-only:

```bash
mkdir -p output
docker compose run --rm app --help
```

The future web UI may be published to the LAN without built-in authentication,
as explicitly selected for this project. That deployment would allow any
reachable LAN peer to access uploaded PII and must never be treated as
internet-safe.

## Tax Rules Disclaimer

This is software for calculation assistance, not tax or legal advice. Rates,
treaty treatment, exemptions, and Form 270.01 mappings must be verified against
the applicable Kazakhstan Tax Code and official instructions for each year.
Year-specific rules will be versioned in YAML and calculations will refuse
unapproved or incomplete rule files.

## Plans

The durable implementation context is in `tmp/plans/00-overview.md`. Attach it
to every future coding session. Numbered plans describe the foundation,
parsers, external sources and FIFO, tax/report CLI, and deferred web UI phases.

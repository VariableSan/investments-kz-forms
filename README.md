# Kazakhstan Investment Tax Declaration Tool

Local-first Python 3.12 tooling for preparing traceable inputs for Kazakhstan
Form 270.00 / Appendix 270.01 from IBKR and Freedom Bank reports.

The project provides both a CLI and a local NiceGUI browser workflow. Both
paths use the same parsers and report model. The browser workflow assigns each
connection an opaque, owner-bound job directory with restrictive permissions.
Jobs are cleaned up by a configurable TTL so downloads are not invalidated by
browser disconnects. Rules edited in the browser are session-only and are
never written back to the bundled YAML.

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

The CLI calculates a source-traceable report and writes both XLSX and Markdown
outputs. Rules must be explicitly approved and can be supplied with `--rules`:

```bash
uv run kz-tax-report --ibkr path/to/activity.csv \
	--freedom path/to/freedom.pdf \
	--f1042s path/to/1042s.pdf \
	--year 2025 \
	--rules path/to/approved-rules-2025.yaml \
	--out output/report.xlsx
```

Generated reports include source-row provenance, reconciliation warnings, and a
Markdown summary for manual entry. The bundled year file is intentionally
unapproved until its official citation and values have been reviewed. No
electronic filing is supported.

## Docker Batch Mode

The current Compose service is for CLI batch execution and mounts inputs
read-only:

```bash
mkdir -p output
docker compose run --rm app --help
```

Runtime settings can be supplied through environment variables. Copy
`example.env` to `.env` before using Docker Compose and adjust the values that
depend on the deployment. The application keeps built-in fallback values when
these variables are absent or empty. Explicit CLI options such as `--rules`
still take precedence over environment settings.

Supported application variables include `KZ_TAX_REPORT_NBK_URL`,
`KZ_TAX_REPORT_NBK_TIMEOUT`, `KZ_TAX_REPORT_NBK_CACHE_PATH`, and
`KZ_TAX_REPORT_RULES_DIR`. Browser artifact policy is controlled by
`KZ_TAX_REPORT_ARTIFACT_DIR`, `KZ_TAX_REPORT_ARTIFACT_MODE`,
`KZ_TAX_REPORT_ARTIFACT_TTL_SECONDS`, `KZ_TAX_REPORT_MAX_UPLOAD_BYTES`, and
`KZ_TAX_REPORT_MAX_JOB_BYTES`. `INPUTS_HOST_DIR` and `OUTPUT_HOST_DIR` control
the host-side Compose mounts.

The web UI may be published to the LAN without built-in authentication, as
explicitly selected for this project. That deployment allows any reachable LAN
peer to access uploaded PII and must never be treated as internet-safe.
The local Docker web profile mounts `OUTPUT_HOST_DIR` at `/outputs`; after a
successful calculation the UI both downloads the reports in the browser and
writes collision-safe XLSX/Markdown copies to that mount. These copies contain
financial data and should be removed according to your local retention policy.

For local Docker use, create the output directory before starting the service
and make it writable by the image's non-root UID (`10001`):

```bash
mkdir -p output
chown 10001:10001 output
make docker-web
```

The `hosted` Compose profile intentionally has no host output mount. It streams
browser downloads from TTL-managed job directories and removes expired jobs;
it does not publish a static report directory. Start it with
`docker compose --profile hosted up web-hosted`. The local profile uses a
default 24-hour TTL, while the hosted profile defaults to one hour. Both
profiles enforce per-file and per-job upload limits. Compose health checks
probe the UI root endpoint every 30 seconds.

## Browser UI

Run the local UI on `127.0.0.1:8080`:

```bash
make web
```

For a LAN deployment using Compose, review the privacy warning and run:

```bash
make docker-build
make docker-web
```

The UI accepts an IBKR CSV, Freedom Bank PDF, and 1042-S PDF, then shows the
calculated totals and reconciliation warnings before offering XLSX and
Markdown downloads. The Tax rules panel starts with the year-specific YAML,
provides a separate manual `Approved` toggle, and materializes edits only in
the current session. It does not transmit files to a tax authority or cloud
service.

## Tax Rules Disclaimer

This is software for calculation assistance, not tax or legal advice. Rates,
treaty treatment, exemptions, and Form 270.01 mappings must be verified against
the applicable Kazakhstan Tax Code and official instructions for each year.
Year-specific rules will be versioned in YAML and calculations will refuse
unapproved or incomplete rule files.

## Plans

The durable implementation context is in `tmp/plans/00-overview.md`. Attach it
to every future coding session. Numbered plans describe the foundation,
parsers, external sources and FIFO, tax/report CLI, and web UI phases.

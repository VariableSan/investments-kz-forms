# Kazakhstan Investment Tax Declaration Tool

Local-first Python 3.12 tooling for preparing traceable inputs for Kazakhstan
Form 270.00 / Appendix 270.01 from IBKR and Freedom Bank reports.

The project provides both a CLI and a local NiceGUI browser workflow. Both
paths use the same parsers and report model. The browser workflow assigns each
connection an opaque, owner-bound job directory with restrictive permissions.
Jobs are cleaned up by a configurable TTL so downloads are not invalidated by
browser disconnects. Rules edited in the browser are session-only and are
never written back to the bundled YAML.

## License And Disclaimer

This project is available under the PolyForm Noncommercial License 1.0.0. It
is source-available and may not be used for commercial purposes; it is not an
OSI-certified open-source license. The software is calculation assistance, not
tax or legal advice. Verify every source, rule, form line, and final declaration
before filing. The author and operator accept no responsibility for filing
correctness.

The optional ISIN prefill reads only exact matches from the uploaded IBKR
report. It makes no external requests. Missing or ambiguous values require
manual completion. The application never submits a declaration electronically.

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

The CSV, annual-rate XLSX, and Freedom PDF are the required inputs. The 1042-S
PDF is optional and enables reconciliation plus a foreign-tax-credit check.
The HTML report is optional and must not be required for a normal run.

## CLI

The CLI calculates a source-traceable report and writes both XLSX and Markdown
outputs. The annual-rate workbook is downloaded manually from the official NBK
page configured by `KZ_TAX_REPORT_NBK_DOWNLOAD_URL`:

```bash
uv run kz-tax-report --ibkr path/to/activity.csv \
	--freedom path/to/freedom.pdf \
	--annual-rates path/to/2025-rates.xlsx \
	--year 2025 \
	--out output/report.xlsx
```

Add `--f1042s path/to/1042s.pdf` when the form is available. Without it, IBKR
withholding is shown as reference only and is not used as a foreign-tax credit.
Generated reports include source-row provenance, annual-rate workbook
provenance, 270.01 values, 270.04 asset preparation, input fingerprint, and
warnings. Foreign tax credit amounts from 1042-S are converted from USD to KZT
using the supplied annual-rate workbook before the configured cap is applied.
No electronic filing is supported. Reports based on unapproved tax rules are
marked `DRAFT / NOT FOR FILING`.

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

The only NBK setting is `KZ_TAX_REPORT_NBK_DOWNLOAD_URL`; the application does
not fetch or cache government rates. Browser artifact policy is controlled by
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
`docker compose --profile hosted up web-hosted` after setting every hosted
variable in `.env`. The origin binds only to loopback so Cloudflare Tunnel (or
an equivalent private reverse proxy) remains the only public ingress. Compose
health checks probe `/healthz` every 30 seconds; the application root itself
requires a valid Cloudflare Access token.

### Invite-Only Hosted Profile

Set `KZ_TAX_REPORT_MODE=hosted`, the Access issuer, audience, JWKS URL,
HTTPS public URL, a random session secret of at least 32 bytes,
`KZ_TAX_REPORT_TRUST_PROXY=true`, and explicit positive TTL/upload limits. The
process refuses to start when any of these values is missing or insecure.
Cloudflare Access must enforce the invite-only email policy and pass its
signed `CF_Authorization` cookie; the application also accepts a Bearer token
for API-style clients. Unsigned identity headers and application passwords are
not trusted.

Deploy the image pulled from GHCR through Dokploy, attach a Cloudflare Tunnel
to the private container port, and keep the origin firewall closed. Store the
issuer, audience, JWKS URL, public URL, session secret, and limits as Dokploy
secrets/environment values, never in the image. Use the health check at
`/healthz`. Jobs and reports are isolated by authenticated subject, deleted by
TTL cleanup, and are not persisted to a host output mount. Initial delivery
does not use R2: reports are streamed directly from the ephemeral job
directory, which keeps the retention and authorization surface small.

The server necessarily sees plaintext PDF and CSV contents while parsing. This
is an intentional hosted risk, not a zero-knowledge design; only invited
identities should be allowed through Access.

### Dokploy Compose File

For Dokploy, paste `docker-compose.prod.yml` into the Compose editor. The file
pulls `ghcr.io/variablesan/investments-kz-forms:latest` by default; set
`KZ_TAX_REPORT_IMAGE` when deploying a different tag. Add these values to the
Dokploy environment/secrets before deploying:

- `KZ_TAX_REPORT_ACCESS_ISSUER`
- `KZ_TAX_REPORT_ACCESS_AUDIENCE`
- `KZ_TAX_REPORT_ACCESS_JWKS_URL`
- `KZ_TAX_REPORT_SESSION_SECRET` (at least 32 bytes)
- `KZ_TAX_REPORT_PUBLIC_URL`
- `KZ_TAX_REPORT_ARTIFACT_TTL_SECONDS`
- `KZ_TAX_REPORT_MAX_UPLOAD_BYTES`
- `KZ_TAX_REPORT_MAX_JOB_BYTES`

The service listens on internal port `8080`; configure the Dokploy domain or
Cloudflare Tunnel to route to that port. The production file uses hosted mode,
an ephemeral job directory, and no host output mount. Keep Cloudflare Access
as the only public ingress and set its policy to invite-only.

## Browser UI

Run the local UI on `127.0.0.1:8080`:

```bash
make web
```

`make web` loads the project `.env` before starting the native UI. Running
`uv run kz-tax-report-ui` directly does not load `.env`; export variables in
the shell first when using that form.

For a LAN deployment using Compose, review the privacy warning and run:

```bash
make docker-build
make docker-web
```

The UI accepts an IBKR CSV, Freedom Bank PDF and annual-rate XLSX, with an
optional 1042-S PDF. It shows calculated totals, 270.04 asset preparation and
warnings before offering XLSX and Markdown downloads. Tax rules are internal
year-specific YAML configuration and are not edited in the browser. The app
does not transmit files to a tax authority or download government data.

## Tax Rules Disclaimer

This is software for calculation assistance, not tax or legal advice. Rates,
treaty treatment, exemptions, and Form 270.01 mappings must be verified against
the applicable Kazakhstan Tax Code and official instructions for each year.
Year-specific rules are versioned in YAML and should be verified before filing.

## Plans

The durable implementation context is in `tmp/plans/00-overview.md`. Attach it
to every future coding session. Numbered plans describe the foundation,
parsers, external sources and FIFO, tax/report CLI, and web UI phases.

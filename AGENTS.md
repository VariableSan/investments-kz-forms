# AGENTS.md

## Project
Local CLI tool that parses IBKR + Freedom Bank (KZ) brokerage reports and
computes figures for Kazakhstan personal income tax Form 270.00/270.01.
No e-filing, no cloud — local-only, handles PII/financial data.

## Stack
- Python 3.12, managed with `uv` (use `uv add <pkg>`, `uv run <cmd>`,
  never `pip install` directly).
- Key deps: pandas, pdfplumber, pypdf, requests, pydantic, openpyxl, pytest.

## Commands
- Install: `uv sync`
- Run CLI: `uv run kz-tax-report --ibkr <csv> --freedom <pdf> --f1042s <pdf> --year <YYYY> --out report.xlsx`
- Test: `uv run pytest -q`
- Lint/format: `uv run ruff check . && uv run ruff format .`
- Quality gate: `make test && make lint && make format-check`
- Formatter configuration lives in `pyproject.toml`; use `make format` only
  when intentionally applying formatting changes.

## Development workflow
- Work test-first: write a focused failing pytest, implement the smallest
  change, run the focused test, then the complete suite and Ruff checks.
- Use a `src/kz_tax_report/` package and external `tests/` directory.
- Commit `uv.lock`; manage dependencies with `uv add`, never direct `pip install`.
- Tests may contain only synthetic, de-identified fixtures. Real reports under
  `data/` are ignored and must never be copied into tests or Docker images.
- Attach `tmp/plans/00-overview.md` to every implementation session and update
  the relevant numbered plan as work progresses.

## Runtime boundaries
- The current Docker Compose service runs the CLI with read-only input mounts;
  it does not expose a web port.
- A future NiceGUI phase may expose the UI to the LAN without built-in
  authentication. This is a deliberate PII risk and is never internet-safe.
- No external tax-system submission, cloud storage, or unreviewed tax rules.

## Module map
- `ibkr_parser.py` — parses multi-section IBKR Activity Statement CSV.
- `f1042s_parser.py` — parses IRS Form 1042-S PDF(s).
- `freedom_parser.py` — parses Freedom Bank "Инвестиционная валюта Freedom" PDF.
- `nbk_rates.py` — fetches/caches National Bank of Kazakhstan FX rates.
- `fifo.py` — generic FIFO lot-matching for realized gains.
- `tax_engine.py` — applies KZ tax rules; rates/brackets live in
  `tax_rules_<year>.yaml`, never hardcoded in logic.
- `report_builder.py` — builds XLSX + markdown summary mapped to Form
  270.01 line items.
- `cli.py` — entry point.

## Conventions
- Every number in the output must cite its source row (file + row id).
  Never emit a bare number without traceability.
- Do not hardcode tax rates, treaty withholding rates, or NBK URLs inside
  business logic — put them in config/YAML.
- Reconcile IBKR dividend/withholding totals against 1042-S totals; raise
  a visible warning on mismatch, don't silently swallow it.
- Add a pytest fixture-based test for any new parser before merging.
- Never add code that submits/transmits data to any external tax system.

## Data quirks to remember
- IBKR CSV: one file, many sections, each row starts with
  `<SectionName>,<Header|Data>,...` — split by section name first.
- IBKR realized gains are precomputed per-symbol in the
  "Реализованная и нереализованная П/У" section — prefer this over
  re-deriving FIFO from Trades unless doing a cross-check.
- Freedom ETN purchases (cashback) have profit=0; profit only appears on
  `Продажа` (sale) rows — FIFO only needed if sales exist in the period.
- Freedom ETN gains are tax-exempt (AIX-listed) but must still be
  reported then adjusted to zero in Form 270.01 — never just omit them.
- 1042-S `Recipient's foreign taxpayer identification number` = KZ ИИН,
  use it to validate the PDF belongs to the expected taxpayer.

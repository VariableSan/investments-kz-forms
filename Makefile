SHELL := /bin/sh

YEAR ?= 2025
IBKR ?=
FREEDOM ?=
F1042S ?=
OUT ?= output/report.xlsx

.PHONY: install test test-one lint format-check lint-fix format run web docker-build docker-cli docker-web

install:
	uv sync

test:
	uv run pytest -q

test-one:
	uv run pytest -q $(TEST)

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

lint-fix:
	uv run ruff check --fix .

format:
	uv run ruff format .

run:
	uv run kz-tax-report --year $(YEAR) --ibkr $(IBKR) --freedom $(FREEDOM) --f1042s $(F1042S) --out $(OUT)

web:
	uv run kz-tax-report-ui

docker-build:
	docker build -t kz-tax-report:local .

docker-cli:
	docker compose run --rm app --help

docker-web:
	docker compose --profile web up web
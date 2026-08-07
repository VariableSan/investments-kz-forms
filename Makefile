SHELL := /bin/sh

YEAR ?= 2025
IBKR ?=
FREEDOM ?=
F1042S ?=
ANNUAL_RATES ?=
OUT ?= output/report.xlsx

.PHONY: help install test test-one lint format-check lint-fix format run web docker-build docker-cli docker-web docker-down docker-web-down docker-hosted-down

help: ## Показать все доступные команды
	@awk 'BEGIN {FS = ":.*##"; printf "Доступные команды:\n\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  make %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Установить зависимости через uv
	uv sync

test: ## Запустить весь набор тестов
	uv run pytest -q

test-one: ## Запустить выбранный тест или файл: make test-one TEST=...
	uv run pytest -q $(TEST)

lint: ## Проверить код Ruff
	uv run ruff check .

format-check: ## Проверить форматирование Ruff
	uv run ruff format --check .

lint-fix: ## Автоматически исправить замечания Ruff
	uv run ruff check --fix .

format: ## Отформатировать код Ruff
	uv run ruff format .

run: ## Запустить CLI-расчёт
	uv run kz-tax-report --year $(YEAR) --ibkr $(IBKR) $(if $(FREEDOM),--freedom $(FREEDOM),) --annual-rates $(ANNUAL_RATES) $(if $(F1042S),--f1042s $(F1042S),) --out $(OUT)

web: ## Запустить браузерный интерфейс
	set -a; [ ! -f .env ] || . ./.env; set +a; exec uv run kz-tax-report-ui

docker-build: ## Собрать Docker-образ
	docker build -t kz-tax-report:local .

docker-cli: ## Запустить CLI в Docker
	docker compose run --rm app --help

docker-web: ## Запустить локальный веб-интерфейс Docker
	docker compose --profile web up web

docker-down: ## Остановить Docker-сервисы
	docker compose down

docker-web-down: ## Остановить локальный веб-интерфейс Docker
	docker compose --profile web down

docker-hosted-down: ## Остановить hosted Docker-профиль
	docker compose --profile hosted down
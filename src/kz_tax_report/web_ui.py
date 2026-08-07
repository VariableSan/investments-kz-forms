"""Русский браузерный интерфейс для подготовки формы 270."""

import os
import secrets
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse
from nicegui import app, events, ui

from kz_tax_report.app_service import (
    ArtifactJobManager,
    ArtifactPolicy,
    InputValidationError,
    export_artifacts,
)
from kz_tax_report.config import (
    get_app_mode,
    get_freedom_reports_url,
    get_hosted_configuration,
    get_ibkr_reports_url,
    get_nbk_download_url,
)
from kz_tax_report.hosted_security import (
    get_authenticated_subject,
    install_hosted_security,
)


_artifact_manager: ArtifactJobManager | None = None


def _get_artifact_manager() -> ArtifactJobManager:
    global _artifact_manager
    if _artifact_manager is None:
        _artifact_manager = ArtifactJobManager(ArtifactPolicy.from_environment())
    return _artifact_manager


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/artifacts/{job_id}/{filename}")
async def download_artifact(job_id: str, filename: str) -> FileResponse:
    if filename not in {"form-270-report.xlsx", "form-270-report.md"}:
        raise HTTPException(status_code=404, detail="Артефакт не найден")
    try:
        job = _get_artifact_manager().get_for_download(
            job_id, get_authenticated_subject()
        )
    except InputValidationError as error:
        raise HTTPException(status_code=404, detail="Артефакт не найден") from error
    artifact = job.workspace.root / filename
    if not artifact.is_file():
        raise HTTPException(status_code=404, detail="Артефакт не найден")
    return FileResponse(artifact, filename=filename)


def _owner() -> str:
    authenticated = get_authenticated_subject()
    if authenticated:
        return authenticated
    owner = app.storage.user.get("owner")
    if not owner:
        owner = uuid4().hex
        app.storage.user["owner"] = owner
    return owner


def _result_snapshot(report: object) -> dict[str, object]:
    metrics = [
        {"label": label, "value": str(value)}
        for label, value in (
            ("Дивиденды, тенге", report.taxable_dividends),
            ("Реализованная прибыль, тенге", report.taxable_realized_gains),
            ("Освобождённый доход, тенге", report.exempt_realized_gains),
            ("Налог к уплате, тенге", report.tax_due),
        )
    ]
    declaration_rows = [
        {
            "label": report.rules.form_labels.get(
                "dividends", "Валовые иностранные дивиденды"
            ),
            "amount": str(report.taxable_dividends),
            "line": report.rules.dividends_line,
            "status": "рассчитано",
        },
        {
            "label": report.rules.form_labels.get(
                "realized_gains", "Налогооблагаемая прибыль от продажи"
            ),
            "amount": str(report.taxable_realized_gains),
            "line": report.rules.realized_gains_line,
            "status": "рассчитано",
        },
        *[
            {
                "label": item.label,
                "amount": str(item.amount),
                "line": item.form_line,
                "status": item.status,
            }
            for item in report.declaration_items
        ],
    ]
    freedom_isin = str(report.freedom_isin or "")
    asset_rows = []
    for asset in report.assets:
        asset_isin = asset.get("isin", "")
        is_freedom_asset = (
            report.freedom_report_uploaded
            and freedom_isin
            and asset_isin == freedom_isin
        )
        asset_rows.append(
            {
                "asset": ("Freedom: " if is_freedom_asset else "")
                + (asset.get("symbol", "") or asset.get("asset_class", "")),
                "isin": asset_isin or "ввести вручную",
                "quantity": str(asset.get("quantity", "")),
                "country": asset.get("country", "") or "ввести вручную",
                "currency": asset.get("currency", ""),
                "source": f"{asset.get('source_file', '')}:{asset.get('source_row', '')}",
                "status": ("ДОБАВИТЬ В 270.04" if is_freedom_asset else "IBKR"),
            }
        )
    if report.freedom_report_uploaded and not any(
        row["isin"] == freedom_isin for row in asset_rows
    ):
        asset_rows.append(
            {
                "asset": "Freedom: валюта",
                "isin": freedom_isin or "не найден в Freedom PDF",
                "quantity": "—",
                "country": "ввести вручную",
                "currency": "",
                "source": "Freedom PDF",
                "status": "ДОБАВИТЬ В 270.04",
            }
        )
    return {
        "year": report.year,
        "metrics": metrics,
        "declaration_rows": declaration_rows,
        "asset_rows": asset_rows,
        "freedom_report_uploaded": report.freedom_report_uploaded,
        "freedom_isin": report.freedom_isin,
        "warnings": list(report.warnings),
        "foreign_tax_credit_notice": any(
            value.category == "1042s_gross_income" for value in report.values
        ),
    }


def _render_result(
    result_area: ui.column,
    snapshot: dict[str, object],
    exported_paths: tuple[object, object] | None,
    job_id: str,
) -> None:
    result_area.clear()
    with result_area:
        if exported_paths:
            ui.label(
                f"Локальные копии: {exported_paths[0]} и {exported_paths[1]}"
            ).classes("text-sm text-gray-600")
        ui.label(f"Результат за {snapshot['year']} год").classes("text-2xl font-bold")
        with ui.row().classes("w-full flex-wrap gap-3"):
            for metric in snapshot["metrics"]:
                with ui.card().classes("metric min-w-52 grow"):
                    ui.label(metric["label"]).classes("text-sm text-gray-600")
                    ui.label(metric["value"]).classes("text-2xl font-bold")
        with ui.card().classes("w-full bg-white border border-stone-200"):
            ui.label("Данные для переноса в 270.01").classes("text-xl font-bold")
            ui.table(
                columns=[
                    {"name": "label", "label": "Показатель", "field": "label"},
                    {"name": "amount", "label": "Сумма, тенге", "field": "amount"},
                    {"name": "line", "label": "Строка", "field": "line"},
                    {"name": "status", "label": "Статус", "field": "status"},
                ],
                rows=snapshot["declaration_rows"],
                row_key="label",
            ).classes("w-full")
        with ui.card().classes("w-full bg-white border border-stone-200"):
            ui.label("Активы на 31 декабря для 270.04").classes("text-xl font-bold")
            if snapshot.get("freedom_report_uploaded"):
                freedom_isin = snapshot.get("freedom_isin")
                ui.label(
                    "Freedom не из IBKR: эту строку проверьте и добавьте в 270.04. ISIN: "
                    + (
                        str(freedom_isin)
                        if freedom_isin
                        else "не найден в загруженном отчёте"
                    )
                ).classes("text-sm text-gray-600")
            ui.table(
                columns=[
                    {"name": "asset", "label": "Инструмент", "field": "asset"},
                    {"name": "isin", "label": "ISIN", "field": "isin"},
                    {"name": "quantity", "label": "Количество", "field": "quantity"},
                    {"name": "country", "label": "Страна", "field": "country"},
                    {"name": "currency", "label": "Валюта", "field": "currency"},
                    {"name": "source", "label": "Источник", "field": "source"},
                    {"name": "status", "label": "Пометка", "field": "status"},
                ],
                rows=snapshot["asset_rows"],
                row_key="asset",
            ).classes("w-full")
        if snapshot["warnings"]:
            with ui.card().classes("w-full bg-red-50 border border-red-200"):
                ui.label("Нужна ручная проверка").classes("font-bold")
                for warning in snapshot["warnings"]:
                    ui.label(warning).classes("text-sm")
        if snapshot["foreign_tax_credit_notice"]:
            with ui.card().classes("w-full bg-amber-50 border border-amber-300"):
                ui.label(
                    "Проверьте применение иностранного налогового кредита"
                ).classes("font-bold text-amber-950")
                ui.label(
                    "Корректная форма 1042-S может позволять уменьшить ИПН на "
                    "иностранный налоговый кредит по применимым правилам РК, но "
                    "не означает автоматического освобождения дивидендов. "
                    "Проверьте действующее законодательство РК и свои обстоятельства. "
                    "Программа не является налоговой или юридической консультацией "
                    "и не несёт ответственности за решение о декларировании."
                ).classes("text-sm text-amber-950")
        with ui.row().classes("gap-3"):
            ui.button(
                "Скачать XLSX",
                icon="download",
                on_click=lambda: ui.download(
                    f"/artifacts/{job_id}/form-270-report.xlsx"
                ),
            )
            ui.button(
                "Скачать Markdown",
                icon="description",
                on_click=lambda: ui.download(f"/artifacts/{job_id}/form-270-report.md"),
            )


@ui.page("/")
def index() -> None:
    artifact_manager = _get_artifact_manager()
    owner = _owner()
    previous_job_id = app.storage.user.get("job_id")
    try:
        job = artifact_manager.get(previous_job_id, owner) if previous_job_id else None
    except InputValidationError:
        job = None
    if job is None:
        job = artifact_manager.create(owner)
        app.storage.user["job_id"] = job.job_id
    workspace = job.workspace

    with ui.tabs().classes("w-full") as navigation_tabs:
        ui.tab("Расчёт", icon="calculate")
        ui.tab("История", icon="history")
    calculation_shell = ui.column().classes("w-full")
    history_shell = ui.column().classes("page-shell w-full p-6 gap-4")
    history_shell.set_visibility(False)
    with history_shell:
        ui.label("История расчётов").classes("text-3xl font-bold")
        ui.label(
            "Завершённые расчёты и ссылки на результаты хранятся в течение "
            "настроенного срока. История доступна только владельцу расчётов."
        ).classes("text-gray-600")
        history_content = ui.column().classes("w-full gap-3")

    def open_history(entry: dict[str, object]) -> None:
        snapshot = entry.get("snapshot")
        if not isinstance(snapshot, dict):
            ui.notify("Снимок этого расчёта недоступен", type="negative")
            return
        calculation_shell.set_visibility(True)
        history_shell.set_visibility(False)
        navigation_tabs.set_value("Расчёт")
        _render_result(result_area, snapshot, None, str(entry["job_id"]))

    def render_history() -> None:
        history_content.clear()
        entries = artifact_manager.list_completed(owner)
        with history_content:
            if not entries:
                ui.label("Сохранённых расчётов пока нет.").classes("text-gray-600")
                return
            for entry in entries:
                created_at = datetime.fromtimestamp(
                    float(entry["created_at"])
                ).strftime("%d.%m.%Y %H:%M")
                summary = entry["summary"]
                with ui.card().classes("w-full bg-white border border-stone-200"):
                    ui.label(f"Расчёт за {entry['year']} год от {created_at}").classes(
                        "text-lg font-bold"
                    )
                    ui.label(
                        f"Дивиденды: {summary.get('taxable_dividends', '—')} тенге; "
                        f"реализованная прибыль: {summary.get('taxable_realized_gains', '—')} тенге; "
                        f"налог к уплате: {summary.get('tax_due', '—')} тенге"
                    ).classes("text-sm text-gray-700")
                    with ui.row().classes("gap-3"):
                        ui.button(
                            "Открыть расчёт",
                            icon="visibility",
                            on_click=lambda entry=entry: open_history(entry),
                        )
                        ui.button(
                            "Скачать XLSX",
                            icon="download",
                            on_click=lambda job_id=entry["job_id"]: ui.download(
                                f"/artifacts/{job_id}/form-270-report.xlsx"
                            ),
                        )
                        ui.button(
                            "Скачать Markdown",
                            icon="description",
                            on_click=lambda job_id=entry["job_id"]: ui.download(
                                f"/artifacts/{job_id}/form-270-report.md"
                            ),
                        )

    with history_shell:
        ui.button("Обновить историю", icon="refresh", on_click=render_history)

    def switch_tab(event: object) -> None:
        selected = getattr(event, "value", None)
        is_history = selected == "История"
        calculation_shell.set_visibility(not is_history)
        history_shell.set_visibility(is_history)
        if is_history:
            render_history()

    navigation_tabs.on_value_change(switch_tab)
    ui.add_head_html(
        """
        <style>
          body { background: #f4f1ea; color: #1f2825; }
          .page-shell { max-width: 900px; margin: 0 auto; }
          .metric { background: #fffdf8; border-left: 4px solid #2b7668; }
        </style>
        """
    )

    with calculation_shell:
        with ui.column().classes("page-shell w-full p-6 gap-5"):
            with ui.card().classes("w-full bg-amber-50 border border-amber-300"):
                ui.label("Важное предупреждение").classes("font-bold text-amber-950")
                ui.label(
                    "Программа помогает подготовить расчёт и не является налоговой "
                    "или юридической консультацией. Проверьте источники, правила и "
                    "итоговую декларацию самостоятельно. Автор и оператор программы "
                    "не несут ответственности за корректность подачи."
                ).classes("text-sm text-amber-950")
            ui.label("Подготовка формы 270").classes("text-4xl font-bold")
            ui.label(
                "Загрузите отчёты брокеров и официальный среднегодовой курс. "
                "Программа подготовит суммы для ручного переноса в декларацию."
            ).classes("text-lg")
            with ui.card().classes("w-full bg-white border border-stone-200"):
                ui.label("Где получить файлы").classes("text-xl font-bold")
                ui.label(
                    "IBKR\n"
                    "1. При необходимости переключите интерфейс IBKR на русский язык.\n"
                    "2. Откройте «Доходность и отчёты» → «Выписка по операциям».\n"
                    "3. Выберите период «Годовой», датой укажите прошлый налоговый год "
                    "и скачайте CSV.\n"
                    "4. Затем откройте «Доходность и отчёты» → «Налоговые документы» → "
                    "«Налоговый год» за прошлый год и скачайте Form 1042-S в PDF. "
                    "Она всегда скачивается на английском языке, это нормально.\n\n"
                    "Freedom\n"
                    "1. В мобильном приложении Freedom SuperApp откройте «Валюта Freedom» "
                    "(обычно раздел находится в верхней правой части экрана).\n"
                    "2. Нажмите «Справки и выписка» → «Отчёт о брокерских сделках».\n"
                    "3. Выберите русский язык и период с 1 января по 31 декабря "
                    "расчётного года, например с 1 января 2025 года по 31 декабря "
                    "2025 года.\n\n"
                    "Среднегодовой курс НБК\n"
                    "Официальный файл со среднегодовыми курсами можно получить на любом "
                    "языке страницы НБК за расчётный год."
                ).classes("whitespace-pre-line text-sm text-gray-700")
                with ui.row().classes("gap-4 flex-wrap"):
                    ui.link(
                        "Страница отчётов IBKR", get_ibkr_reports_url(), new_tab=True
                    )
                    ui.link(
                        "Страница отчётов Freedom",
                        get_freedom_reports_url(),
                        new_tab=True,
                    )
                    ui.link(
                        "Официальная страница НБК", get_nbk_download_url(), new_tab=True
                    )

            year = ui.number(
                "Налоговый год", value=2025, min=2000, max=2100, format="%.0f"
            ).classes("w-48")
            status = ui.label("Загрузите CSV IBKR и среднегодовой курс НБК").classes(
                "text-gray-600"
            )
            auto_fill_isin = ui.checkbox(
                "Заполнить ISIN по загруженному отчёту IBKR (только локально)",
                value=True,
            ).classes("text-sm")
            upload_specs = (
                ("activity.csv", "Отчёт о деятельности IBKR", ".csv"),
                ("freedom.pdf", "Выписка Freedom (необязательно)", ".pdf"),
                ("annual-rates.xlsx", "Среднегодовой курс НБК", ".xlsx"),
                ("f1042s.pdf", "Форма 1042-S (необязательно)", ".pdf"),
            )

            async def handle_upload(
                event: events.UploadEventArguments, logical_name: str
            ) -> None:
                content = await event.file.read()
                workspace.save_upload(logical_name, content)
                status.set_text(f"Получен файл: {logical_name}")

            with ui.row().classes("w-full flex-wrap gap-4"):
                for logical_name, label, accept in upload_specs:
                    ui.upload(
                        label=label,
                        on_upload=lambda event, name=logical_name: handle_upload(
                            event, name
                        ),
                        auto_upload=True,
                    ).props(f"accept={accept}").classes("min-w-64")

            result_area = ui.column().classes("w-full gap-4")

            def calculate() -> None:
                result_area.clear()
                try:
                    artifacts = workspace.calculate(
                        int(year.value), auto_fill_isin=bool(auto_fill_isin.value)
                    )
                    exported_paths = None
                    if artifact_manager.policy.mode == "local":
                        exported_paths = export_artifacts(
                            artifacts.xlsx_path,
                            artifacts.markdown_path,
                            os.environ.get("KZ_TAX_REPORT_OUTPUT_DIR", "output"),
                            f"form-270-{int(year.value)}-{job.job_id[:12]}",
                        )
                except (InputValidationError, OSError, ValueError) as error:
                    status.set_text(str(error))
                    ui.notify(str(error), type="negative")
                    return
                report = artifacts.report
                snapshot = _result_snapshot(report)
                artifact_manager.mark_completed(
                    job,
                    year=report.year,
                    summary={
                        "taxable_dividends": str(report.taxable_dividends),
                        "taxable_realized_gains": str(report.taxable_realized_gains),
                        "tax_due": str(report.tax_due),
                    },
                    snapshot=snapshot,
                )
                status.set_text("Расчёт завершён; проверьте предупреждения")
                _render_result(result_area, snapshot, exported_paths, job.job_id)

            ui.button("Рассчитать", icon="calculate", on_click=calculate).classes(
                "bg-[#2b7668] text-white"
            )


def main() -> None:
    mode = get_app_mode()
    run_options: dict[str, object] = {
        "host": os.environ.get("KZ_TAX_REPORT_UI_HOST", "127.0.0.1"),
        "port": int(os.environ.get("KZ_TAX_REPORT_UI_PORT", "8080")),
        "title": "Подготовка формы 270",
        "reload": False,
        "storage_secret": (os.environ.get("KZ_TAX_REPORT_SESSION_SECRET") or "").strip()
        or secrets.token_urlsafe(32),
    }
    if mode == "hosted":
        settings = get_hosted_configuration()
        install_hosted_security(app)
        run_options["storage_secret"] = str(settings["session_secret"])
    ui.run(**run_options)


if __name__ == "__main__":
    main()

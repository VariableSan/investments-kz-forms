"""Guided local and hosted browser workflow for Form 270 preparation."""

import os
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
    get_hosted_configuration,
    get_nbk_download_url,
    get_ibkr_reports_url,
    get_freedom_reports_url,
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
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        job = _get_artifact_manager().get_for_download(
            job_id, get_authenticated_subject()
        )
    except InputValidationError as error:
        raise HTTPException(status_code=404, detail="Artifact not found") from error
    artifact = job.workspace.root / filename
    if not artifact.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(artifact, filename=filename)


@ui.page("/")
def index() -> None:
    artifact_manager = _get_artifact_manager()
    owner = get_authenticated_subject() or uuid4().hex
    job = artifact_manager.create(owner)
    workspace = job.workspace

    ui.add_head_html(
        """
        <style>
          body { background: #f4f1ea; color: #1f2825; }
          .page-shell { max-width: 900px; margin: 0 auto; }
          .metric { background: #fffdf8; border-left: 4px solid #2b7668; }
        </style>
        """
    )

    with ui.column().classes("page-shell w-full p-6 gap-5"):
        ui.label("Подготовка формы 270").classes("text-4xl font-bold")
        ui.label(
            "Загрузите отчёты брокеров и официальный среднегодовой курс. "
            "Программа подготовит суммы для ручного переноса в декларацию."
        ).classes("text-lg")
        with ui.card().classes("w-full bg-white border border-stone-200"):
            ui.label("1. Скачайте среднегодовой курс").classes("text-xl font-bold")
            ui.label(
                "На странице НБК скачайте XLSX за нужный год и загрузите его ниже."
            ).classes("text-sm text-gray-600")
            ui.link(
                "Официальная страница НБК", get_nbk_download_url(), new_tab=True
            ).classes("text-teal-800 font-bold underline")

        with ui.card().classes("w-full bg-white border border-stone-200"):
            ui.label("2. Скачайте отчёты брокеров").classes("text-xl font-bold")
            with ui.row().classes("gap-4 flex-wrap"):
                ui.link("Отчёты IBKR", get_ibkr_reports_url(), new_tab=True).classes(
                    "text-teal-800 font-bold underline"
                )
                ui.link(
                    "Отчёты Freedom", get_freedom_reports_url(), new_tab=True
                ).classes("text-teal-800 font-bold underline")

        year = ui.number(
            "Налоговый год", value=2025, min=2000, max=2100, format="%.0f"
        ).classes("w-48")
        status = ui.label("Ожидаются три обязательных файла").classes("text-gray-600")
        upload_specs = (
            ("activity.csv", "IBKR Activity Statement", ".csv"),
            ("freedom.pdf", "Выписка Freedom", ".pdf"),
            ("annual-rates.xlsx", "Среднегодовой курс НБК", ".xlsx"),
            ("f1042s.pdf", "1042-S (необязательно)", ".pdf"),
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
                artifacts = workspace.calculate(int(year.value))
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
            status.set_text("Расчёт завершён; проверьте предупреждения")
            with result_area:
                if exported_paths:
                    ui.label(
                        f"Локальные копии: {exported_paths[0]} и {exported_paths[1]}"
                    ).classes("text-sm text-gray-600")
                ui.label(f"Результат за {report.year} год").classes(
                    "text-2xl font-bold"
                )
                with ui.row().classes("w-full flex-wrap gap-3"):
                    for label, value in (
                        ("Дивиденды, KZT", report.taxable_dividends),
                        ("Реализованная прибыль, KZT", report.taxable_realized_gains),
                        ("Освобождённый доход, KZT", report.exempt_realized_gains),
                        ("Налог к уплате, KZT", report.tax_due),
                    ):
                        with ui.card().classes("metric min-w-52 grow"):
                            ui.label(label).classes("text-sm text-gray-600")
                            ui.label(str(value)).classes("text-2xl font-bold")
                if report.warnings:
                    with ui.card().classes("w-full bg-red-50 border border-red-200"):
                        ui.label("Нужна ручная проверка").classes("font-bold")
                        for warning in report.warnings:
                            ui.label(warning).classes("text-sm")
                with ui.row().classes("gap-3"):
                    ui.button(
                        "Скачать XLSX",
                        icon="download",
                        on_click=lambda: ui.download(
                            f"/artifacts/{job.job_id}/form-270-report.xlsx"
                        ),
                    )
                    ui.button(
                        "Скачать Markdown",
                        icon="description",
                        on_click=lambda: ui.download(
                            f"/artifacts/{job.job_id}/form-270-report.md"
                        ),
                    )

        ui.button("Рассчитать", icon="calculate", on_click=calculate).classes(
            "bg-[#2b7668] text-white"
        )


def main() -> None:
    mode = get_app_mode()
    run_options: dict[str, object] = {
        "host": os.environ.get("KZ_TAX_REPORT_UI_HOST", "127.0.0.1"),
        "port": int(os.environ.get("KZ_TAX_REPORT_UI_PORT", "8080")),
        "title": "KZ tax report",
        "reload": False,
    }
    if mode == "hosted":
        settings = get_hosted_configuration()
        install_hosted_security(app)
        run_options["storage_secret"] = str(settings["session_secret"])
    ui.run(**run_options)


if __name__ == "__main__":
    main()

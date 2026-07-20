"""Local NiceGUI interface for reviewing and downloading tax report inputs."""

import os
from tempfile import TemporaryDirectory

from nicegui import app, events, ui

from kz_tax_report.app_service import CalculationWorkspace, InputValidationError
from kz_tax_report.tax_engine import RulesError


def create_workspace() -> tuple[TemporaryDirectory[str], CalculationWorkspace]:
    temporary_directory = TemporaryDirectory(prefix="kz-tax-report-")
    return temporary_directory, CalculationWorkspace(temporary_directory.name)


@ui.page("/")
def index() -> None:
    temporary_directory, workspace = create_workspace()
    state: dict[str, object] = {"artifacts": None}

    def cleanup() -> None:
        workspace.cleanup()
        temporary_directory.cleanup()

    app.on_disconnect(cleanup)

    ui.add_head_html(
        """
        <style>
          body { background: #f4f1ea; color: #1f2825; }
          .page-shell { max-width: 960px; margin: 0 auto; }
          .eyebrow { color: #2b7668; letter-spacing: .08em; text-transform: uppercase; }
          .metric { background: #fffdf8; border-left: 4px solid #d66b4a; }
        </style>
        """
    )

    with ui.column().classes("page-shell w-full p-6 gap-5"):
        ui.label("KZ tax report").classes("eyebrow text-sm font-bold")
        ui.label("Form 270.01 review workspace").classes("text-4xl font-bold")
        ui.label(
            "Upload the three source reports, calculate locally, and inspect every warning before downloading."
        ).classes("text-lg")
        with ui.card().classes("w-full bg-amber-50 border border-amber-200"):
            ui.label(
                "Privacy boundary: this browser service has no built-in authentication. "
                "Anyone who can reach its LAN address may access uploaded financial data."
            ).classes("font-medium")

        with ui.row().classes("w-full items-end gap-4"):
            year = ui.number(
                "Tax year", value=2025, min=2000, max=2100, format="%.0f"
            ).classes("w-40")
            status = ui.label("Waiting for source reports").classes("text-gray-600")

        uploads: dict[str, object] = {}
        upload_specs = (
            ("activity.csv", "IBKR activity CSV", ".csv"),
            ("freedom.pdf", "Freedom Bank PDF", ".pdf"),
            ("f1042s.pdf", "IRS Form 1042-S PDF", ".pdf"),
        )

        async def handle_upload(
            event: events.UploadEventArguments, logical_name: str
        ) -> None:
            content = await event.file.read()
            workspace.save_upload(logical_name, content)
            status.set_text(f"Received {logical_name}")

        with ui.row().classes("w-full flex-wrap gap-4"):
            for logical_name, label, accept in upload_specs:
                uploads[logical_name] = (
                    ui.upload(
                        label=label,
                        on_upload=lambda event, name=logical_name: handle_upload(
                            event, name
                        ),
                        auto_upload=True,
                    )
                    .props(f"accept={accept}")
                    .classes("min-w-64")
                )

        result_area = ui.column().classes("w-full gap-4")

        def calculate() -> None:
            result_area.clear()
            try:
                artifacts = workspace.calculate(int(year.value))
            except (InputValidationError, OSError, RulesError, ValueError) as error:
                status.set_text(str(error))
                ui.notify(str(error), type="negative")
                return
            state["artifacts"] = artifacts
            report = artifacts.report
            status.set_text("Calculation complete; review warnings before downloading")
            with result_area:
                ui.label(f"Results for {report.year}").classes("text-2xl font-bold")
                with ui.row().classes("w-full flex-wrap gap-3"):
                    for label, value in (
                        ("Taxable dividends", report.taxable_dividends),
                        ("Realized gains", report.taxable_realized_gains),
                        ("Exempt gains", report.exempt_realized_gains),
                        ("Tax due", report.tax_due),
                    ):
                        with ui.card().classes("metric min-w-52 grow"):
                            ui.label(label).classes("text-sm text-gray-600")
                            ui.label(str(value)).classes("text-2xl font-bold")
                if report.warnings:
                    with ui.card().classes("w-full bg-red-50 border border-red-200"):
                        ui.label("Warnings require manual review").classes("font-bold")
                        for warning in report.warnings:
                            ui.label(warning).classes("text-sm")
                else:
                    ui.label("No reconciliation warnings").classes(
                        "text-green-700 font-bold"
                    )
                with ui.row().classes("gap-3"):
                    ui.button(
                        "Download XLSX",
                        icon="download",
                        on_click=lambda: ui.download(str(artifacts.xlsx_path)),
                    )
                    ui.button(
                        "Download Markdown",
                        icon="description",
                        on_click=lambda: ui.download(str(artifacts.markdown_path)),
                    )

        ui.button("Calculate report", icon="calculate", on_click=calculate).classes(
            "bg-[#2b7668] text-white"
        )


def main() -> None:
    ui.run(
        host=os.environ.get("KZ_TAX_REPORT_UI_HOST", "127.0.0.1"),
        port=int(os.environ.get("KZ_TAX_REPORT_UI_PORT", "8080")),
        title="KZ tax report",
        reload=False,
    )


if __name__ == "__main__":
    main()

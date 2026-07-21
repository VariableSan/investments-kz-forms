"""Local NiceGUI interface for reviewing and downloading tax report inputs."""

import json
import os
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse
from nicegui import events, ui
from nicegui import app

from kz_tax_report.app_service import (
    ArtifactJobManager,
    ArtifactPolicy,
    InputValidationError,
    export_artifacts,
)
from kz_tax_report.config import (
    get_app_mode,
    get_hosted_configuration,
    get_rules_path,
    get_source_url,
)
from kz_tax_report.hosted_security import (
    get_authenticated_subject,
    install_hosted_security,
)
from kz_tax_report.rules_workspace import RulesDraftError, TaxRulesDraft
from kz_tax_report.source_evidence import fetch_source_evidence
from kz_tax_report.tax_engine import RulesError


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
    state: dict[str, object] = {"artifacts": None}

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
        with ui.card().classes("w-full bg-white border border-stone-200"):
            ui.label("Official sources for the fields below").classes(
                "text-xl font-bold"
            )
            ui.label(
                "Use the current year and applicable language/version. The links are checked against the application's HTTPS allowlist."
            ).classes("text-sm text-gray-600")
            source_link_specs = (
                (
                    "Tax Code",
                    "Tax rate, foreign tax credit and exemption rules",
                    "tax_code",
                ),
                (
                    "Tax forms",
                    "Form 270.01 line numbers and reporting instructions",
                    "form_instructions",
                ),
                (
                    "MRP",
                    "The annual MRP value used in the calculation",
                    "mrp",
                ),
                (
                    "National Bank rates",
                    "NBK FX-rate reference for payment or disposal dates",
                    "nbk_rates",
                ),
                (
                    "Treaty guidance",
                    "Foreign-tax-credit and treaty background",
                    "treaty_credit",
                ),
                (
                    "AIX official list",
                    "Check whether an instrument is listed and potentially exempt",
                    "aix_exemption",
                ),
            )
            with ui.column().classes("w-full gap-2"):
                for label, purpose, source_key in source_link_specs:
                    with ui.row().classes("w-full items-baseline gap-2 flex-wrap"):
                        ui.link(
                            label, get_source_url(source_key), new_tab=True
                        ).classes("text-teal-800 font-bold underline")
                        ui.label(f"- {purpose}").classes("text-sm text-gray-700")
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

        try:
            rules_draft = TaxRulesDraft.from_path(get_rules_path(2025))
        except RulesDraftError as error:
            rules_draft = TaxRulesDraft({"year": 2025, "approved": False})
            ui.notify(str(error), type="negative")

        with ui.expansion("Tax rules for this session", icon="tune").classes("w-full"):
            ui.label(
                "Edits stay in this browser session and never overwrite the bundled YAML. "
                "Approval is a manual acknowledgement, not an automatic legal check."
            ).classes("text-sm text-gray-600")
            with ui.row().classes("w-full flex-wrap gap-4"):
                rules_rate = ui.input(
                    "Tax rate",
                    value=str(rules_draft.document.get("tax", {}).get("rate", "")),
                ).classes("w-40")
                rules_citation = ui.input(
                    "Citation", value=str(rules_draft.document.get("citation", ""))
                ).classes("min-w-80 grow")
                rules_mrp = ui.input(
                    "MRP", value=str(rules_draft.document.get("mrp", ""))
                ).classes("w-40")
                rules_brackets = ui.textarea(
                    "Tax brackets JSON",
                    value=json.dumps(
                        rules_draft.document.get("tax", {}).get("brackets", [])
                    ),
                ).classes("min-w-80 grow")
                rules_approved = ui.checkbox(
                    "Approved", value=rules_draft.approved
                ).classes("pt-2")
            with ui.row().classes("w-full flex-wrap gap-4"):
                income_document = rules_draft.document.get("income", {})
                rules_lines = {
                    key: ui.input(
                        key.replace("_", " ").title(),
                        value=str(income_document.get(key, "")),
                    ).classes("min-w-52 grow")
                    for key in (
                        "dividends_line",
                        "realized_gains_line",
                        "exempt_gains_line",
                    )
                }
            with ui.row().classes("w-full flex-wrap gap-4"):
                label_document = rules_draft.document.get("form_labels", {})
                rules_labels = {
                    key: ui.input(
                        f"Form label: {key.replace('_', ' ')}",
                        value=str(label_document.get(key, "")),
                    ).classes("min-w-52 grow")
                    for key in ("dividends", "realized_gains", "exempt_gains")
                }

            source_keys = (
                "tax_code",
                "form_instructions",
                "mrp",
                "nbk_rates",
                "treaty_credit",
                "aix_exemption",
            )
            source_controls: dict[str, tuple[object, object]] = {}
            with ui.expansion(
                "Official references and evidence", icon="fact_check"
            ).classes("w-full"):
                ui.label(
                    "Fetching records availability and HTTP metadata only. It never reads rates or approves rules."
                ).classes("text-sm text-gray-600")
                source_document = rules_draft.document.get("sources", {})
                evidence_document = rules_draft.document.get("source_evidence", {})
                for source_key in source_keys:
                    with ui.row().classes("w-full items-end gap-3"):
                        citation = ui.input(
                            source_key.replace("_", " ").title(),
                            value=str(source_document.get(source_key, "")),
                        ).classes("grow")
                        evidence_status = ui.label(
                            _evidence_summary(evidence_document.get(source_key, {}))
                        ).classes("text-sm text-gray-600")
                        source_controls[source_key] = (citation, evidence_status)

                        def fetch_evidence(
                            key: str = source_key,
                            status_control: object = evidence_status,
                        ) -> None:
                            evidence = fetch_source_evidence(key)
                            rules_draft.set_source_evidence(evidence.as_dict())
                            status_control.set_text(
                                _evidence_summary(evidence.as_dict())
                            )
                            ui.notify(
                                f"{key}: evidence {'recorded' if evidence.ok else 'failed'}",
                                type="positive" if evidence.ok else "warning",
                            )

                        ui.button(
                            "Fetch evidence",
                            icon="cloud_download",
                            on_click=fetch_evidence,
                        )

            def reset_rules() -> None:
                try:
                    fresh = TaxRulesDraft.from_path(get_rules_path(int(year.value)))
                except (OSError, RulesDraftError, ValueError) as error:
                    ui.notify(str(error), type="negative")
                    return
                rules_draft.document = fresh.document
                rules_rate.value = str(rules_draft.document["tax"]["rate"])
                rules_citation.value = str(rules_draft.document["citation"])
                rules_mrp.value = str(rules_draft.document.get("mrp", ""))
                rules_brackets.value = json.dumps(
                    rules_draft.document.get("tax", {}).get("brackets", [])
                )
                rules_approved.value = rules_draft.approved
                for key, control in rules_lines.items():
                    control.value = str(rules_draft.document["income"][key])
                for key, control in rules_labels.items():
                    control.value = str(
                        rules_draft.document.get("form_labels", {}).get(key, "")
                    )
                for key, (citation, status_control) in source_controls.items():
                    citation.value = str(
                        rules_draft.document.get("sources", {}).get(key, "")
                    )
                    status_control.set_text(
                        _evidence_summary(
                            rules_draft.document.get("source_evidence", {}).get(key, {})
                        )
                    )
                ui.notify("Rules reset from the year-specific YAML")

            ui.button("Reset from YAML", icon="restart_alt", on_click=reset_rules)

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
                rules_draft.set_tax_rate(str(rules_rate.value))
                rules_draft.set_citation(str(rules_citation.value))
                if str(rules_mrp.value).strip():
                    rules_draft.set_mrp(str(rules_mrp.value))
                if str(rules_brackets.value).strip():
                    brackets = json.loads(str(rules_brackets.value))
                    if not isinstance(brackets, list):
                        raise RulesDraftError("Tax brackets must be a JSON list")
                    rules_draft.set_brackets(brackets)
                rules_draft.set_approved(bool(rules_approved.value))
                for key, control in rules_lines.items():
                    rules_draft.set_income_line(key, str(control.value))
                for key, control in rules_labels.items():
                    rules_draft.set_form_label(key, str(control.value))
                for key, (citation, _) in source_controls.items():
                    if str(citation.value).strip():
                        rules_draft.set_source_citation(key, str(citation.value))
                session_rules = rules_draft.materialize(workspace.root / "rules")
                rules_draft.validate_for_calculation(int(year.value), session_rules)
                artifacts = workspace.calculate(
                    int(year.value), rules_path=session_rules
                )
                exported_paths = None
                if artifact_manager.policy.mode == "local":
                    exported_paths = export_artifacts(
                        artifacts.xlsx_path,
                        artifacts.markdown_path,
                        os.environ.get("KZ_TAX_REPORT_OUTPUT_DIR", "/outputs"),
                        f"form-270-{int(year.value)}-{job.job_id[:12]}",
                    )
            except (
                InputValidationError,
                OSError,
                RulesDraftError,
                RulesError,
                ValueError,
            ) as error:
                status.set_text(str(error))
                ui.notify(str(error), type="negative")
                return
            state["artifacts"] = artifacts
            report = artifacts.report
            status.set_text("Calculation complete; review warnings before downloading")
            with result_area:
                if exported_paths is not None:
                    ui.label(
                        f"Local copies: {exported_paths[0]} and {exported_paths[1]}"
                    ).classes("text-sm text-gray-600")
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
                        on_click=lambda: ui.download(
                            f"/artifacts/{job.job_id}/form-270-report.xlsx"
                        ),
                    )
                    ui.button(
                        "Download Markdown",
                        icon="description",
                        on_click=lambda: ui.download(
                            f"/artifacts/{job.job_id}/form-270-report.md"
                        ),
                    )

        ui.button("Calculate report", icon="calculate", on_click=calculate).classes(
            "bg-[#2b7668] text-white"
        )


def _evidence_summary(evidence: object) -> str:
    if not isinstance(evidence, dict) or not evidence:
        return "Not fetched"
    if evidence.get("error"):
        return f"Failed: {evidence['error']}"
    return f"HTTP {evidence.get('status_code', '?')} at {evidence.get('retrieved_at', '?')}"


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
    ui.run(
        **run_options,
    )


if __name__ == "__main__":
    main()

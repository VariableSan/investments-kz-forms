"""Source-traceable Markdown and XLSX report writers."""

from pathlib import Path

from openpyxl import Workbook

from kz_tax_report.tax_engine import TaxReport


def write_xlsx(report: TaxReport, path: str | Path) -> None:
    """Write summary, values, and warnings sheets to an XLSX file."""

    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    summary.append(["Form 270.01 input", "Amount", "Source rule line"])
    summary_rows = [
        ("Taxable dividends", report.taxable_dividends, report.rules.dividends_line),
        (
            "Taxable realized gains",
            report.taxable_realized_gains,
            report.rules.realized_gains_line,
        ),
        (
            "Exempt realized gains",
            report.exempt_realized_gains,
            report.rules.exempt_gains_line,
        ),
        ("Tax before foreign credit", report.tax_before_credit, "calculation"),
        ("Foreign tax credit", report.foreign_tax_credit, "calculation"),
        ("Tax due", report.tax_due, "calculation"),
    ]
    for row in summary_rows:
        summary.append(row)

    values = workbook.create_sheet("Values")
    values.append(["Category", "Amount", "Source file", "Source row", "Detail"])
    for value in report.values:
        values.append(
            [
                value.category,
                value.amount,
                value.source_file,
                value.source_row,
                value.source_detail,
            ]
        )

    warnings = workbook.create_sheet("Warnings")
    warnings.append(["Warning"])
    for warning in report.warnings:
        warnings.append([warning])
    workbook.save(path)


def write_markdown(report: TaxReport, path: str | Path) -> None:
    """Write a concise manual-review summary with source references."""

    lines = [
        f"# Form 270.01 inputs for {report.year}",
        "",
        f"Rules citation: {report.rules.citation}",
        "",
        "| Input | Amount | Rule line |",
        "| --- | ---: | --- |",
        f"| Taxable dividends | {report.taxable_dividends} | {report.rules.dividends_line} |",
        f"| Taxable realized gains | {report.taxable_realized_gains} | {report.rules.realized_gains_line} |",
        f"| Exempt realized gains | {report.exempt_realized_gains} | {report.rules.exempt_gains_line} |",
        f"| Tax before foreign credit | {report.tax_before_credit} | calculation |",
        f"| Foreign tax credit | {report.foreign_tax_credit} | calculation |",
        f"| Tax due | {report.tax_due} | calculation |",
        "",
        "## Source values",
        "",
        "| Category | Amount | Source |",
        "| --- | ---: | --- |",
    ]
    lines.extend(
        f"| {value.category} | {value.amount} | {value.source_file}:{value.source_row} |"
        for value in report.values
    )
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in report.warnings or ("None",))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

"""Shared calculation service for CLI and local browser workflows."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from kz_tax_report.config import get_rules_path
from kz_tax_report.f1042s_parser import parse_f1042s
from kz_tax_report.freedom_parser import parse_freedom_report
from kz_tax_report.ibkr_parser import parse_activity_statement
from kz_tax_report.report_builder import write_markdown, write_xlsx
from kz_tax_report.tax_engine import TaxReport, calculate_report, load_rules


class InputValidationError(ValueError):
    """Raised when a calculation session is missing a required input."""


@dataclass(frozen=True)
class CalculationArtifacts:
    """Generated files and the in-memory report for one calculation."""

    report: TaxReport
    xlsx_path: Path
    markdown_path: Path


class CalculationWorkspace:
    """Own uploaded inputs and generated reports for one isolated session."""

    REQUIRED_INPUTS = ("activity.csv", "freedom.pdf", "f1042s.pdf")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_upload(self, filename: str, content: bytes) -> Path:
        """Save an upload under a known logical filename."""

        safe_name = Path(filename).name
        if safe_name not in self.REQUIRED_INPUTS:
            raise InputValidationError(f"Unsupported upload: {filename}")
        destination = self.root / safe_name
        destination.write_bytes(content)
        return destination

    def validate_inputs(self, year: int) -> None:
        """Validate required files and the year-specific rules file."""

        missing = [
            name for name in self.REQUIRED_INPUTS if not (self.root / name).is_file()
        ]
        if missing:
            names = ", ".join(missing)
            raise InputValidationError(f"Missing required inputs: {names}")
        rules_path = get_rules_path(year)
        if not rules_path.is_file():
            raise InputValidationError(
                f"Tax rules file not found for {year}: {rules_path}"
            )

    def calculate(
        self, year: int, rules_path: str | Path | None = None
    ) -> CalculationArtifacts:
        """Parse the session inputs and write traceable report artifacts."""

        self.validate_inputs(year)
        report = calculate_files(
            year=year,
            ibkr_path=self.root / "activity.csv",
            freedom_path=self.root / "freedom.pdf",
            f1042s_path=self.root / "f1042s.pdf",
            xlsx_path=self.root / "form-270-report.xlsx",
            markdown_path=self.root / "form-270-report.md",
            rules_path=rules_path,
        )
        return CalculationArtifacts(
            report, self.root / "form-270-report.xlsx", self.root / "form-270-report.md"
        )

    def cleanup(self) -> None:
        """Remove this session's inputs and generated outputs."""

        shutil.rmtree(self.root, ignore_errors=True)


def calculate_files(
    *,
    year: int,
    ibkr_path: str | Path,
    freedom_path: str | Path,
    f1042s_path: str | Path,
    xlsx_path: str | Path,
    markdown_path: str | Path,
    rules_path: str | Path | None = None,
) -> TaxReport:
    """Calculate and write a report from three source files."""

    report = calculate_report(
        year=year,
        rules=load_rules(rules_path or get_rules_path(year)),
        ibkr_sections=parse_activity_statement(ibkr_path),
        freedom_transactions=parse_freedom_report(freedom_path),
        f1042s_records=parse_f1042s(f1042s_path),
    )
    Path(xlsx_path).parent.mkdir(parents=True, exist_ok=True)
    write_xlsx(report, xlsx_path)
    write_markdown(report, markdown_path)
    return report

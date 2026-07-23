"""Shared calculation service for CLI and local browser workflows."""

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from kz_tax_report.annual_rates import AnnualRateProvider
from kz_tax_report.config import (
    get_app_mode,
    get_artifact_mode,
    get_artifact_root,
    get_artifact_ttl_seconds,
    get_max_job_bytes,
    get_max_upload_bytes,
    get_hosted_configuration,
    get_rules_path,
)
from kz_tax_report.f1042s_parser import parse_f1042s
from kz_tax_report.freedom_parser import parse_freedom_report
from kz_tax_report.ibkr_parser import parse_activity_statement
from kz_tax_report.report_builder import write_markdown, write_xlsx
from kz_tax_report.tax_engine import TaxReport, calculate_report, load_rules


class InputValidationError(ValueError):
    """Raised when a calculation session is missing a required input."""


@dataclass(frozen=True)
class ArtifactPolicy:
    root: Path
    mode: str = "local"
    ttl_seconds: float = 86400.0
    max_upload_bytes: int = 25 * 1024 * 1024
    max_job_bytes: int = 75 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.mode not in {"local", "hosted"}:
            raise ValueError("Artifact mode must be local or hosted")
        if (
            self.ttl_seconds <= 0
            or self.max_upload_bytes <= 0
            or self.max_job_bytes <= 0
        ):
            raise ValueError("Artifact limits must be greater than zero")

    @classmethod
    def from_environment(cls) -> "ArtifactPolicy":
        app_mode = get_app_mode()
        hosted = get_hosted_configuration()
        return cls(
            root=get_artifact_root(),
            mode=app_mode if app_mode == "hosted" else get_artifact_mode(),
            ttl_seconds=float(hosted.get("ttl_seconds", get_artifact_ttl_seconds())),
            max_upload_bytes=int(
                hosted.get("max_upload_bytes", get_max_upload_bytes())
            ),
            max_job_bytes=int(hosted.get("max_job_bytes", get_max_job_bytes())),
        )


@dataclass(frozen=True)
class ArtifactJob:
    job_id: str
    owner: str
    created_at: float
    workspace: "CalculationWorkspace"
    metadata_path: Path


class ArtifactJobManager:
    """Create and retain isolated browser jobs independently of page lifetime."""

    def __init__(self, policy: ArtifactPolicy) -> None:
        self.policy = policy
        self.policy.root.mkdir(parents=True, exist_ok=True)
        self.policy.root.chmod(0o700)
        self.cleanup_expired()

    def create(self, owner: str) -> ArtifactJob:
        self.cleanup_expired()
        for _ in range(5):
            job_id = uuid4().hex
            root = self.policy.root / job_id
            try:
                root.mkdir(mode=0o700)
            except FileExistsError:
                continue
            created_at = time.time()
            workspace = CalculationWorkspace(
                root,
                max_upload_bytes=self.policy.max_upload_bytes,
                max_job_bytes=self.policy.max_job_bytes,
            )
            metadata_path = root / "metadata.json"
            job = ArtifactJob(job_id, owner, created_at, workspace, metadata_path)
            self._write_metadata(job)
            return job
        raise OSError("Unable to allocate an artifact workspace")

    def get(self, job_id: str, owner: str) -> ArtifactJob:
        self.cleanup_expired()
        if not job_id or Path(job_id).name != job_id:
            raise InputValidationError("Invalid artifact job id")
        metadata_path = self.policy.root / job_id / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
            raise InputValidationError("Artifact job not found") from error
        if metadata.get("owner") != owner:
            raise InputValidationError("Artifact job ownership check failed")
        workspace = CalculationWorkspace(
            metadata_path.parent,
            max_upload_bytes=self.policy.max_upload_bytes,
            max_job_bytes=self.policy.max_job_bytes,
        )
        return ArtifactJob(
            job_id,
            owner,
            float(metadata["created_at"]),
            workspace,
            metadata_path,
        )

    def get_for_download(self, job_id: str, owner: str | None) -> ArtifactJob:
        """Resolve a download and enforce ownership in hosted mode."""

        if self.policy.mode == "hosted":
            if not owner:
                raise InputValidationError("Artifact ownership is required")
            return self.get(job_id, owner)
        metadata_path = self.policy.root / job_id / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
            raise InputValidationError("Artifact job not found") from error
        return self.get(job_id, str(metadata.get("owner", "")))

    def cleanup_expired(self, now: float | None = None) -> tuple[str, ...]:
        cutoff = (time.time() if now is None else now) - self.policy.ttl_seconds
        removed: list[str] = []
        for metadata_path in self.policy.root.glob("*/metadata.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                created_at = float(metadata["created_at"])
                job_id = metadata_path.parent.name
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if created_at < cutoff:
                shutil.rmtree(metadata_path.parent, ignore_errors=True)
                if not metadata_path.parent.exists():
                    removed.append(job_id)
        return tuple(removed)

    def set_created_at(self, job: ArtifactJob, created_at: float) -> None:
        updated = ArtifactJob(
            job.job_id, job.owner, created_at, job.workspace, job.metadata_path
        )
        self._write_metadata(updated)

    def _write_metadata(self, job: ArtifactJob) -> None:
        job.metadata_path.write_text(
            json.dumps(
                {
                    "job_id": job.job_id,
                    "owner": job.owner,
                    "created_at": job.created_at,
                    "mode": self.policy.mode,
                }
            ),
            encoding="utf-8",
        )
        job.metadata_path.chmod(0o600)


@dataclass(frozen=True)
class CalculationArtifacts:
    """Generated files and the in-memory report for one calculation."""

    report: TaxReport
    xlsx_path: Path
    markdown_path: Path


class CalculationWorkspace:
    """Own uploaded inputs and generated reports for one isolated session."""

    REQUIRED_INPUTS = ("activity.csv", "freedom.pdf", "annual-rates.xlsx")
    OPTIONAL_INPUTS = ("f1042s.pdf",)

    def __init__(
        self,
        root: str | Path,
        *,
        max_upload_bytes: int = 25 * 1024 * 1024,
        max_job_bytes: int = 75 * 1024 * 1024,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.max_upload_bytes = max_upload_bytes
        self.max_job_bytes = max_job_bytes

    def save_upload(self, filename: str, content: bytes) -> Path:
        """Save an upload under a known logical filename."""

        safe_name = Path(filename).name
        if safe_name not in (*self.REQUIRED_INPUTS, *self.OPTIONAL_INPUTS):
            raise InputValidationError(f"Unsupported upload: {filename}")
        if len(content) > self.max_upload_bytes:
            raise InputValidationError(
                f"Upload exceeds maximum upload size of {self.max_upload_bytes} bytes"
            )
        existing_size = sum(
            path.stat().st_size
            for path in (
                self.root / name
                for name in (*self.REQUIRED_INPUTS, *self.OPTIONAL_INPUTS)
            )
            if path.is_file() and path.name != safe_name
        )
        if existing_size + len(content) > self.max_job_bytes:
            raise InputValidationError(
                f"Upload exceeds workspace upload limit of {self.max_job_bytes} bytes"
            )
        destination = self.root / safe_name
        destination.write_bytes(content)
        destination.chmod(0o600)
        return destination

    def validate_inputs(self, year: int, rules_path: str | Path | None = None) -> None:
        """Validate required files and the year-specific rules file."""

        missing = [
            name for name in self.REQUIRED_INPUTS if not (self.root / name).is_file()
        ]
        if missing:
            names = ", ".join(missing)
            raise InputValidationError(f"Missing required inputs: {names}")
        selected_rules_path = (
            Path(rules_path) if rules_path is not None else get_rules_path(year)
        )
        if not selected_rules_path.is_file():
            raise InputValidationError(
                f"Tax rules file not found for {year}: {selected_rules_path}"
            )

    def calculate(
        self, year: int, rules_path: str | Path | None = None
    ) -> CalculationArtifacts:
        """Parse the session inputs and write traceable report artifacts."""

        self.validate_inputs(year, rules_path=rules_path)
        report = calculate_files(
            year=year,
            ibkr_path=self.root / "activity.csv",
            freedom_path=self.root / "freedom.pdf",
            annual_rates_path=self.root / "annual-rates.xlsx",
            f1042s_path=(
                self.root / "f1042s.pdf"
                if (self.root / "f1042s.pdf").is_file()
                else None
            ),
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


def export_artifacts(
    xlsx_path: str | Path,
    markdown_path: str | Path,
    output_dir: str | Path,
    stem: str,
) -> tuple[Path, Path]:
    """Copy completed reports to a configured local output directory."""

    destination_dir = Path(output_dir)
    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe_stem = Path(stem).name
    if not safe_stem or safe_stem in {".", ".."}:
        raise InputValidationError("Report output name must not be empty")
    for suffix in range(1, 10000):
        candidate_stem = safe_stem if suffix == 1 else f"{safe_stem}-{suffix}"
        destinations = (
            destination_dir / f"{candidate_stem}.xlsx",
            destination_dir / f"{candidate_stem}.md",
        )
        if any(destination.exists() for destination in destinations):
            continue
        try:
            for source, destination in zip(
                (xlsx_path, markdown_path), destinations, strict=True
            ):
                file_descriptor = os.open(
                    destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(file_descriptor, "wb") as output_file:
                    with Path(source).open("rb") as input_file:
                        shutil.copyfileobj(input_file, output_file)
        except FileExistsError:
            for destination in destinations:
                destination.unlink(missing_ok=True)
            continue
        return destinations
    raise OSError("Unable to allocate a unique report output name")


def calculate_files(
    *,
    year: int,
    ibkr_path: str | Path,
    freedom_path: str | Path,
    annual_rates_path: str | Path,
    f1042s_path: str | Path | None = None,
    xlsx_path: str | Path,
    markdown_path: str | Path,
    rules_path: str | Path | None = None,
    rate_provider: AnnualRateProvider | None = None,
) -> TaxReport:
    """Calculate and write a report from broker files and an annual-rate workbook."""

    report = calculate_report(
        year=year,
        rules=load_rules(rules_path or get_rules_path(year), require_approved=False),
        ibkr_sections=parse_activity_statement(ibkr_path),
        freedom_transactions=parse_freedom_report(freedom_path),
        f1042s_records=(
            parse_f1042s(f1042s_path)
            if f1042s_path is not None and Path(f1042s_path).is_file()
            else None
        ),
        rate_provider=rate_provider or AnnualRateProvider(annual_rates_path, year),
    )
    Path(xlsx_path).parent.mkdir(parents=True, exist_ok=True)
    write_xlsx(report, xlsx_path)
    write_markdown(report, markdown_path)
    return report

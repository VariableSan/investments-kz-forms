from pathlib import Path

import pytest

from kz_tax_report.app_service import (
    ArtifactJobManager,
    ArtifactPolicy,
    CalculationWorkspace,
    InputValidationError,
    export_artifacts,
)


def test_workspace_stores_only_expected_upload_names(tmp_path: Path) -> None:
    workspace = CalculationWorkspace(tmp_path / "session")

    stored = workspace.save_upload("../../activity.csv", b"csv")

    assert stored == workspace.root / "activity.csv"
    assert stored.read_bytes() == b"csv"

    with pytest.raises(InputValidationError, match="Unsupported upload"):
        workspace.save_upload("secrets.txt", b"private")


def test_workspace_validation_reports_missing_inputs(tmp_path: Path) -> None:
    workspace = CalculationWorkspace(tmp_path / "session")
    workspace.save_upload("activity.csv", b"csv")

    with pytest.raises(InputValidationError, match="freedom.pdf"):
        workspace.validate_inputs(2025)


def test_workspace_validation_checks_explicit_session_rules_path(
    tmp_path: Path,
) -> None:
    workspace = CalculationWorkspace(tmp_path / "session")
    for filename in workspace.REQUIRED_INPUTS:
        workspace.save_upload(filename, b"fixture")

    missing_rules = tmp_path / "session-rules.yaml"

    with pytest.raises(InputValidationError, match="Tax rules file not found"):
        workspace.validate_inputs(2025, rules_path=missing_rules)


def test_export_artifacts_copies_reports_to_output_directory(tmp_path: Path) -> None:
    xlsx = tmp_path / "job" / "report.xlsx"
    markdown = tmp_path / "job" / "report.md"
    xlsx.parent.mkdir()
    xlsx.write_bytes(b"xlsx")
    markdown.write_text("markdown", encoding="utf-8")

    exported = export_artifacts(xlsx, markdown, tmp_path / "output", "report-2025")

    assert exported == (
        tmp_path / "output" / "report-2025.xlsx",
        tmp_path / "output" / "report-2025.md",
    )
    assert exported[0].read_bytes() == b"xlsx"
    assert exported[1].read_text(encoding="utf-8") == "markdown"


def test_artifact_jobs_are_opaque_and_owner_bound(tmp_path: Path) -> None:
    manager = ArtifactJobManager(
        ArtifactPolicy(root=tmp_path / "jobs", mode="local", ttl_seconds=60)
    )

    job = manager.create("connection-a")

    assert job.workspace.root.name == job.job_id
    assert job.workspace.root.parent == tmp_path / "jobs"
    assert job.workspace.root.stat().st_mode & 0o777 == 0o700
    loaded = manager.get(job.job_id, "connection-a")
    assert loaded.job_id == job.job_id
    assert loaded.owner == job.owner
    assert loaded.workspace.root == job.workspace.root
    with pytest.raises(InputValidationError, match="ownership"):
        manager.get(job.job_id, "connection-b")


def test_artifact_jobs_expire_without_touching_other_jobs(tmp_path: Path) -> None:
    manager = ArtifactJobManager(
        ArtifactPolicy(root=tmp_path / "jobs", mode="hosted", ttl_seconds=10)
    )
    old_job = manager.create("old")
    new_job = manager.create("new")
    manager.set_created_at(old_job, 100.0)
    manager.set_created_at(new_job, 195.0)

    removed = manager.cleanup_expired(now=200.0)

    assert removed == (old_job.job_id,)
    assert not old_job.workspace.root.exists()
    assert new_job.workspace.root.exists()


def test_workspace_enforces_per_file_and_total_upload_limits(tmp_path: Path) -> None:
    workspace = CalculationWorkspace(
        tmp_path / "session", max_upload_bytes=4, max_job_bytes=6
    )

    workspace.save_upload("activity.csv", b"1234")
    with pytest.raises(InputValidationError, match="maximum upload size"):
        workspace.save_upload("freedom.pdf", b"12345")
    with pytest.raises(InputValidationError, match="workspace upload limit"):
        workspace.save_upload("freedom.pdf", b"123")


def test_export_artifacts_does_not_overwrite_existing_reports(tmp_path: Path) -> None:
    xlsx = tmp_path / "job" / "report.xlsx"
    markdown = tmp_path / "job" / "report.md"
    xlsx.parent.mkdir()
    xlsx.write_bytes(b"new xlsx")
    markdown.write_text("new markdown", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "report.xlsx").write_bytes(b"old xlsx")
    (output / "report.md").write_text("old markdown", encoding="utf-8")

    exported = export_artifacts(xlsx, markdown, output, "report")

    assert exported[0].name == "report-2.xlsx"
    assert exported[1].name == "report-2.md"
    assert (output / "report.xlsx").read_bytes() == b"old xlsx"

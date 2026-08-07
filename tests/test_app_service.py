from pathlib import Path

import pytest

from kz_tax_report.app_service import (
    ArtifactJobManager,
    ArtifactPolicy,
    CalculationWorkspace,
    InputValidationError,
    _input_fingerprint,
    export_artifacts,
)


def test_workspace_stores_only_expected_upload_names(tmp_path: Path) -> None:
    workspace = CalculationWorkspace(tmp_path / "session")

    stored = workspace.save_upload("../../activity.csv", b"csv")

    assert stored == workspace.root / "activity.csv"
    assert stored.read_bytes() == b"csv"

    with pytest.raises(InputValidationError, match="Unsupported upload"):
        workspace.save_upload("secrets.txt", b"private")


def test_input_fingerprint_changes_when_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "activity.csv"
    source.write_bytes(b"first")

    first = _input_fingerprint(source)
    source.write_bytes(b"second")

    assert first != _input_fingerprint(source)


def test_workspace_validation_reports_missing_inputs(tmp_path: Path) -> None:
    workspace = CalculationWorkspace(tmp_path / "session")
    workspace.save_upload("activity.csv", b"csv")

    with pytest.raises(InputValidationError, match="annual-rates.xlsx"):
        workspace.validate_inputs(2025)


def test_workspace_validation_does_not_require_optional_freedom_or_1042s(
    tmp_path: Path,
) -> None:
    workspace = CalculationWorkspace(tmp_path / "session")
    workspace.save_upload("activity.csv", b"csv")
    workspace.save_upload("annual-rates.xlsx", b"rates")

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


def test_completed_artifact_history_is_owner_bound_and_contains_result_summary(
    tmp_path: Path,
) -> None:
    manager = ArtifactJobManager(
        ArtifactPolicy(root=tmp_path / "jobs", mode="local", ttl_seconds=60)
    )
    first = manager.create("connection-a")
    second = manager.create("connection-b")
    manager.mark_completed(
        first,
        year=2025,
        summary={"tax_due": "123.45", "taxable_dividends": "678.90"},
        snapshot={
            "year": 2025,
            "metrics": [],
            "declaration_rows": [],
            "asset_rows": [],
            "warnings": ["Проверка"],
        },
    )
    for filename in ("form-270-report.xlsx", "form-270-report.md"):
        (first.workspace.root / filename).write_bytes(b"fixture")
    manager.mark_completed(second, year=2024, summary={"tax_due": "9.00"})

    history = manager.list_completed("connection-a")

    assert [item["job_id"] for item in history] == [first.job_id]
    assert history[0]["year"] == 2025
    assert history[0]["summary"] == {
        "tax_due": "123.45",
        "taxable_dividends": "678.90",
    }
    assert history[0]["snapshot"] == {
        "year": 2025,
        "metrics": [],
        "declaration_rows": [],
        "asset_rows": [],
        "warnings": ["Проверка"],
    }


def test_completed_history_ignores_invalid_result_snapshot(tmp_path: Path) -> None:
    manager = ArtifactJobManager(
        ArtifactPolicy(root=tmp_path / "jobs", mode="local", ttl_seconds=60)
    )
    job = manager.create("owner")
    manager.mark_completed(job, year=2025, summary={}, snapshot={"warnings": []})
    for filename in ("form-270-report.xlsx", "form-270-report.md"):
        (job.workspace.root / filename).write_bytes(b"fixture")

    history = manager.list_completed("owner")

    assert history == []


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


def test_expired_artifact_is_reaped_before_lookup(tmp_path: Path) -> None:
    manager = ArtifactJobManager(
        ArtifactPolicy(root=tmp_path / "jobs", mode="hosted", ttl_seconds=10)
    )
    job = manager.create("owner")
    manager.set_created_at(job, 100.0)

    with pytest.raises(InputValidationError, match="not found"):
        manager.get(job.job_id, "owner")


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

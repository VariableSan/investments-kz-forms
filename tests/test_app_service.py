from pathlib import Path

import pytest

from kz_tax_report.app_service import CalculationWorkspace, InputValidationError


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

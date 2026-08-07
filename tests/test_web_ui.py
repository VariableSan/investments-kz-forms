from decimal import Decimal
from types import SimpleNamespace

from kz_tax_report.web_ui import _result_snapshot


def make_report(
    *,
    freedom_report_uploaded: bool,
    freedom_isin: str,
    assets: tuple[dict[str, object], ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        year=2025,
        taxable_dividends=Decimal("0"),
        taxable_realized_gains=Decimal("0"),
        exempt_realized_gains=Decimal("0"),
        tax_due=Decimal("0"),
        rules=SimpleNamespace(
            form_labels={},
            dividends_line="270.01.01",
            realized_gains_line="270.01.02",
        ),
        declaration_items=(),
        assets=assets,
        warnings=(),
        values=(),
        freedom_report_uploaded=freedom_report_uploaded,
        freedom_isin=freedom_isin,
    )


def test_result_snapshot_keeps_freedom_isin_metadata() -> None:
    snapshot = _result_snapshot(
        make_report(freedom_report_uploaded=True, freedom_isin="KZX000002001")
    )

    assert snapshot["freedom_report_uploaded"] is True
    assert snapshot["freedom_isin"] == "KZX000002001"
    assert snapshot["asset_rows"] == [
        {
            "asset": "Freedom: валюта",
            "isin": "KZX000002001",
            "quantity": "—",
            "country": "ввести вручную",
            "currency": "",
            "source": "Freedom PDF",
            "status": "ДОБАВИТЬ В 270.04",
        }
    ]


def test_result_snapshot_keeps_missing_freedom_isin_visible() -> None:
    snapshot = _result_snapshot(
        make_report(freedom_report_uploaded=True, freedom_isin="")
    )

    assert snapshot["freedom_report_uploaded"] is True
    assert snapshot["freedom_isin"] == ""
    assert snapshot["asset_rows"][0]["isin"] == "не найден в Freedom PDF"
    assert snapshot["asset_rows"][0]["status"] == "ДОБАВИТЬ В 270.04"


def test_result_snapshot_marks_existing_freedom_asset_without_duplicate() -> None:
    snapshot = _result_snapshot(
        make_report(
            freedom_report_uploaded=True,
            freedom_isin="KZX000002001",
            assets=(
                {
                    "asset_class": "ETN",
                    "symbol": "",
                    "isin": "KZX000002001",
                    "quantity": Decimal("12"),
                    "country": "",
                    "currency": "USD",
                    "source_file": "freedom.pdf",
                    "source_row": 1,
                },
            ),
        )
    )

    assert len(snapshot["asset_rows"]) == 1
    assert snapshot["asset_rows"][0]["asset"] == "Freedom: ETN"
    assert snapshot["asset_rows"][0]["status"] == "ДОБАВИТЬ В 270.04"

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from kz_tax_report.tax_engine import RulesError, calculate_report, load_rules
from kz_tax_report.config import get_rules_path


class FixedAnnualRates:
    annual = True

    def get_rate(self, rate_date: str, currency: str) -> Decimal:
        assert currency == "USD"
        return Decimal("521.59")


def test_calculate_report_keeps_provenance_and_reconciles_sources(
    tmp_path: Path,
) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
year: 2025
approved: true
citation: Synthetic approved rule for tests
tax:
  rate: '0.10'
  foreign_tax_credit: true
income:
  dividends_line: '270.01.01'
  realized_gains_line: '270.01.02'
  exempt_gains_line: '270.01.03'
""",
        encoding="utf-8",
    )
    sections = {
        "Дивиденды": pd.DataFrame(
            [
                {
                    "currency": "USD",
                    "date": "2025-02-01",
                    "description": "ACME dividend",
                    "amount": 100.0,
                    "source_file": "activity.csv",
                    "source_row": 12,
                }
            ]
        ),
        "Удерживаемый налог": pd.DataFrame(
            [
                {
                    "currency": "USD",
                    "date": "2025-02-01",
                    "description": "ACME withholding",
                    "amount": 8.0,
                    "source_file": "activity.csv",
                    "source_row": 13,
                }
            ]
        ),
        "Реализованная и нереализованная П/У: отчет об эффективности": pd.DataFrame(
            [
                {
                    "asset_class": "STK",
                    "symbol": "ACME",
                    "realized_total": 50.0,
                    "source_file": "activity.csv",
                    "source_row": 31,
                }
            ]
        ),
    }
    freedom = pd.DataFrame(
        [
            {
                "transaction_type": "Продажа",
                "profit": Decimal("20"),
                "source_file": "freedom.pdf",
                "source_page": 2,
                "source_table": 1,
                "source_row": 4,
            }
        ]
    )
    f1042s = pd.DataFrame(
        [
            {
                "income_code": "06",
                "gross_income": Decimal("99"),
                "federal_tax_withheld": Decimal("8"),
                "source_file": "1042-s.pdf",
                "source_page": 1,
                "source_row": 3,
            }
        ]
    )

    result = calculate_report(
        year=2025,
        rules=load_rules(rules_path),
        ibkr_sections=sections,
        freedom_transactions=freedom,
        f1042s_records=f1042s,
        freedom_closing_position={
            "asset_class": "ETN",
            "symbol": "",
            "isin": "KZX000002001",
            "quantity": Decimal("12"),
            "currency": "USD",
            "country": "",
            "source_file": "freedom.pdf",
            "source_page": 1,
            "source_row": 1,
        },
    )

    assert result.taxable_dividends == Decimal("100")
    assert result.taxable_realized_gains == Decimal("50")
    assert result.exempt_realized_gains == Decimal("20")
    assert result.tax_before_credit == Decimal("15")
    assert result.foreign_tax_credit == Decimal("8")
    assert result.tax_due == Decimal("7")
    assert result.values[0].source_file == "activity.csv"
    assert result.values[0].source_row == 12
    assert any(
        "Валовой доход по форме 1042-S" in warning for warning in result.warnings
    )
    assert result.assets[-1] == {
        "asset_class": "ETN",
        "currency": "USD",
        "symbol": "",
        "quantity": Decimal("12"),
        "isin": "KZX000002001",
        "country": "",
        "source_file": "freedom.pdf",
        "source_page": 1,
        "source_row": 1,
    }


def test_zero_quantity_freedom_position_keeps_isin_metadata_without_asset(
    tmp_path: Path,
) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
year: 2025
approved: true
citation: Synthetic approved rule for tests
tax:
  rate: '0.10'
  foreign_tax_credit: true
income:
  dividends_line: '270.01.01'
  realized_gains_line: '270.01.02'
  exempt_gains_line: '270.01.03'
""",
        encoding="utf-8",
    )
    empty_sections = {
        "Дивиденды": pd.DataFrame(
            columns=[
                "currency",
                "date",
                "amount",
                "description",
                "source_file",
                "source_row",
            ]
        ),
        "Удерживаемый налог": pd.DataFrame(
            columns=[
                "currency",
                "date",
                "amount",
                "description",
                "source_file",
                "source_row",
            ]
        ),
        "Реализованная и нереализованная П/У: отчет об эффективности": pd.DataFrame(
            columns=[
                "asset_class",
                "symbol",
                "realized_total",
                "source_file",
                "source_row",
            ]
        ),
    }

    result = calculate_report(
        year=2025,
        rules=load_rules(rules_path),
        ibkr_sections=empty_sections,
        freedom_transactions=pd.DataFrame(columns=["transaction_type", "profit"]),
        f1042s_records=pd.DataFrame(
            columns=["income_code", "gross_income", "federal_tax_withheld"]
        ),
        freedom_report_uploaded=True,
        freedom_closing_position={
            "asset_class": "ETN",
            "symbol": "",
            "isin": "KZX000002001",
            "quantity": Decimal("0"),
            "currency": "USD",
            "country": "",
            "source_file": "freedom.pdf",
            "source_page": 1,
            "source_row": 1,
        },
    )

    assert result.freedom_report_uploaded is True
    assert result.freedom_isin == "KZX000002001"
    assert result.assets == ()


def test_1042s_foreign_tax_credit_is_converted_to_kzt(
    tmp_path: Path,
) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
year: 2025
approved: true
citation: Synthetic approved rule for tests
tax:
  rate: '0.10'
  foreign_tax_credit: true
income:
  dividends_line: '270.01.01'
  realized_gains_line: '270.01.02'
  exempt_gains_line: '270.01.03'
""",
        encoding="utf-8",
    )
    sections = {
        "Дивиденды": pd.DataFrame(
            [
                {
                    "currency": "USD",
                    "date": "2025-02-01",
                    "description": "ACME dividend",
                    "amount": 1000,
                    "source_file": "activity.csv",
                    "source_row": 12,
                }
            ]
        ),
        "Удерживаемый налог": pd.DataFrame(
            columns=[
                "currency",
                "date",
                "description",
                "amount",
                "source_file",
                "source_row",
            ]
        ),
        "Реализованная и нереализованная П/У: отчет об эффективности": pd.DataFrame(
            columns=[
                "asset_class",
                "symbol",
                "realized_total",
                "source_file",
                "source_row",
            ]
        ),
    }
    report = calculate_report(
        year=2025,
        rules=load_rules(rules_path),
        ibkr_sections=sections,
        freedom_transactions=pd.DataFrame(columns=["transaction_type", "profit"]),
        f1042s_records=pd.DataFrame(
            [
                {
                    "income_code": "06",
                    "gross_income": Decimal("100"),
                    "federal_tax_withheld": Decimal("46"),
                    "source_file": "1042-s.pdf",
                    "source_page": 1,
                    "source_row": 3,
                }
            ]
        ),
        rate_provider=FixedAnnualRates(),
    )

    assert report.foreign_tax_credit == Decimal("23993.14")
    withheld = next(
        value
        for value in report.values
        if value.category == "1042s_federal_tax_withheld"
    )
    assert withheld.currency == "USD"
    assert withheld.foreign_amount == Decimal("46.00")
    assert withheld.fx_rate == Decimal("521.59")


def test_reconciliation_uses_total_1042s_income_and_normalizes_withholding_sign(
    tmp_path: Path,
) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
year: 2025
approved: true
citation: Synthetic approved rule for tests
tax:
  rate: '0.10'
  foreign_tax_credit: true
income:
  dividends_line: '270.01.01'
  realized_gains_line: '270.01.02'
  exempt_gains_line: '270.01.03'
""",
        encoding="utf-8",
    )
    sections = {
        "Дивиденды": pd.DataFrame(
            [
                {
                    "currency": "USD",
                    "date": "2025-02-01",
                    "description": "ACME dividend",
                    "amount": 100,
                    "source_file": "activity.csv",
                    "source_row": 12,
                }
            ]
        ),
        "Удерживаемый налог": pd.DataFrame(
            [
                {
                    "currency": "USD",
                    "date": "2025-02-01",
                    "description": "ACME withholding",
                    "amount": -8,
                    "source_file": "activity.csv",
                    "source_row": 13,
                }
            ]
        ),
        "Реализованная и нереализованная П/У: отчет об эффективности": pd.DataFrame(
            columns=[
                "asset_class",
                "symbol",
                "realized_total",
                "source_file",
                "source_row",
            ]
        ),
    }
    f1042s = pd.DataFrame(
        [
            {
                "income_code": "06",
                "gross_income": Decimal("100"),
                "federal_tax_withheld": Decimal("8"),
                "source_file": "1042-s.pdf",
                "source_page": 1,
                "source_row": 3,
            },
            {
                "income_code": "01",
                "gross_income": Decimal("25"),
                "federal_tax_withheld": Decimal("0"),
                "source_file": "1042-s.pdf",
                "source_page": 4,
                "source_row": 3,
            },
        ]
    )

    result = calculate_report(
        year=2025,
        rules=load_rules(rules_path),
        ibkr_sections=sections,
        freedom_transactions=pd.DataFrame(
            columns=["transaction_type", "profit", "source_file", "source_row"]
        ),
        f1042s_records=f1042s,
    )

    assert result.foreign_tax_credit == Decimal("8")
    assert any(
        "Валовой доход по форме 1042-S" in warning for warning in result.warnings
    )
    assert not any(
        "Удержанный федеральный налог по форме 1042-S" in warning
        for warning in result.warnings
    )
    assert any("Код дохода 01 формы 1042-S" in warning for warning in result.warnings)


def test_reconciliation_ignores_sub_dollar_gross_rounding_difference(
    tmp_path: Path,
) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
year: 2025
approved: true
citation: Synthetic approved rule for tests
tax:
  rate: '0.10'
  foreign_tax_credit: true
income:
  dividends_line: '270.01.01'
  realized_gains_line: '270.01.02'
  exempt_gains_line: '270.01.03'
""",
        encoding="utf-8",
    )
    records = pd.DataFrame(
        [
            {
                "income_code": "06",
                "gross_income": Decimal("306"),
                "federal_tax_withheld": Decimal("46"),
                "source_file": "1042-s.pdf",
                "source_page": 1,
                "source_row": 3,
            },
            {
                "income_code": "01",
                "gross_income": Decimal("180"),
                "federal_tax_withheld": Decimal("0"),
                "source_file": "1042-s.pdf",
                "source_page": 4,
                "source_row": 3,
            },
        ]
    )
    report = calculate_report(
        year=2025,
        rules=load_rules(rules_path, require_approved=False),
        ibkr_sections={
            "Дивиденды": pd.DataFrame(
                [
                    {
                        "currency": "USD",
                        "date": "2025-02-01",
                        "description": "dividend",
                        "amount": 485.89,
                        "source_file": "activity.csv",
                        "source_row": 12,
                    }
                ]
            ),
            "Удерживаемый налог": pd.DataFrame(
                [
                    {
                        "currency": "USD",
                        "date": "2025-02-01",
                        "description": "withholding",
                        "amount": 46,
                        "source_file": "activity.csv",
                        "source_row": 13,
                    }
                ]
            ),
            "Реализованная и нереализованная П/У: отчет об эффективности": pd.DataFrame(
                columns=[
                    "Класс актива",
                    "Символ",
                    "Реализованная Всего",
                    "source_file",
                    "source_row",
                ]
            ),
        },
        freedom_transactions=pd.DataFrame(columns=["transaction_type", "profit"]),
        f1042s_records=records,
    )

    assert not any(
        "Валовой доход по форме 1042-S" in warning for warning in report.warnings
    )


def test_unapproved_or_incomplete_rules_refuse_calculation(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "year: 2025\napproved: false\ncitation: pending\n", encoding="utf-8"
    )

    with pytest.raises(RulesError, match="approved"):
        load_rules(rules_path)


def test_bundled_rules_refuse_calculation_until_officially_reviewed() -> None:
    with pytest.raises(RulesError, match="approved"):
        load_rules(get_rules_path(2025))

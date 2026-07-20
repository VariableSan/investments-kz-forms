from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from kz_tax_report.tax_engine import RulesError, calculate_report, load_rules


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
    )

    assert result.taxable_dividends == Decimal("100")
    assert result.taxable_realized_gains == Decimal("50")
    assert result.exempt_realized_gains == Decimal("20")
    assert result.tax_before_credit == Decimal("15")
    assert result.foreign_tax_credit == Decimal("8")
    assert result.tax_due == Decimal("7")
    assert result.values[0].source_file == "activity.csv"
    assert result.values[0].source_row == 12
    assert any("1042-S gross income" in warning for warning in result.warnings)


def test_unapproved_or_incomplete_rules_refuse_calculation(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "year: 2025\napproved: false\ncitation: pending\n", encoding="utf-8"
    )

    with pytest.raises(RulesError, match="approved"):
        load_rules(rules_path)

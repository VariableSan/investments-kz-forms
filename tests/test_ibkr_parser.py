from pathlib import Path

import pandas as pd
import pytest

from kz_tax_report.ibkr_parser import (
    extract_dividends,
    extract_open_positions,
    extract_realized_pnl,
    extract_withholding_tax,
    parse_dividend_report,
    reconcile_dividends,
    parse_activity_statement,
)


@pytest.fixture()
def activity_statement(tmp_path: Path) -> Path:
    path = tmp_path / "activity.csv"
    path.write_text(
        "\n".join(
            [
                "Statement,Header,Field,Value",
                'Statement,Data,Title,"Activity, Statement"',
                "Дивиденды,Header,Валюта,Дата,Описание,Сумма",
                "Дивиденды,Data,USD,2025-01-01,VOO dividend,12.50",
                "Удерживаемый налог,Header,Валюта,Дата,Описание,Сумма",
                "Удерживаемый налог,Data,USD,2025-01-01,VOO tax,-1.88",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_parse_multisection_csv_preserves_rows_and_provenance(
    activity_statement: Path,
) -> None:
    sections = parse_activity_statement(activity_statement)

    assert set(sections) == {"Statement", "Дивиденды", "Удерживаемый налог"}
    assert sections["Statement"].loc[0, "Value"] == "Activity, Statement"
    assert sections["Дивиденды"].loc[0, "source_row"] == 4
    assert sections["Дивиденды"].loc[0, "source_file"] == "activity.csv"


def test_extract_ibkr_tax_inputs_excludes_summary_rows(
    activity_statement: Path,
) -> None:
    sections = parse_activity_statement(activity_statement)

    dividends = extract_dividends(sections)
    withholding = extract_withholding_tax(sections)

    assert dividends.to_dict("records") == [
        {
            "currency": "USD",
            "date": "2025-01-01",
            "description": "VOO dividend",
            "amount": 12.5,
            "source_file": "activity.csv",
            "source_row": 4,
        }
    ]
    assert withholding.loc[0, "amount"] == -1.88
    assert withholding.loc[0, "source_row"] == 6


def test_extract_realized_pnl_uses_symbol_rows_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "realized.csv"
    path.write_text(
        "\n".join(
            [
                "Реализованная и нереализованная П/У: отчет об эффективности,Header,Класс актива,Символ,Коррект. стоимости,Реализованная Всего,Нереализованная Всего,Всего,Код",
                "Реализованная и нереализованная П/У: отчет об эффективности,Data,Акции,VOO,100,25.50,0,25.50,",
                "Реализованная и нереализованная П/У: отчет об эффективности,Data,Всего,,0,25.50,0,25.50,",
            ]
        ),
        encoding="utf-8",
    )

    realized = extract_realized_pnl(parse_activity_statement(path))

    assert realized.to_dict("records") == [
        {
            "asset_class": "Акции",
            "symbol": "VOO",
            "realized_total": 25.5,
            "source_file": "realized.csv",
            "source_row": 2,
        }
    ]


def test_extract_open_positions_returns_summary_rows_for_form_270_04(
    tmp_path: Path,
) -> None:
    path = tmp_path / "positions.csv"
    path.write_text(
        "\n".join(
            [
                "Открытые позиции,Header,DataDiscriminator,Класс актива,Валюта,Символ,Количество",
                "Открытые позиции,Data,Summary,Акции,USD,VOO,13.2724",
                "Открытые позиции,Data,Total,Всего,USD,,13.2724",
            ]
        ),
        encoding="utf-8",
    )

    positions = extract_open_positions(parse_activity_statement(path))

    assert positions.to_dict("records") == [
        {
            "asset_class": "Акции",
            "currency": "USD",
            "symbol": "VOO",
            "quantity": 13.2724,
            "isin": "",
            "country": "",
            "source_file": "positions.csv",
            "source_row": 2,
        }
    ]


def test_parse_optional_html_dividend_report_and_reconcile(tmp_path: Path) -> None:
    path = tmp_path / "dividends.html"
    path.write_text(
        """
        <table id="tblDividendDetail">
          <tr><th>Symbol</th><th>Report Date</th><th>Gross in USD</th><th>Withhold in USD</th></tr>
          <tr><td>VOO</td><td>2025-01-01</td><td>12.50</td><td>1.88</td></tr>
        </table>
        """,
        encoding="utf-8",
    )

    report = parse_dividend_report(path)
    result = reconcile_dividends(
        extract_dividends(
            {
                "Дивиденды": pd.DataFrame(
                    [
                        {
                            "Валюта": "USD",
                            "Дата": "2025-01-01",
                            "Описание": "VOO dividend",
                            "Сумма": "12.50",
                            "source_file": "activity.csv",
                            "source_row": 1,
                        }
                    ]
                )
            }
        ),
        report,
    )

    assert report.loc[0, "source_row"] == 2
    assert result == {"csv_gross": 12.5, "html_gross": 12.5, "difference": 0.0}

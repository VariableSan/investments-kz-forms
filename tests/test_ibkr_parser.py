from pathlib import Path

import pytest

from kz_tax_report.ibkr_parser import parse_activity_statement


@pytest.fixture()
def activity_statement(tmp_path: Path) -> Path:
    path = tmp_path / "activity.csv"
    path.write_text(
        "\n".join(
            [
                "Statement,Header,Field,Value",
                'Statement,Data,Title,"Activity, Statement"',
                "Дивиденды,Header,Symbol,Amount,Currency",
                "Дивиденды,Data,VOO,12.50,USD",
                "Удерживаемый налог,Header,Symbol,Amount,Currency",
                "Удерживаемый налог,Data,VOO,-1.88,USD",
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

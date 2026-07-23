"""Parser for the multi-section IBKR Activity Statement CSV export."""

import csv
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import TextIO

import pandas as pd


DIVIDENDS_SECTION = "Дивиденды"
WITHHOLDING_SECTION = "Удерживаемый налог"
REALIZED_PNL_SECTION = "Реализованная и нереализованная П/У: отчет об эффективности"
SUMMARY_MARKERS = ("Всего", "Всего (все активы)")


def parse_activity_statement(path: str | Path) -> dict[str, pd.DataFrame]:
    """Parse an IBKR statement into one DataFrame per section.

    Each output keeps the original CSV line and file name so downstream
    calculations can cite their source rows.
    """

    source_path = Path(path)
    sections: dict[str, list[dict[str, str | int]]] = {}
    headers: dict[str, list[str]] = {}

    with source_path.open("r", encoding="utf-8-sig", newline="") as source:
        _read_rows(source, source_path.name, sections, headers)

    return {
        section: pd.DataFrame(
            rows, columns=[*headers[section], "source_file", "source_row"]
        )
        for section, rows in sections.items()
    }


def _read_rows(
    source: TextIO,
    source_name: str,
    sections: dict[str, list[dict[str, str | int]]],
    headers: dict[str, list[str]],
) -> None:
    for source_row, row in enumerate(csv.reader(source), start=1):
        if len(row) < 2:
            continue

        section, marker, *values = row
        if marker == "Header":
            if not values or all(not column for column in values):
                raise ValueError(f"Invalid header at {source_name}:{source_row}")
            headers[section] = [
                column or f"unnamed_{index}" for index, column in enumerate(values)
            ]
            sections.setdefault(section, [])
            continue

        if marker != "Data":
            continue
        if section not in headers:
            raise ValueError(f"Data before header at {source_name}:{source_row}")
        if len(values) > len(headers[section]):
            raise ValueError(
                f"Column count mismatch at {source_name}:{source_row}: "
                f"expected {len(headers[section])}, got {len(values)}"
            )
        values.extend([""] * (len(headers[section]) - len(values)))

        record: dict[str, str | int] = dict(zip(headers[section], values, strict=True))
        record["source_file"] = source_name
        record["source_row"] = source_row
        sections[section].append(record)


def extract_dividends(sections: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return dividend detail rows with normalized numeric amounts."""

    return _extract_cash_flow(
        sections,
        DIVIDENDS_SECTION,
        output_columns=("currency", "date", "description", "amount"),
    )


def extract_withholding_tax(sections: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return withholding-tax detail rows with normalized numeric amounts."""

    return _extract_cash_flow(
        sections,
        WITHHOLDING_SECTION,
        output_columns=("currency", "date", "description", "amount"),
    )


def extract_realized_pnl(sections: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return IBKR's precomputed realized P&L for each instrument."""

    frame = _require_section(sections, REALIZED_PNL_SECTION)
    asset_column = _find_column(frame, "Класс актива", "asset_class")
    symbol_column = _find_column(frame, "Символ", "symbol")
    realized_column = _find_column(frame, "Реализованная Всего", "realized_total")
    detail = frame[~frame[asset_column].isin(SUMMARY_MARKERS)].copy()
    detail["realized_total"] = _to_number(detail[realized_column], realized_column)
    return detail.assign(
        asset_class=detail[asset_column],
        symbol=detail[symbol_column],
    )[["asset_class", "symbol", "realized_total", "source_file", "source_row"]]


def extract_open_positions(sections: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return IBKR closing positions with fields useful for Form 270.04."""

    frame = _require_section(sections, "Открытые позиции")
    discriminator = _find_column(frame, "DataDiscriminator", "Тип данных")
    asset_column = _find_column(frame, "Класс актива", "asset_class")
    currency_column = _find_column(frame, "Валюта", "currency")
    symbol_column = _find_column(frame, "Символ", "symbol")
    quantity_column = _find_column(frame, "Количество", "quantity")
    detail = frame[frame[discriminator].astype(str).str.casefold() == "summary"].copy()
    detail["quantity"] = _to_number(detail[quantity_column], quantity_column)
    return detail.assign(
        asset_class=detail[asset_column],
        currency=detail[currency_column],
        symbol=detail[symbol_column],
        isin="",
        country="",
    )[
        [
            "asset_class",
            "currency",
            "symbol",
            "quantity",
            "isin",
            "country",
            "source_file",
            "source_row",
        ]
    ]


def parse_dividend_report(path: str | Path) -> pd.DataFrame:
    """Parse the optional IBKR HTML dividend detail table."""

    source_path = Path(path)
    parser = _DividendTableParser()
    parser.feed(source_path.read_text(encoding="utf-8"))
    if not parser.rows:
        raise ValueError(f"Dividend detail table is missing: {source_path.name}")
    header = parser.rows[0]
    detail_rows = [row for row in parser.rows[1:] if len(row) == len(header)]
    table = pd.DataFrame(detail_rows, columns=header)
    columns = {
        "symbol": _find_column(table, "Symbol"),
        "date": _find_column(table, "Report Date"),
        "gross": _find_column(table, "Gross in USD"),
        "withholding": _find_column(table, "Withhold in USD"),
    }
    result = table.rename(columns={value: key for key, value in columns.items()})[
        [*columns]
    ]
    result["gross"] = result["gross"].map(_html_amount)
    result["withholding"] = result["withholding"].map(_html_amount)
    result["source_file"] = source_path.name
    result["source_row"] = range(2, len(result) + 2)
    return result


class _DividendTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_table = False
        self._in_detail_section = False
        self._in_row = False
        self._in_cell = False
        self._cell: list[str] = []
        self._row: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div" and attributes.get("id") == "tblDividendDetailBody":
            self._in_detail_section = True
        elif tag == "table" and (
            attributes.get("id") == "tblDividendDetail" or self._in_detail_section
        ):
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in {"th", "td"}:
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if self._in_row and self._in_cell and tag in {"th", "td"}:
            self._row.append("".join(self._cell).strip())
            self._in_cell = False
        elif self._in_table and self._in_row and tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
        elif self._in_table and tag == "table":
            self._in_table = False
        elif self._in_detail_section and tag == "div":
            self._in_detail_section = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._in_cell and tag == "br":
            self._cell.append(" ")


def reconcile_dividends(
    csv_dividends: pd.DataFrame, html_dividends: pd.DataFrame
) -> dict[str, float]:
    """Return gross dividend totals and their difference for manual review."""

    csv_gross = float(csv_dividends["amount"].sum())
    html_gross = float(html_dividends["gross"].sum())
    return {
        "csv_gross": csv_gross,
        "html_gross": html_gross,
        "difference": csv_gross - html_gross,
    }


def _html_amount(value: str) -> float:
    matches = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value)
    if not matches:
        raise ValueError(f"Invalid HTML dividend amount: {value!r}")
    return float(matches[-1])


def _extract_cash_flow(
    sections: dict[str, pd.DataFrame],
    section_name: str,
    output_columns: tuple[str, ...],
) -> pd.DataFrame:
    frame = _require_section(sections, section_name)
    columns = {
        "currency": _find_column(frame, "Валюта", "currency"),
        "date": _find_column(frame, "Дата", "date"),
        "description": _find_column(frame, "Описание", "description"),
        "amount": _find_column(frame, "Сумма", "amount"),
    }
    detail = frame[~frame[columns["currency"]].isin(SUMMARY_MARKERS)].copy()
    detail["amount"] = _to_number(detail[columns["amount"]], columns["amount"])
    return detail.assign(
        currency=detail[columns["currency"]],
        date=detail[columns["date"]],
        description=detail[columns["description"]],
    )[[*output_columns, "source_file", "source_row"]]


def _require_section(
    sections: dict[str, pd.DataFrame], section_name: str
) -> pd.DataFrame:
    if section_name not in sections:
        raise ValueError(f"Required IBKR section is missing: {section_name}")
    return sections[section_name]


def _find_column(frame: pd.DataFrame, *candidates: str) -> str:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    raise ValueError(f"Required IBKR column is missing; expected one of {candidates}")


def _to_number(values: pd.Series, column: str) -> pd.Series:
    numbers = pd.to_numeric(values, errors="coerce")
    if numbers.isna().any():
        invalid = values[numbers.isna()].iloc[0]
        raise ValueError(f"Invalid numeric value in {column}: {invalid!r}")
    return numbers

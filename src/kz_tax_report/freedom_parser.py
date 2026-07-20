"""Parse transaction tables from Freedom Bank investment PDFs."""

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import pdfplumber


_ALIASES = {
    "deal_number": ("номер сделки", "deal number"),
    "date": ("дата", "date"),
    "transaction_type": ("тип операции", "операция", "transaction type", "type"),
    "symbol": ("тикер", "символ", "инструмент", "symbol", "ticker"),
    "quantity": ("количество", "quantity", "qty"),
    "profit": ("прибыль", "прибыль/убыток", "profit", "p&l", "p/l"),
    "details": ("детали", "details"),
}
_REQUIRED_COLUMNS = ("date", "transaction_type", "quantity", "profit")


def parse_freedom_report(path: str | Path) -> pd.DataFrame:
    """Return transaction rows with physical PDF table provenance."""

    source_path = Path(path)
    records: list[dict[str, object]] = []
    with pdfplumber.open(source_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                if not table or not table[0]:
                    continue
                headers = [_clean_cell(cell) for cell in table[0]]
                columns = _find_columns(headers)
                missing = [key for key in _REQUIRED_COLUMNS if key not in columns]
                if len(missing) == len(_REQUIRED_COLUMNS):
                    continue
                if missing:
                    missing_names = ", ".join(missing)
                    raise ValueError(
                        "Malformed Freedom transaction table at "
                        f"{source_path.name}:page {page_number},table {table_number}; "
                        f"missing {missing_names}"
                    )
                for row_number, raw_row in enumerate(table[1:], start=2):
                    if not raw_row or not any(_clean_cell(cell) for cell in raw_row):
                        continue
                    if len(raw_row) < len(headers):
                        raw_row = [*raw_row, *([None] * (len(headers) - len(raw_row)))]
                    try:
                        records.append(
                            {
                                "date": _clean_cell(raw_row[columns["date"]]),
                                "transaction_type": _clean_cell(
                                    raw_row[columns["transaction_type"]]
                                ),
                                "symbol": _column_value(raw_row, columns, "symbol"),
                                "deal_number": _column_value(
                                    raw_row, columns, "deal_number"
                                ),
                                "quantity": _decimal(
                                    raw_row[columns["quantity"]], "quantity"
                                ),
                                "profit": _decimal(
                                    raw_row[columns["profit"]], "profit"
                                ),
                                "details": _column_value(raw_row, columns, "details"),
                                "source_file": source_path.name,
                                "source_page": page_number,
                                "source_table": table_number,
                                "source_row": row_number,
                            }
                        )
                    except (IndexError, ValueError) as error:
                        raise ValueError(
                            f"Malformed Freedom row at {source_path.name}:page "
                            f"{page_number},table {table_number},row {row_number}: {error}"
                        ) from error

    if not records:
        raise ValueError(f"No Freedom transaction rows found: {source_path.name}")
    return pd.DataFrame(records)


def _clean_cell(value: object) -> str:
    return "" if value is None else " ".join(str(value).split())


def _find_columns(headers: list[str]) -> dict[str, int]:
    return {
        key: column
        for key, aliases in _ALIASES.items()
        if (column := _find_column(headers, aliases)) is not None
    }


def _find_column(headers: list[str], aliases: tuple[str, ...]) -> int | None:
    normalized = [header.casefold() for header in headers]
    for alias in aliases:
        normalized_alias = alias.casefold()
        for index, header in enumerate(normalized):
            if header == normalized_alias or header.startswith(f"{normalized_alias} "):
                return index
    return None


def _column_value(row: list[object | None], columns: dict[str, int], key: str) -> str:
    column = columns.get(key)
    return "" if column is None else _clean_cell(row[column])


def _decimal(value: object, field: str) -> Decimal:
    cleaned = re.sub(r"[^\d,\.\-+]", "", _clean_cell(value)).replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(f"Invalid {field}: {value!r}") from error

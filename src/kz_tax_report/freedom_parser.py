"""Parse transaction tables from Freedom Bank investment PDFs."""

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import pdfplumber


_ALIASES = {
    "date": ("дата", "date"),
    "transaction_type": ("тип операции", "операция", "transaction type", "type"),
    "symbol": ("тикер", "символ", "инструмент", "symbol", "ticker"),
    "quantity": ("количество", "quantity", "qty"),
    "profit": ("прибыль", "прибыль/убыток", "profit", "p&l", "p/l"),
}


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
                columns = {
                    key: _find_column(headers, aliases)
                    for key, aliases in _ALIASES.items()
                }
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
                                "symbol": _clean_cell(raw_row[columns["symbol"]]),
                                "quantity": _decimal(
                                    raw_row[columns["quantity"]], "quantity"
                                ),
                                "profit": _decimal(
                                    raw_row[columns["profit"]], "profit"
                                ),
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


def _find_column(headers: list[str], aliases: tuple[str, ...]) -> int:
    normalized = [header.casefold() for header in headers]
    for alias in aliases:
        if alias.casefold() in normalized:
            return normalized.index(alias.casefold())
    raise ValueError(f"Required Freedom column is missing; expected one of {aliases}")


def _decimal(value: object, field: str) -> Decimal:
    cleaned = _clean_cell(value).replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(f"Invalid {field}: {value!r}") from error

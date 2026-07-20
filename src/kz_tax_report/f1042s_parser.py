"""Extract the taxpayer and income fields from IRS Form 1042-S PDFs."""

import re
from pathlib import Path

import pandas as pd
import pdfplumber


_NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?"


def parse_f1042s(path: str | Path) -> pd.DataFrame:
    """Return one validated record per 1042-S page, retaining page provenance."""

    source_path = Path(path)
    records: list[dict[str, object]] = []
    with pdfplumber.open(source_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            records.append(_parse_page(text, source_path.name, page_number))

    if not records:
        raise ValueError(f"No readable 1042-S pages found: {source_path.name}")
    return pd.DataFrame(records)


def _parse_page(text: str, source_file: str, source_page: int) -> dict[str, object]:
    try:
        tax_year = int(_label_value(text, r"Calendar\s+year", r"\d{4}"))
        tin = _label_value(
            text,
            r"Recipient(?:'|’)?s\s+foreign\s+taxpayer\s+identification\s+number",
            r"[A-Za-z0-9-]+",
        )
        income_code = _label_value(text, r"Income\s+code", r"\d{1,3}").zfill(2)
        gross_income = _decimal_value(text, r"Gross\s+income")
        withheld = _decimal_value(text, r"Federal\s+tax\s+withheld")
    except ValueError as error:
        raise ValueError(
            f"Malformed 1042-S at {source_file}:page {source_page}: {error}"
        ) from error

    return {
        "tax_year": tax_year,
        "recipient_tin": tin,
        "income_code": income_code,
        "gross_income": gross_income,
        "federal_tax_withheld": withheld,
        "source_file": source_file,
        "source_page": source_page,
        "source_row": _line_number(text, r"Calendar\s+year"),
    }


def _label_value(text: str, label: str, value_pattern: str) -> str:
    match = re.search(rf"{label}\s*[:#]?\s*({value_pattern})", text, re.IGNORECASE)
    if not match:
        raise ValueError(f"missing field matching {label!r}")
    return match.group(1).replace(",", "")


def _decimal_value(text: str, label: str) -> object:
    from decimal import Decimal

    return Decimal(_label_value(text, label, _NUMBER))


def _line_number(text: str, label: str) -> int:
    for line_number, line in enumerate(text.splitlines(), start=1):
        if re.search(label, line, re.IGNORECASE):
            return line_number
    return 1

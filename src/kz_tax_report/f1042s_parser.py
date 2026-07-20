"""Extract the taxpayer and income fields from IRS Form 1042-S PDFs."""

import re
from pathlib import Path

import pandas as pd
import pdfplumber
from pypdf import PdfReader


_NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?"


def parse_f1042s(path: str | Path) -> pd.DataFrame:
    """Return one validated record per 1042-S page, retaining page provenance."""

    source_path = Path(path)
    records = _try_parse_pages(_pdfplumber_page_texts(source_path), source_path.name)
    if not records:
        records = _try_parse_pages(_pypdf_page_texts(source_path), source_path.name)

    if not records:
        raise ValueError(f"No completed 1042-S forms found: {source_path.name}")
    return pd.DataFrame(records)


def _pdfplumber_page_texts(path: Path) -> list[str]:
    with pdfplumber.open(path) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def _pypdf_page_texts(path: Path) -> list[str]:
    return [(page.extract_text() or "") for page in PdfReader(path).pages]


def _parse_pages(texts: list[str], source_file: str) -> list[dict[str, object]]:
    has_recipient_copies = any(_is_recipient_copy(text) for text in texts)
    return [
        _parse_page(text, source_file, page_number)
        for page_number, text in enumerate(texts, start=1)
        if _is_selected_form(text, has_recipient_copies)
    ]


def _try_parse_pages(texts: list[str], source_file: str) -> list[dict[str, object]]:
    try:
        return _parse_pages(texts, source_file)
    except ValueError:
        return []


def _is_completed_form(text: str) -> bool:
    return all(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in (
            r"Income\s+code\s*[:#]?\s*\d{1,3}",
            rf"Gross\s+income\s*[:#]?\s*{_NUMBER}",
            rf"Federal\s+tax\s+withheld\s*[:#]?\s*{_NUMBER}",
        )
    )


def _is_recipient_copy(text: str) -> bool:
    return bool(re.search(r"\bCopy\s+B\b", text, re.IGNORECASE))


def _is_selected_form(text: str, has_recipient_copies: bool) -> bool:
    return (
        _is_recipient_copy(text) if has_recipient_copies else _is_completed_form(text)
    )


def _parse_page(text: str, source_file: str, source_page: int) -> dict[str, object]:
    try:
        tax_year = _tax_year(text)
        tin = _label_value(
            text,
            r"Recipient(?:'|’)?s\s+foreign\s+(?:taxpayer\s+identification\s+"
            r"number|tax\s+identification(?:\s+number)?)",
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


def _tax_year(text: str) -> int:
    for pattern in (r"Calendar\s+year", r"Tax\s+year"):
        try:
            return int(_label_value(text, pattern, r"\d{4}"))
        except ValueError:
            pass
    match = re.search(r"\b(20\d{2})\s+Form\s+1042-S\b", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    years = sorted(set(re.findall(r"\b20\d{2}\b", text)))
    if len(years) == 1:
        return int(years[0])
    raise ValueError("missing tax year")


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

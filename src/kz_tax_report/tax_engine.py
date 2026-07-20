"""Review-gated tax calculations for investment income."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from kz_tax_report.ibkr_parser import (
    extract_dividends,
    extract_realized_pnl,
    extract_withholding_tax,
)


class RulesError(ValueError):
    """Raised when a tax rules file cannot safely govern a calculation."""


@dataclass(frozen=True)
class TaxRules:
    year: int
    citation: str
    rate: Decimal
    foreign_tax_credit: bool
    dividends_line: str
    realized_gains_line: str
    exempt_gains_line: str


@dataclass(frozen=True)
class TraceableValue:
    category: str
    amount: Decimal
    source_file: str
    source_row: int
    source_detail: str = ""


@dataclass(frozen=True)
class TaxReport:
    year: int
    rules: TaxRules
    taxable_dividends: Decimal
    taxable_realized_gains: Decimal
    exempt_realized_gains: Decimal
    tax_before_credit: Decimal
    foreign_tax_credit: Decimal
    tax_due: Decimal
    values: tuple[TraceableValue, ...]
    warnings: tuple[str, ...]


def load_rules(path: str | Path) -> TaxRules:
    """Load and validate an approved, complete year-specific YAML rules file."""

    source_path = Path(path)
    try:
        raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RulesError(f"Unable to read tax rules: {source_path}: {error}") from error
    if not isinstance(raw, dict):
        raise RulesError("Tax rules must be a YAML mapping")
    if raw.get("approved") is not True:
        raise RulesError("Tax rules must be explicitly approved before calculation")

    try:
        tax = raw["tax"]
        income = raw["income"]
        rules = TaxRules(
            year=int(raw["year"]),
            citation=_required_text(raw, "citation"),
            rate=_decimal(tax["rate"], "tax.rate"),
            foreign_tax_credit=bool(tax["foreign_tax_credit"]),
            dividends_line=_required_text(income, "dividends_line"),
            realized_gains_line=_required_text(income, "realized_gains_line"),
            exempt_gains_line=_required_text(income, "exempt_gains_line"),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise RulesError(f"Tax rules are incomplete: {error}") from error
    if not Decimal("0") <= rules.rate <= Decimal("1"):
        raise RulesError("tax.rate must be between 0 and 1")
    return rules


def calculate_report(
    *,
    year: int,
    rules: TaxRules,
    ibkr_sections: dict[str, pd.DataFrame],
    freedom_transactions: pd.DataFrame,
    f1042s_records: pd.DataFrame,
) -> TaxReport:
    """Calculate tax inputs while retaining a source reference for every value."""

    if rules.year != year:
        raise RulesError(
            f"Rules year {rules.year} does not match requested year {year}"
        )

    dividends = extract_dividends(ibkr_sections)
    withholding = extract_withholding_tax(ibkr_sections)
    realized = extract_realized_pnl(ibkr_sections)
    values: list[TraceableValue] = []
    for row in dividends.to_dict("records"):
        values.append(_trace("dividend", row["amount"], row))
    for row in realized.to_dict("records"):
        values.append(_trace("realized_gain", row["realized_total"], row))
    for row in f1042s_records.to_dict("records"):
        values.append(_trace("1042s_gross_income", row["gross_income"], row))
        values.append(
            _trace("1042s_federal_tax_withheld", row["federal_tax_withheld"], row)
        )

    taxable_dividends = _sum(dividends, "amount")
    taxable_realized_gains = _sum(realized, "realized_total")
    exempt_realized_gains = _sum(
        freedom_transactions[freedom_transactions["transaction_type"].map(_is_sale)],
        "profit",
    )
    for row in freedom_transactions[
        freedom_transactions["transaction_type"].map(_is_sale)
    ].to_dict("records"):
        values.append(_trace("exempt_gain", row["profit"], row))

    dividend_f1042s = _dividend_1042s_records(f1042s_records)
    f1042s_gross = _sum(dividend_f1042s, "gross_income")
    withheld = abs(_sum(dividend_f1042s, "federal_tax_withheld"))
    warnings = _reconciliation_warnings(
        taxable_dividends,
        abs(_sum(withholding, "amount")),
        f1042s_gross,
        withheld,
    )
    warnings.extend(_non_dividend_1042s_warnings(f1042s_records))
    tax_before_credit = _money(
        (taxable_dividends + taxable_realized_gains) * rules.rate
    )
    foreign_tax_credit = _money(
        min(withheld, tax_before_credit) if rules.foreign_tax_credit else Decimal("0")
    )
    return TaxReport(
        year=year,
        rules=rules,
        taxable_dividends=_money(taxable_dividends),
        taxable_realized_gains=_money(taxable_realized_gains),
        exempt_realized_gains=_money(exempt_realized_gains),
        tax_before_credit=tax_before_credit,
        foreign_tax_credit=foreign_tax_credit,
        tax_due=_money(max(Decimal("0"), tax_before_credit - foreign_tax_credit)),
        values=tuple(values),
        warnings=tuple(warnings),
    )


def _required_text(mapping: dict[str, Any], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"{field} must be numeric") from error


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _sum(frame: pd.DataFrame, column: str) -> Decimal:
    if frame.empty:
        return Decimal("0")
    return sum((_decimal(value, column) for value in frame[column]), Decimal("0"))


def _trace(category: str, amount: object, row: dict[str, Any]) -> TraceableValue:
    detail = str(row.get("symbol") or row.get("description") or "")
    return TraceableValue(
        category=category,
        amount=_money(_decimal(amount, category)),
        source_file=str(row["source_file"]),
        source_row=int(row["source_row"]),
        source_detail=detail,
    )


def _is_sale(value: object) -> bool:
    return str(value).casefold() in {"продажа", "sale", "sell"}


def _dividend_1042s_records(records: pd.DataFrame) -> pd.DataFrame:
    if "income_code" not in records:
        raise ValueError("1042-S records are missing income_code")
    codes = records["income_code"].astype(str).str.zfill(2)
    return records[codes == "06"]


def _non_dividend_1042s_warnings(records: pd.DataFrame) -> list[str]:
    if "income_code" not in records:
        return []
    codes = sorted(
        {
            str(code).zfill(2)
            for code in records["income_code"]
            if str(code).zfill(2) != "06"
        }
    )
    return [
        f"1042-S income code {code} is not included in the dividend calculation "
        "and requires manual review."
        for code in codes
    ]


def _reconciliation_warnings(
    ibkr_dividends: Decimal,
    ibkr_withheld: Decimal,
    f1042s_gross: Decimal,
    f1042s_withheld: Decimal,
) -> list[str]:
    warnings: list[str] = []
    if ibkr_dividends != f1042s_gross:
        warnings.append(
            "1042-S gross income does not reconcile with IBKR dividends: "
            f"IBKR {ibkr_dividends}, 1042-S gross income {f1042s_gross}."
        )
    if ibkr_withheld != f1042s_withheld:
        warnings.append(
            "1042-S federal tax withheld does not reconcile with IBKR withholding: "
            f"IBKR {ibkr_withheld}, 1042-S {f1042s_withheld}."
        )
    return warnings

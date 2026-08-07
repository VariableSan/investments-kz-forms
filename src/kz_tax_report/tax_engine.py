"""Review-gated tax calculations for investment income."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from datetime import date

import pandas as pd
import yaml

from kz_tax_report.ibkr_parser import (
    extract_dividends,
    extract_open_positions,
    extract_realized_pnl,
    extract_withholding_tax,
)


_GROSS_RECONCILIATION_TOLERANCE = Decimal("0.50")


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
    form_labels: dict[str, str]
    exemptions: tuple[str, ...]
    conversion_policy: str
    approved: bool
    brackets: tuple[tuple[Decimal, Decimal], ...] = ()


@dataclass(frozen=True)
class TraceableValue:
    category: str
    amount: Decimal
    source_file: str
    source_row: int
    source_detail: str = ""
    currency: str = ""
    rate_date: str = ""
    fx_rate: Decimal | None = None
    fx_source: str = ""
    foreign_amount: Decimal | None = None
    kzt_amount: Decimal | None = None


@dataclass(frozen=True)
class DeclarationItem:
    label: str
    amount: Decimal
    form_line: str
    status: str
    note: str
    source_file: str
    source_row: int


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
    declaration_items: tuple[DeclarationItem, ...]
    assets: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    freedom_report_uploaded: bool = False
    freedom_isin: str = ""
    input_fingerprint: str = ""

    @property
    def status(self) -> str:
        return "FINAL" if self.rules.approved else "DRAFT / NOT FOR FILING"


def load_rules(path: str | Path, *, require_approved: bool = True) -> TaxRules:
    """Load and validate an approved, complete year-specific YAML rules file."""

    source_path = Path(path)
    try:
        raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RulesError(f"Unable to read tax rules: {source_path}: {error}") from error
    if not isinstance(raw, dict):
        raise RulesError("Tax rules must be a YAML mapping")
    approved = raw.get("approved") is True
    if require_approved and not approved:
        raise RulesError("Tax rules must be explicitly approved before calculation")

    try:
        tax = raw["tax"]
        income = raw["income"]
        form_labels = raw.get("form_labels", {})
        if not isinstance(form_labels, dict):
            raise ValueError("form_labels must be a mapping")
        exemptions = raw.get("exemptions", [])
        if not isinstance(exemptions, list) or not all(
            isinstance(item, str) and item.strip() for item in exemptions
        ):
            raise ValueError("exemptions must be a list of non-empty strings")
        brackets = tuple(
            (
                _decimal(item["up_to"], "tax.brackets.up_to"),
                _decimal(item["rate"], "tax.brackets.rate"),
            )
            for item in tax.get("brackets", [])
        )
        rules = TaxRules(
            year=int(raw["year"]),
            citation=_required_text(raw, "citation"),
            rate=_decimal(tax["rate"], "tax.rate"),
            foreign_tax_credit=bool(tax["foreign_tax_credit"]),
            dividends_line=_required_text(income, "dividends_line"),
            realized_gains_line=_required_text(income, "realized_gains_line"),
            exempt_gains_line=_required_text(income, "exempt_gains_line"),
            form_labels={
                str(key): _required_text(form_labels, str(key)) for key in form_labels
            },
            exemptions=tuple(exemptions),
            conversion_policy=str(
                raw.get("conversion_policy", "NBK rate on income date")
            ),
            approved=approved,
            brackets=brackets,
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
    f1042s_records: pd.DataFrame | None,
    rate_provider: Any | None = None,
    auto_fill_isin: bool = False,
    freedom_report_uploaded: bool = False,
    freedom_closing_position: dict[str, Any] | None = None,
) -> TaxReport:
    """Calculate tax inputs while retaining a source reference for every value."""

    if rules.year != year:
        raise RulesError(
            f"Rules year {rules.year} does not match requested year {year}"
        )

    dividends = _filter_year(extract_dividends(ibkr_sections), year)
    withholding = _filter_year(extract_withholding_tax(ibkr_sections), year)
    realized = extract_realized_pnl(ibkr_sections)
    assets = (
        extract_open_positions(ibkr_sections, auto_fill_isin=auto_fill_isin)
        if "Открытые позиции" in ibkr_sections
        else pd.DataFrame()
    )
    if (
        freedom_closing_position is not None
        and _decimal(
            freedom_closing_position.get("quantity", 0), "Freedom closing quantity"
        )
        != 0
    ):
        assets = pd.concat([assets, pd.DataFrame([freedom_closing_position])])
    freedom_transactions = _filter_year(freedom_transactions, year)
    f1042s_records = _filter_year(
        f1042s_records if f1042s_records is not None else _empty_1042s(),
        year,
        column="tax_year",
    )
    values: list[TraceableValue] = []
    declaration_items: list[DeclarationItem] = []
    source_dividend_total = _sum(dividends, "amount")
    source_withholding_total = _sum(withholding, "amount")
    dividend_rows = _convert_rows(dividends, "amount", rate_provider)
    for row in dividend_rows.to_dict("records"):
        values.append(_trace("dividend", row["amount"], row))
    realized = realized.assign(currency="USD")
    realized_rows = _convert_rows(realized, "realized_total", rate_provider)
    for row in realized_rows.to_dict("records"):
        values.append(_trace("realized_gain", row["realized_total"], row))
    f1042s_currency = f1042s_records.assign(currency="USD")
    f1042s_rate_provider = (
        rate_provider if getattr(rate_provider, "annual", False) else None
    )
    f1042s_gross_rows = _convert_rows(
        f1042s_currency, "gross_income", f1042s_rate_provider
    )
    f1042s_withheld_rows = _convert_rows(
        f1042s_currency, "federal_tax_withheld", f1042s_rate_provider
    )
    for row in f1042s_gross_rows.to_dict("records"):
        values.append(_trace("1042s_gross_income", row["gross_income"], row))
    for row in f1042s_withheld_rows.to_dict("records"):
        values.append(
            _trace("1042s_federal_tax_withheld", row["federal_tax_withheld"], row)
        )

    non_dividend_records = f1042s_records[
        f1042s_records["income_code"].astype(str).str.zfill(2) != "06"
    ]
    if not non_dividend_records.empty:
        review_rows = non_dividend_records.assign(currency="USD")
        for row in _convert_rows(
            review_rows, "gross_income", f1042s_rate_provider
        ).to_dict("records"):
            declaration_items.append(
                DeclarationItem(
                    label=f"Код дохода формы 1042-S {str(row['income_code']).zfill(2)}",
                    amount=_money(_decimal(row["gross_income"], "gross_income")),
                    form_line="manual",
                    status="требуется ручная классификация",
                    note="Показано для проверки; исключено из налога на дивиденды и иностранного налогового кредита.",
                    source_file=str(row["source_file"]),
                    source_row=int(row["source_row"]),
                )
            )

    taxable_dividends = _sum(dividend_rows, "amount")
    taxable_realized_gains = _sum(realized_rows, "realized_total")
    exempt_sales = freedom_transactions[
        freedom_transactions["transaction_type"].map(_is_sale)
    ]
    exempt_realized_gains = _sum(
        _convert_rows(exempt_sales, "profit", rate_provider),
        "profit",
    )
    for row in _convert_rows(exempt_sales, "profit", rate_provider).to_dict("records"):
        values.append(_trace("exempt_gain", row["profit"], row))

    dividend_f1042s = _dividend_1042s_records(f1042s_records)
    f1042s_gross = _sum(f1042s_records, "gross_income")
    withheld_usd = Decimal("0")
    withheld = Decimal("0")
    warnings: list[str] = []
    if f1042s_records.empty:
        warnings.append(
            "Форма 1042-S не предоставлена; удержание IBKR показано для справки и "
            "не применяется как иностранный налоговый кредит."
        )
    else:
        withheld_usd = abs(_sum(dividend_f1042s, "federal_tax_withheld"))
        withheld = abs(
            _sum(
                f1042s_withheld_rows.loc[dividend_f1042s.index],
                "federal_tax_withheld",
            )
        )
        warnings.extend(
            _reconciliation_warnings(
                source_dividend_total,
                source_withholding_total,
                f1042s_gross,
                withheld_usd,
            )
        )
    warnings.extend(_non_dividend_1042s_warnings(f1042s_records))
    tax_before_credit = _money(
        _tax_for_base(taxable_dividends + taxable_realized_gains, rules)
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
        declaration_items=tuple(declaration_items),
        assets=tuple(assets.to_dict("records")),
        warnings=tuple(warnings),
        freedom_report_uploaded=freedom_report_uploaded,
        freedom_isin=(
            str(freedom_closing_position.get("isin", ""))
            if freedom_report_uploaded and freedom_closing_position is not None
            else ""
        ),
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


def _filter_year(frame: pd.DataFrame, year: int, column: str = "date") -> pd.DataFrame:
    if frame.empty or column not in frame:
        return frame

    def matches(value: object) -> bool:
        if isinstance(value, int) or (
            isinstance(value, str) and value.strip().isdigit()
        ):
            return int(value) == year
        try:
            return date.fromisoformat(str(value)[:10]).year == year
        except ValueError:
            return False

    return frame[frame[column].map(matches)].reset_index(drop=True)


def _convert_rows(
    frame: pd.DataFrame, amount_column: str, provider: Any | None
) -> pd.DataFrame:
    if provider is None or frame.empty:
        return frame
    result = frame.copy()
    converted: list[Decimal] = []
    for index, row in enumerate(result.to_dict("records")):
        currency = str(row.get("currency", "USD") or "USD").upper()
        if currency == "KZT":
            converted.append(_decimal(row[amount_column], amount_column))
            continue
        raw_date = (
            row.get("date") or row.get("payment_date") or row.get("disposal_date")
        )
        if not raw_date and not getattr(provider, "annual", False):
            raise RulesError(f"Missing conversion date for {amount_column}")
        raw_date = raw_date or "annual"
        rate = provider.get_rate(str(raw_date)[:10], currency)
        original = _decimal(row[amount_column], amount_column)
        converted.append(original * _decimal(rate, "FX rate"))
        result.loc[index, "original_amount"] = original
        result.loc[index, "rate_date"] = str(raw_date)[:10]
        result.loc[index, "fx_rate"] = rate
        source_for = getattr(provider, "source_for", None)
        if source_for is not None:
            source = source_for(currency)
            if source is not None:
                result.loc[index, "fx_source"] = (
                    f"{source.file}:{source.sheet}!{source.rate_cell}"
                )
    result[amount_column] = converted
    return result


def _tax_for_base(base: Decimal, rules: TaxRules) -> Decimal:
    if not rules.brackets:
        return base * rules.rate
    total = Decimal("0")
    lower = Decimal("0")
    for upper, rate in rules.brackets:
        portion = min(base, upper) - lower
        if portion > 0:
            total += portion * rate
        lower = upper
        if base <= upper:
            return total
    if base > lower:
        total += (base - lower) * rules.brackets[-1][1]
    return total


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
        currency=str(row.get("currency", "KZT") or "KZT"),
        rate_date=str(row.get("rate_date", "")),
        fx_rate=row.get("fx_rate"),
        fx_source=str(row.get("fx_source", "")),
        foreign_amount=(
            _money(_decimal(row["original_amount"], category))
            if "original_amount" in row
            else None
        ),
        kzt_amount=_money(_decimal(amount, category)),
    )


def _is_sale(value: object) -> bool:
    return str(value).casefold() in {"продажа", "sale", "sell"}


def _dividend_1042s_records(records: pd.DataFrame) -> pd.DataFrame:
    if "income_code" not in records:
        raise ValueError("1042-S records are missing income_code")
    codes = records["income_code"].astype(str).str.zfill(2)
    return records[codes == "06"]


def _empty_1042s() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "tax_year",
            "income_code",
            "gross_income",
            "federal_tax_withheld",
        ]
    )


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
        f"Код дохода {code} формы 1042-S не включён в расчёт дивидендов "
        "и требует ручной проверки."
        for code in codes
    ]


def _reconciliation_warnings(
    ibkr_income: Decimal,
    ibkr_withheld_net: Decimal,
    f1042s_gross: Decimal,
    f1042s_withheld: Decimal,
) -> list[str]:
    warnings: list[str] = []
    if abs(ibkr_income - f1042s_gross) > _GROSS_RECONCILIATION_TOLERANCE:
        warnings.append(
            "Валовой доход по форме 1042-S не сходится с доходом IBKR: "
            f"IBKR {ibkr_income}, общий валовой доход 1042-S {f1042s_gross}."
        )
    if abs(ibkr_withheld_net) != f1042s_withheld:
        warnings.append(
            "Удержанный федеральный налог по форме 1042-S не сходится с удержанием IBKR: "
            f"IBKR нетто {ibkr_withheld_net} USD, форма 1042-S, код 06, "
            f"{f1042s_withheld} USD; в деталях IBKR могут быть обратные операции. "
            "Для кредита используется сумма из формы 1042-S."
        )
    return warnings

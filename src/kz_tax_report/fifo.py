"""Decimal FIFO lot matching with source-row provenance."""

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping


class FifoError(ValueError):
    """Raised when FIFO input cannot be matched safely."""


@dataclass(frozen=True)
class FifoMatch:
    symbol: str
    quantity: Decimal
    unit_cost: Decimal
    unit_price: Decimal
    gain: Decimal
    purchase_source_row: object | None
    sale_source_row: object | None


def match_fifo(
    purchases: list[Mapping[str, object]], sales: list[Mapping[str, object]]
) -> list[FifoMatch]:
    """Match purchases to sales in input order, grouped independently by symbol."""

    inventory: dict[str, deque[tuple[Decimal, Decimal, object | None]]] = defaultdict(
        deque
    )
    for purchase in purchases:
        symbol = _symbol(purchase)
        inventory[symbol].append(
            (
                _positive(purchase, "quantity"),
                _decimal(purchase, "unit_cost"),
                purchase.get("source_row"),
            )
        )

    matches: list[FifoMatch] = []
    for sale in sales:
        symbol = _symbol(sale)
        remaining = _positive(sale, "quantity")
        unit_price = _decimal(sale, "unit_price")
        lots = inventory[symbol]
        while remaining:
            if not lots:
                raise FifoError(f"Insufficient inventory for {symbol}")
            lot_quantity, unit_cost, purchase_source_row = lots[0]
            matched_quantity = min(remaining, lot_quantity)
            matches.append(
                FifoMatch(
                    symbol=symbol,
                    quantity=matched_quantity,
                    unit_cost=unit_cost,
                    unit_price=unit_price,
                    gain=matched_quantity * (unit_price - unit_cost),
                    purchase_source_row=purchase_source_row,
                    sale_source_row=sale.get("source_row"),
                )
            )
            remaining -= matched_quantity
            lot_quantity -= matched_quantity
            if lot_quantity:
                lots[0] = (lot_quantity, unit_cost, purchase_source_row)
            else:
                lots.popleft()
    return matches


def _symbol(record: Mapping[str, object]) -> str:
    symbol = str(record.get("symbol", "")).strip()
    if not symbol:
        raise FifoError("FIFO record is missing symbol")
    return symbol


def _decimal(record: Mapping[str, object], field: str) -> Decimal:
    try:
        value = Decimal(str(record[field]))
    except (KeyError, InvalidOperation) as error:
        raise FifoError(f"FIFO record has invalid {field}") from error
    return value


def _positive(record: Mapping[str, object], field: str) -> Decimal:
    value = _decimal(record, field)
    if value <= 0:
        raise FifoError(f"FIFO {field} must be positive")
    return value

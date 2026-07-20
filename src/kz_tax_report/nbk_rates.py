"""National Bank of Kazakhstan FX rates with a local JSON cache."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests

from kz_tax_report.config import (
    DEFAULT_NBK_URL,
    get_nbk_cache_path,
    get_nbk_timeout,
    get_nbk_url,
)

__all__ = ["DEFAULT_NBK_URL", "NbkRateProvider", "get_nbk_rate"]


class NbkRateProvider:
    """Fetch NBK daily rates and fall back to the latest cached prior rate."""

    def __init__(
        self,
        cache_path: str | Path | None = None,
        *,
        url: str | None = None,
        session: Any | None = None,
        timeout: float | None = None,
    ) -> None:
        self.cache_path = (
            Path(cache_path) if cache_path is not None else get_nbk_cache_path()
        )
        self.url = url.strip() if url and url.strip() else get_nbk_url()
        self.session = session or requests.Session()
        self.timeout = timeout if timeout is not None else get_nbk_timeout()

    def get_rate(self, rate_date: date | str, currency: str) -> Decimal:
        requested_date = _as_date(rate_date)
        code = currency.upper().strip()
        if not code:
            raise ValueError("Currency code is required")

        cache = self._read_cache()
        exact = _cached_rate(cache, requested_date, code)
        if exact is not None:
            return exact

        try:
            rate = self._fetch(requested_date, code)
        except (
            ElementTree.ParseError,
            InvalidOperation,
            OSError,
            requests.RequestException,
        ) as error:
            fallback = _latest_cached_rate(cache, requested_date, code)
            if fallback is not None:
                return fallback
            raise RuntimeError(
                f"Unable to obtain NBK rate for {code} on {requested_date.isoformat()}"
            ) from error

        cache.setdefault(requested_date.isoformat(), {})[code] = str(rate)
        self._write_cache(cache)
        return rate

    def _fetch(self, rate_date: date, currency: str) -> Decimal:
        response = self.session.get(
            self.url,
            params={"fdate": rate_date.strftime("%d.%m.%Y")},
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        for item in root.iter():
            title = (item.findtext("title") or "").strip().upper()
            if title == currency:
                value = (item.findtext("description") or "").strip().replace(",", ".")
                return Decimal(value)
        raise ValueError(f"Currency {currency} is missing from NBK response")

    def _read_cache(self) -> dict[str, dict[str, str]]:
        if not self.cache_path.exists():
            return {}
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Invalid NBK cache: {self.cache_path}") from error
        if not isinstance(value, dict) or not all(
            isinstance(row, dict) for row in value.values()
        ):
            raise RuntimeError(f"Invalid NBK cache shape: {self.cache_path}")
        return value

    def _write_cache(self, cache: dict[str, dict[str, str]]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(cache, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


def get_nbk_rate(
    rate_date: date | str,
    currency: str,
    cache_path: str | Path | None = None,
    *,
    url: str | None = None,
) -> Decimal:
    """Convenience wrapper around :class:`NbkRateProvider`."""

    return NbkRateProvider(cache_path, url=url).get_rate(rate_date, currency)


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Invalid rate date: {value!r}") from error


def _cached_rate(
    cache: dict[str, dict[str, str]], rate_date: date, currency: str
) -> Decimal | None:
    value = cache.get(rate_date.isoformat(), {}).get(currency)
    return None if value is None else Decimal(value)


def _latest_cached_rate(
    cache: dict[str, dict[str, str]], rate_date: date, currency: str
) -> Decimal | None:
    for offset in range(1, 3660):
        prior = rate_date - timedelta(days=offset)
        value = _cached_rate(cache, prior, currency)
        if value is not None:
            return value
    return None

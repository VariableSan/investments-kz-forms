"""Environment-backed application configuration."""

import os
from pathlib import Path


DEFAULT_NBK_URL = "https://nationalbank.kz/rss/get_rates.cfm"
DEFAULT_NBK_TIMEOUT = 10.0
DEFAULT_NBK_CACHE_PATH = Path("output/nbk-rates.json")


def get_nbk_url() -> str:
    return _env_value("KZ_TAX_REPORT_NBK_URL", DEFAULT_NBK_URL)


def get_nbk_timeout() -> float:
    value = _env_value("KZ_TAX_REPORT_NBK_TIMEOUT", str(DEFAULT_NBK_TIMEOUT))
    try:
        timeout = float(value)
    except ValueError as error:
        raise ValueError("KZ_TAX_REPORT_NBK_TIMEOUT must be a number") from error
    if timeout <= 0:
        raise ValueError("KZ_TAX_REPORT_NBK_TIMEOUT must be greater than zero")
    return timeout


def get_nbk_cache_path() -> Path:
    return Path(_env_value("KZ_TAX_REPORT_NBK_CACHE_PATH", str(DEFAULT_NBK_CACHE_PATH)))


def get_rules_path(year: int) -> Path:
    rules_dir = os.environ.get("KZ_TAX_REPORT_RULES_DIR", "").strip()
    if rules_dir:
        return Path(rules_dir) / f"tax_rules_{year}.yaml"
    return Path(__file__).with_name(f"tax_rules_{year}.yaml")


def _env_value(name: str, fallback: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or fallback

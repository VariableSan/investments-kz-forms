"""Environment-backed application configuration."""

import os
from pathlib import Path


DEFAULT_NBK_URL = "https://nationalbank.kz/rss/get_rates.cfm"
DEFAULT_NBK_TIMEOUT = 10.0
DEFAULT_NBK_CACHE_PATH = Path("output/nbk-rates.json")
DEFAULT_ARTIFACT_ROOT = Path("/tmp/kz-tax-report-jobs")
DEFAULT_ARTIFACT_MODE = "local"
DEFAULT_ARTIFACT_TTL_SECONDS = 86400.0
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_JOB_BYTES = 75 * 1024 * 1024
DEFAULT_SOURCE_URLS = {
    "tax_code": "https://adilet.zan.kz/eng/docs/K1700000121",
    "form_instructions": "https://kgd.gov.kz/en/content/forms-tax-reporting",
    "mrp": "https://gov.kz/memleket/entities/enbek?lang=en",
    "nbk_rates": DEFAULT_NBK_URL,
    "treaty_credit": "https://www.oecd.org/tax/treaties/",
    "aix_exemption": "https://aix.kz/listing/",
}
SOURCE_ENV_NAMES = {
    key: f"KZ_TAX_REPORT_SOURCE_{key.upper()}_URL" for key in DEFAULT_SOURCE_URLS
}
ALLOWED_SOURCE_HOSTS = {
    "tax_code": {"adilet.zan.kz"},
    "form_instructions": {"kgd.gov.kz"},
    "mrp": {"gov.kz"},
    "nbk_rates": {"nationalbank.kz"},
    "treaty_credit": {"oecd.org", "www.oecd.org"},
    "aix_exemption": {"aix.kz", "www.aix.kz"},
}


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


def get_artifact_root() -> Path:
    return Path(_env_value("KZ_TAX_REPORT_ARTIFACT_DIR", str(DEFAULT_ARTIFACT_ROOT)))


def get_artifact_mode() -> str:
    mode = _env_value("KZ_TAX_REPORT_ARTIFACT_MODE", DEFAULT_ARTIFACT_MODE).lower()
    if mode not in {"local", "hosted"}:
        raise ValueError("KZ_TAX_REPORT_ARTIFACT_MODE must be local or hosted")
    return mode


def get_artifact_ttl_seconds() -> float:
    return _positive_float(
        "KZ_TAX_REPORT_ARTIFACT_TTL_SECONDS", DEFAULT_ARTIFACT_TTL_SECONDS
    )


def get_max_upload_bytes() -> int:
    return _positive_int("KZ_TAX_REPORT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)


def get_max_job_bytes() -> int:
    return _positive_int("KZ_TAX_REPORT_MAX_JOB_BYTES", DEFAULT_MAX_JOB_BYTES)


def get_source_url(source_key: str) -> str:
    """Return a configured official URL, rejecting unknown or off-domain links."""

    if source_key not in DEFAULT_SOURCE_URLS:
        raise ValueError(f"Unknown source key: {source_key}")
    value = _env_value(SOURCE_ENV_NAMES[source_key], DEFAULT_SOURCE_URLS[source_key])
    from urllib.parse import urlparse

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host not in ALLOWED_SOURCE_HOSTS[source_key]:
        raise ValueError(f"Source URL is not allowlisted for {source_key}: {value}")
    return value


def _env_value(name: str, fallback: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or fallback


def _positive_float(name: str, fallback: float) -> float:
    try:
        value = float(_env_value(name, str(fallback)))
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_int(name: str, fallback: int) -> int:
    try:
        value = int(_env_value(name, str(fallback)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value

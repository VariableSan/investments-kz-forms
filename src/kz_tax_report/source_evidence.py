"""Allowlisted, evidence-only retrieval of official tax references."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests

from kz_tax_report.config import get_source_url


class SourceEvidenceError(ValueError):
    """Raised when a source cannot be fetched under the local safety policy."""


@dataclass(frozen=True)
class SourceEvidence:
    """Metadata about a retrieval; response content is deliberately not interpreted."""

    source_key: str
    requested_url: str
    effective_url: str = ""
    retrieved_at: str = ""
    status_code: int | None = None
    etag: str = ""
    last_modified: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status_code is not None and not self.error

    def as_dict(self) -> dict[str, object]:
        return {
            "source_key": self.source_key,
            "requested_url": self.requested_url,
            "effective_url": self.effective_url,
            "retrieved_at": self.retrieved_at,
            "status_code": self.status_code,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "error": self.error,
        }


def fetch_source_evidence(
    source_key: str,
    *,
    session: Any | None = None,
    timeout: float | None = None,
) -> SourceEvidence:
    """Fetch only headers/status for an allowlisted URL and record the outcome."""

    requested_url = ""
    response: Any | None = None
    client = session or requests.Session()
    try:
        requested_url = get_source_url(source_key)
        _validate_url(source_key, requested_url)
        response = client.get(requested_url, timeout=timeout or 10.0)
        response.raise_for_status()
    except (
        OSError,
        requests.RequestException,
        SourceEvidenceError,
        ValueError,
    ) as error:
        return SourceEvidence(
            source_key=source_key,
            requested_url=requested_url,
            effective_url=str(getattr(response, "url", "")),
            retrieved_at=_now(),
            status_code=getattr(response, "status_code", None),
            error=str(error),
        )
    return SourceEvidence(
        source_key=source_key,
        requested_url=requested_url,
        effective_url=str(getattr(response, "url", requested_url)),
        retrieved_at=_now(),
        status_code=int(response.status_code),
        etag=str(getattr(response, "headers", {}).get("ETag", "")),
        last_modified=str(getattr(response, "headers", {}).get("Last-Modified", "")),
    )


def _validate_url(source_key: str, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SourceEvidenceError(f"Source {source_key} must use an HTTPS URL")


def _now() -> str:
    return datetime.now(UTC).isoformat()

from pathlib import Path

from kz_tax_report.config import get_source_url
from kz_tax_report.rules_workspace import TaxRulesDraft
from kz_tax_report.source_evidence import fetch_source_evidence


class Response:
    status_code = 200
    url = "https://adilet.zan.kz/eng/docs/K1700000121"
    headers = {"ETag": "abc", "Last-Modified": "yesterday"}

    def raise_for_status(self) -> None:
        return None


class Session:
    def get(self, url: str, *, timeout: float) -> Response:
        assert url.startswith("https://adilet.zan.kz/")
        assert timeout == 2
        return Response()


def test_source_urls_are_allowlisted(monkeypatch) -> None:
    assert get_source_url("tax_code").startswith("https://adilet.zan.kz/")
    monkeypatch.setenv("KZ_TAX_REPORT_SOURCE_TAX_CODE_URL", "https://example.com/rules")

    evidence = fetch_source_evidence("tax_code")

    assert evidence.ok is False
    assert "not allowlisted" in evidence.error


def test_source_fetch_records_metadata_without_approval() -> None:
    evidence = fetch_source_evidence("tax_code", session=Session(), timeout=2)

    assert evidence.ok is True
    assert evidence.status_code == 200
    assert evidence.etag == "abc"
    assert evidence.last_modified == "yesterday"
    assert evidence.effective_url.endswith("K1700000121")


def test_draft_nested_state_is_session_isolated(tmp_path: Path) -> None:
    source = tmp_path / "rules.yaml"
    source.write_text(
        "year: 2025\napproved: false\ncitation: x\n"
        "tax:\n  rate: '0.1'\n  foreign_tax_credit: true\n"
        "income:\n  dividends_line: a\n  realized_gains_line: b\n  exempt_gains_line: c\n",
        encoding="utf-8",
    )
    first = TaxRulesDraft.from_path(source)
    second = TaxRulesDraft.from_path(source)
    first.set_mrp("850")
    first.set_brackets([{"up_to": "100000", "rate": "0.1"}])

    assert "mrp" not in second.document
    assert "brackets" not in second.document["tax"]
    assert "mrp" not in source.read_text(encoding="utf-8")

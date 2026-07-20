from decimal import Decimal
from datetime import date
import json
from pathlib import Path

import pytest

from kz_tax_report.f1042s_parser import parse_f1042s
from kz_tax_report.fifo import FifoError, match_fifo
from kz_tax_report.freedom_parser import parse_freedom_report
from kz_tax_report.nbk_rates import NbkRateProvider


class FakePage:
    def __init__(self, text: str = "", tables: list[list[list[str]]] | None = None):
        self.text = text
        self.tables = tables or []

    def extract_text(self) -> str:
        return self.text

    def extract_tables(self) -> list[list[list[str]]]:
        return self.tables


class FakePdf:
    def __init__(self, pages: list[FakePage]):
        self.pages = pages

    def __enter__(self) -> "FakePdf":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_parse_1042s_extracts_labeled_values_and_page_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "form-1042s.pdf"
    path.touch()
    pdf = FakePdf(
        [
            FakePage(
                "Calendar year 2025\n"
                "Recipient's foreign taxpayer identification number 900101300123\n"
                "Income code 06\nGross income 123.45\nFederal tax withheld 18.52"
            )
        ]
    )
    monkeypatch.setattr("kz_tax_report.f1042s_parser.pdfplumber.open", lambda _: pdf)

    result = parse_f1042s(path)

    assert result.to_dict("records") == [
        {
            "tax_year": 2025,
            "recipient_tin": "900101300123",
            "income_code": "06",
            "gross_income": Decimal("123.45"),
            "federal_tax_withheld": Decimal("18.52"),
            "source_file": "form-1042s.pdf",
            "source_page": 1,
            "source_row": 1,
        }
    ]


def test_parse_1042s_skips_instruction_pages_and_uses_pypdf_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "form-1042s.pdf"
    path.touch()
    pdf = FakePdf(
        [FakePage("Income code 06\nGross income 123.45\nFederal tax withheld 18.52")]
    )
    monkeypatch.setattr("kz_tax_report.f1042s_parser.pdfplumber.open", lambda _: pdf)
    monkeypatch.setattr(
        "kz_tax_report.f1042s_parser._pypdf_page_texts",
        lambda _: [
            "2025 Form 1042-S\n"
            "Recipient's foreign taxpayer identification number 900101300123\n"
            "Income code 06\nGross income 123.45\nFederal tax withheld 18.52",
            "Instructions for Form 1042-S\nBox 1 Income code.",
        ],
    )

    result = parse_f1042s(path)

    assert result.to_dict("records") == [
        {
            "tax_year": 2025,
            "recipient_tin": "900101300123",
            "income_code": "06",
            "gross_income": Decimal("123.45"),
            "federal_tax_withheld": Decimal("18.52"),
            "source_file": "form-1042s.pdf",
            "source_page": 1,
            "source_row": 1,
        }
    ]


def test_parse_freedom_table_preserves_table_row_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "freedom.pdf"
    path.touch()
    pdf = FakePdf(
        [
            FakePage(
                tables=[
                    [
                        ["Дата", "Тип операции", "Тикер", "Количество", "Прибыль"],
                        ["2025-02-01", "Продажа", "ETN", "2", "10.50"],
                    ]
                ]
            )
        ]
    )
    monkeypatch.setattr("kz_tax_report.freedom_parser.pdfplumber.open", lambda _: pdf)

    result = parse_freedom_report(path)

    assert result.to_dict("records") == [
        {
            "date": "2025-02-01",
            "transaction_type": "Продажа",
            "symbol": "ETN",
            "deal_number": "",
            "quantity": Decimal("2"),
            "profit": Decimal("10.50"),
            "details": "",
            "source_file": "freedom.pdf",
            "source_page": 1,
            "source_table": 1,
            "source_row": 2,
        }
    ]


def test_parse_freedom_report_skips_summary_tables_and_accepts_ledger_without_ticker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "freedom.pdf"
    path.touch()
    pdf = FakePdf(
        [
            FakePage(
                tables=[
                    [
                        ["Краткое содержание операций", None, None],
                        ["Покупка", "10", "100"],
                    ],
                    [
                        [
                            "Номер сделки",
                            "Дата",
                            "Операция",
                            "Цена USD",
                            "Цена KZT",
                            "Количество",
                            "Сумма сделки USD",
                            "Сумма сделки KZT",
                            "Прибыль KZT",
                            "Детали",
                        ],
                        [
                            "DEAL-1",
                            "01.02.2025 10:00:00",
                            "Продажа",
                            "1.25 $",
                            "600.50 ₸",
                            "2",
                            "2.50 $",
                            "1201.00 ₸",
                            "200.75 ₸",
                            "Продажа ETN",
                        ],
                    ],
                ]
            )
        ]
    )
    monkeypatch.setattr("kz_tax_report.freedom_parser.pdfplumber.open", lambda _: pdf)

    result = parse_freedom_report(path)

    assert result.to_dict("records") == [
        {
            "date": "01.02.2025 10:00:00",
            "transaction_type": "Продажа",
            "symbol": "",
            "deal_number": "DEAL-1",
            "quantity": Decimal("2"),
            "profit": Decimal("200.75"),
            "details": "Продажа ETN",
            "source_file": "freedom.pdf",
            "source_page": 1,
            "source_table": 2,
            "source_row": 2,
        }
    ]


def test_fifo_matches_decimal_lots_and_keeps_sources() -> None:
    matches = match_fifo(
        purchases=[
            {"symbol": "ETN", "quantity": "3", "unit_cost": "10", "source_row": 4},
            {"symbol": "ETN", "quantity": "2", "unit_cost": "12", "source_row": 8},
        ],
        sales=[
            {"symbol": "ETN", "quantity": "4", "unit_price": "15", "source_row": 12}
        ],
    )

    assert [match.quantity for match in matches] == [Decimal("3"), Decimal("1")]
    assert [match.gain for match in matches] == [Decimal("15"), Decimal("3")]
    assert [match.purchase_source_row for match in matches] == [4, 8]
    assert matches[0].sale_source_row == 12


def test_fifo_rejects_sales_without_inventory() -> None:
    with pytest.raises(FifoError, match="Insufficient inventory"):
        match_fifo(
            purchases=[],
            sales=[{"symbol": "ETN", "quantity": "1", "unit_price": "15"}],
        )


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, response: FakeResponse | Exception):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, str], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_nbk_rate_provider_uses_environment_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KZ_TAX_REPORT_NBK_URL", "https://env.example/rates")
    monkeypatch.setenv("KZ_TAX_REPORT_NBK_TIMEOUT", "3.5")

    provider = NbkRateProvider(
        tmp_path / "nbk-rates.json", session=FakeSession(OSError())
    )

    assert provider.url == "https://env.example/rates"
    assert provider.timeout == 3.5


def test_nbk_rate_provider_caches_xml_and_uses_cached_fallback(tmp_path: Path) -> None:
    cache_path = tmp_path / "nbk-rates.json"
    response = FakeResponse(
        b"<rates><item><title>USD</title><description>500.25</description></item></rates>"
    )
    online = FakeSession(response)
    provider = NbkRateProvider(
        cache_path, url="https://example.test/rates", session=online
    )

    assert provider.get_rate(date(2025, 2, 1), "USD") == Decimal("500.25")
    assert online.calls[0]["params"] == {"fdate": "01.02.2025"}
    assert json.loads(cache_path.read_text()) == {"2025-02-01": {"USD": "500.25"}}

    offline = NbkRateProvider(
        cache_path,
        url="https://example.test/rates",
        session=FakeSession(OSError("offline")),
    )
    assert offline.get_rate(date(2025, 2, 2), "USD") == Decimal("500.25")


def test_nbk_rate_provider_uses_prior_cache_when_currency_is_absent(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "nbk-rates.json"
    cache_path.write_text('{"2025-02-01": {"USD": "500.25"}}', encoding="utf-8")
    holiday_response = FakeResponse(
        b"<rates><item><title>EUR</title><description>520.10</description></item></rates>"
    )
    provider = NbkRateProvider(
        cache_path,
        url="https://example.test/rates",
        session=FakeSession(holiday_response),
    )

    assert provider.get_rate(date(2025, 2, 2), "USD") == Decimal("500.25")

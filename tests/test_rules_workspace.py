from pathlib import Path

import pytest

from kz_tax_report.rules_workspace import RulesDraftError, TaxRulesDraft


RULES = """
year: 2025
approved: false
citation: Pending review
tax:
  rate: '0.10'
  foreign_tax_credit: true
income:
  dividends_line: '270.01.01'
  realized_gains_line: '270.01.02'
  exempt_gains_line: '270.01.03'
"""


def test_rules_draft_edits_and_materializes_without_mutating_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tax_rules_2025.yaml"
    source.write_text(RULES, encoding="utf-8")
    draft = TaxRulesDraft.from_path(source)

    draft.set_tax_rate("0.15")
    draft.set_citation("Verified source for tests")
    draft.set_approved(True)
    materialized = draft.materialize(tmp_path / "session")

    assert "rate: '0.10'" in source.read_text(encoding="utf-8")
    assert "rate: '0.15'" in materialized.read_text(encoding="utf-8")
    assert draft.approved is True


def test_rules_draft_rejects_unsupported_mapping() -> None:
    draft = TaxRulesDraft({"year": 2025, "income": {}})

    with pytest.raises(RulesDraftError, match="Unsupported income mapping"):
        draft.set_income_line("unknown", "value")

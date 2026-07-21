"""Session-only editing and materialization of year-specific tax rules."""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from kz_tax_report.tax_engine import RulesError, load_rules


class RulesDraftError(ValueError):
    """Raised when a session tax-rules draft cannot be used safely."""


@dataclass
class TaxRulesDraft:
    """An isolated in-memory copy of a YAML rules document."""

    document: dict[str, Any]

    @classmethod
    def from_path(cls, path: str | Path) -> "TaxRulesDraft":
        source_path = Path(path)
        try:
            document = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise RulesDraftError(f"Unable to read tax rules: {source_path}") from error
        if not isinstance(document, dict):
            raise RulesDraftError("Tax rules must be a YAML mapping")
        return cls(document=deepcopy(document))

    @property
    def year(self) -> int:
        try:
            return int(self.document["year"])
        except (KeyError, TypeError, ValueError) as error:
            raise RulesDraftError("Tax rules year must be an integer") from error

    @property
    def approved(self) -> bool:
        return self.document.get("approved") is True

    def set_approved(self, approved: bool) -> None:
        self.document["approved"] = bool(approved)

    def set_tax_rate(self, rate: str) -> None:
        number = self._decimal(rate, "tax.rate")
        if not 0 <= number <= 1:
            raise RulesDraftError("tax.rate must be between 0 and 1")
        self._mapping("tax")["rate"] = rate.strip()

    def set_mrp(self, value: str) -> None:
        if self._decimal(value, "mrp") < 0:
            raise RulesDraftError("mrp must not be negative")
        self.document["mrp"] = value.strip()

    def set_brackets(self, brackets: list[dict[str, str]]) -> None:
        normalized = []
        for bracket in brackets:
            if (
                not isinstance(bracket, dict)
                or "up_to" not in bracket
                or "rate" not in bracket
            ):
                raise RulesDraftError("Each tax bracket needs up_to and rate")
            up_to = self._decimal(str(bracket["up_to"]), "tax.brackets.up_to")
            rate = self._decimal(str(bracket["rate"]), "tax.brackets.rate")
            if up_to <= 0 or not 0 <= rate <= 1:
                raise RulesDraftError(
                    "Tax brackets must have positive limits and rates between 0 and 1"
                )
            normalized.append(
                {
                    "up_to": str(bracket["up_to"]).strip(),
                    "rate": str(bracket["rate"]).strip(),
                }
            )
        self._mapping("tax")["brackets"] = normalized

    def set_citation(self, citation: str) -> None:
        self.document["citation"] = citation.strip()

    def set_income_line(self, key: str, value: str) -> None:
        if key not in {"dividends_line", "realized_gains_line", "exempt_gains_line"}:
            raise RulesDraftError(f"Unsupported income mapping: {key}")
        self._mapping("income")[key] = value.strip()

    def set_form_label(self, key: str, value: str) -> None:
        if key not in {"dividends", "realized_gains", "exempt_gains"}:
            raise RulesDraftError(f"Unsupported form label: {key}")
        if not value.strip():
            raise RulesDraftError("Form labels must not be empty")
        self._mapping("form_labels")[key] = value.strip()

    def set_source_citation(self, key: str, value: str) -> None:
        if not key.strip() or not value.strip():
            raise RulesDraftError("Source citations need a key and URL")
        self._mapping("sources")[key.strip()] = value.strip()

    def set_source_evidence(self, evidence: dict[str, object]) -> None:
        source_key = str(evidence.get("source_key", "")).strip()
        if not source_key:
            raise RulesDraftError("Source evidence needs a source key")
        self._mapping("source_evidence")[source_key] = deepcopy(evidence)

    def materialize(self, directory: str | Path) -> Path:
        """Write this draft to an isolated directory and return its path."""

        destination_dir = Path(directory)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"tax_rules_{self.year}.yaml"
        try:
            destination.write_text(
                yaml.safe_dump(self.document, sort_keys=False), encoding="utf-8"
            )
        except (OSError, yaml.YAMLError) as error:
            raise RulesDraftError(
                f"Unable to write session tax rules: {destination}"
            ) from error
        return destination

    def validate_for_calculation(self, expected_year: int, path: str | Path) -> None:
        """Validate both the draft year and the existing approved-rule gate."""

        if self.year != expected_year:
            raise RulesDraftError(
                f"Rules year {self.year} does not match requested year {expected_year}"
            )
        try:
            load_rules(path)
        except RulesError as error:
            raise RulesDraftError(str(error)) from error

    def _decimal(self, value: str, field: str) -> Decimal:
        try:
            number = Decimal(value.strip())
        except (InvalidOperation, AttributeError) as error:
            raise RulesDraftError(f"{field} must be numeric") from error
        if not number.is_finite():
            raise RulesDraftError(f"{field} must be finite")
        return number

    def _mapping(self, key: str) -> dict[str, Any]:
        value = self.document.get(key)
        if not isinstance(value, dict):
            raise RulesDraftError(f"Tax rules section is missing: {key}")
        return value

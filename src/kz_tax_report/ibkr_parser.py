"""Parser for the multi-section IBKR Activity Statement CSV export."""

import csv
from pathlib import Path
from typing import TextIO

import pandas as pd


def parse_activity_statement(path: str | Path) -> dict[str, pd.DataFrame]:
    """Parse an IBKR statement into one DataFrame per section.

    Each output keeps the original CSV line and file name so downstream
    calculations can cite their source rows.
    """

    source_path = Path(path)
    sections: dict[str, list[dict[str, str | int]]] = {}
    headers: dict[str, list[str]] = {}

    with source_path.open("r", encoding="utf-8-sig", newline="") as source:
        _read_rows(source, source_path.name, sections, headers)

    return {
        section: pd.DataFrame(
            rows, columns=[*headers[section], "source_file", "source_row"]
        )
        for section, rows in sections.items()
    }


def _read_rows(
    source: TextIO,
    source_name: str,
    sections: dict[str, list[dict[str, str | int]]],
    headers: dict[str, list[str]],
) -> None:
    for source_row, row in enumerate(csv.reader(source), start=1):
        if len(row) < 2:
            continue

        section, marker, *values = row
        if marker == "Header":
            if not values or any(not column for column in values):
                raise ValueError(f"Invalid header at {source_name}:{source_row}")
            headers[section] = values
            sections.setdefault(section, [])
            continue

        if marker != "Data":
            continue
        if section not in headers:
            raise ValueError(f"Data before header at {source_name}:{source_row}")
        if len(values) != len(headers[section]):
            raise ValueError(
                f"Column count mismatch at {source_name}:{source_row}: "
                f"expected {len(headers[section])}, got {len(values)}"
            )

        record: dict[str, str | int] = dict(zip(headers[section], values, strict=True))
        record["source_file"] = source_name
        record["source_row"] = source_row
        sections[section].append(record)

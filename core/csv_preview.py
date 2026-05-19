from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CsvPreview:
    headers: list[str]
    rows: list[list[str]]


def read_csv_preview(path: str | Path, max_rows: int = 1000) -> CsvPreview:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        headers = next(reader, [])
        rows = []
        for index, row in enumerate(reader):
            if index >= max_rows:
                break
            rows.append(row)
    return CsvPreview(headers=headers, rows=rows)

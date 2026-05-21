from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.sleeves_loader import _read_excel_with_fallback
from core.xlsx_preview import read_xlsx_preview


def read_table(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(source)
    if suffix in {".xlsx", ".xlsm"}:
        try:
            return pd.read_excel(source)
        except Exception:  # noqa: BLE001
            try:
                return _read_excel_with_fallback(source)
            except Exception:  # noqa: BLE001
                preview = read_xlsx_preview(source, max_rows=10_000_000)
                return pd.DataFrame(preview.rows, columns=preview.headers)
    if suffix == ".xls":
        return pd.read_excel(source)
    raise ValueError(f"Unsupported table format: {source.suffix}")

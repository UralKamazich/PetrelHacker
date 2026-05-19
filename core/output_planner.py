from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.exporter import EXCEL_ROW_LIMIT


@dataclass(frozen=True)
class OutputPlan:
    path: Path
    format: str
    warning: str | None = None


def choose_output_plan(requested_path: str | Path, sleeve_count: int, nk: int | None) -> OutputPlan:
    path = Path(requested_path)
    max_data_rows = sleeve_count * (nk or 0)
    if path.suffix.lower() == ".xlsx" and max_data_rows + 1 > EXCEL_ROW_LIMIT:
        csv_path = path.with_suffix(".csv")
        return OutputPlan(
            path=csv_path,
            format="CSV",
            warning=(
                f"Estimated output rows ({max_data_rows}) exceed Excel limit "
                f"({EXCEL_ROW_LIMIT - 1} data rows). Saved CSV instead: {csv_path}"
            ),
        )
    if path.suffix.lower() == ".csv":
        return OutputPlan(path=path, format="CSV")
    return OutputPlan(path=path.with_suffix(".xlsx"), format="XLSX")

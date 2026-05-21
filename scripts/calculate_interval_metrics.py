from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interval_metrics import (  # noqa: E402
    IntervalMetricSettings,
    calculate_interval_metrics,
    write_interval_metrics_xlsx,
)
from core.table_io import read_table  # noqa: E402


def run_metrics(
    extracted_path: str,
    intervals_path: str,
    output_path: str,
    *,
    ntg_column: str | None,
    poro_column: str | None,
    perm_column: str | None,
    lithology_column: str | None,
    reservoir_values: list[str],
    property_columns: list[str],
) -> int:
    extracted = read_table(extracted_path)
    intervals = read_table(intervals_path)
    settings = IntervalMetricSettings(
        ntg_column=ntg_column,
        poro_column=poro_column,
        perm_column=perm_column,
        lithology_column=lithology_column,
        reservoir_values={_normalize_value(value) for value in reservoir_values},
        property_columns=property_columns,
    )
    result = calculate_interval_metrics(extracted, intervals, settings)
    for warning in result.warnings:
        print(f"Warning: {warning}")
    write_interval_metrics_xlsx(result, output_path)
    print(f"Rows written: {len(result.rows)}")
    print(f"Output: {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate interval metrics from extracted RESQML cells.")
    parser.add_argument("extracted_path", help="Extracted cell table, XLSX or CSV.")
    parser.add_argument("intervals_path", help="Well/Port interval table, XLSX or CSV.")
    parser.add_argument("output_path", help="Output metrics XLSX path.")
    parser.add_argument("--ntg-column", default="NTG")
    parser.add_argument("--poro-column", default="PORO")
    parser.add_argument("--perm-column", default=None, help="Defaults to first column containing 'perm'.")
    parser.add_argument("--lithology-column", default=None)
    parser.add_argument("--reservoir-values", nargs="*", default=[])
    parser.add_argument("--properties", nargs="*", default=[], help="Additional property columns for stats.")
    args = parser.parse_args()
    return run_metrics(
        args.extracted_path,
        args.intervals_path,
        args.output_path,
        ntg_column=args.ntg_column,
        poro_column=args.poro_column,
        perm_column=args.perm_column,
        lithology_column=args.lithology_column,
        reservoir_values=args.reservoir_values,
        property_columns=args.properties,
    )


def _normalize_value(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        return text[:-2]
    return text


if __name__ == "__main__":
    raise SystemExit(main())

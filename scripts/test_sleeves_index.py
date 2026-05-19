from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.grid_indexer import FastGridIndexer  # noqa: E402
from core.resqml_reader import ResqmlReader  # noqa: E402
from core.sleeves_loader import load_sleeves_table, validate_sleeves_table  # noqa: E402


def inspect_sleeves_index(epc_path: str, sleeves_path: str) -> int:
    reader = ResqmlReader(epc_path)
    reader.open()
    grids = reader.list_grids()
    if not grids:
        raise ValueError("No grids found in EPC.")
    reader.select_grid(grids[0].uuid)

    indexer = FastGridIndexer(reader, grids[0])
    indexer.build_column_index()

    sleeves = load_sleeves_table(sleeves_path)
    warnings = validate_sleeves_table(sleeves)
    print(f"Grid: {grids[0].title}")
    print(f"Shape NI/NJ/NK: {grids[0].ni}/{grids[0].nj}/{grids[0].nk}")
    print(f"XY bbox: {indexer.bbox}")
    print(f"Sleeves: {len(sleeves)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    print()

    for row in sleeves.itertuples(index=False):
        well = getattr(row, "Well", "")
        port = getattr(row, "Port", "")
        legacy_id = getattr(row, "Sleeve_ID", "")
        sleeve_id = f"{well}_{port}" if well != "" or port != "" else str(legacy_id)
        x = float(getattr(row, "X"))
        y = float(getattr(row, "Y"))
        match = indexer.find_column(x, y)
        if match is None:
            print(f"{sleeve_id}: outside grid at X={x}, Y={y}")
            continue
        print(
            f"{sleeve_id}: X={x:.2f}, Y={y:.2f} -> "
            f"I={match.i_1based}, J={match.j_1based}, distance={match.distance:.2f} m, "
            f"vertical cells={len(indexer.vertical_cells(x, y))}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Map sleeve X/Y coordinates to nearest RESQML grid columns.")
    parser.add_argument("epc_path", help="Path to .epc file")
    parser.add_argument("sleeves_path", help="Path to sleeves CSV/XLSX")
    args = parser.parse_args()
    return inspect_sleeves_index(args.epc_path, args.sleeves_path)


if __name__ == "__main__":
    raise SystemExit(main())

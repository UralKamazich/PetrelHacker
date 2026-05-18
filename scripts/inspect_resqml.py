from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.resqml_reader import ResqmlReader  # noqa: E402


def _shape_text(shape: tuple[int, ...] | None) -> str:
    return "unknown" if shape is None else " x ".join(str(value) for value in shape)


def inspect(epc_path: str, property_limit: int) -> int:
    reader = ResqmlReader(epc_path)
    reader.open()

    print(f"Opened EPC: {Path(epc_path).resolve()}")
    print(f"Backend: {reader.backend}")
    if reader.h5_path:
        print(f"Detected H5: {reader.h5_path.resolve()}")
    else:
        print("Detected H5: not found next to EPC")

    grids = reader.list_grids()
    print(f"Found grids: {len(grids)}")
    print()

    for grid in grids:
        print(f"[{grid.index}] Grid title: {grid.title}")
        print(f"UUID: {grid.uuid}")
        print(f"Type: {grid.grid_type or 'unknown'}")
        ni = "?" if grid.ni is None else grid.ni
        nj = "?" if grid.nj is None else grid.nj
        nk = "?" if grid.nk is None else grid.nk
        print(f"NI/NJ/NK: {ni} x {nj} x {nk}")
        if grid.hdf_paths:
            print("Geometry HDF paths:")
            for path in grid.hdf_paths[:8]:
                print(f"  - {path}")
            if len(grid.hdf_paths) > 8:
                print(f"  ... {len(grid.hdf_paths) - 8} more")
        print()

    if grids:
        reader.select_grid(grids[0].uuid)
    properties = reader.list_properties()
    print(f"Properties for selected grid: {len(properties)}")
    for prop in properties[:property_limit]:
        print(f"[{prop.index}] {prop.title}")
        print(f"  UUID: {prop.uuid}")
        print(f"  Type: {prop.property_type or 'unknown'}")
        print(f"  Indexable element: {prop.indexable_element or 'unknown'}")
        print(f"  UOM: {prop.uom or 'unknown'}")
        print(f"  Property kind: {prop.property_kind or 'unknown'}")
        print(f"  Shape: {_shape_text(prop.shape)}")
        print(f"  DType: {prop.dtype or 'unknown'}")
        if prop.hdf_paths:
            print(f"  HDF path: {prop.hdf_paths[0]}")
        print()

    if len(properties) > property_limit:
        print(f"... {len(properties) - property_limit} more properties not shown")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect RESQML EPC metadata without loading HDF5 arrays.")
    parser.add_argument("epc_path", help="Path to .epc file")
    parser.add_argument("--property-limit", type=int, default=50, help="Number of properties to print")
    args = parser.parse_args()
    return inspect(args.epc_path, args.property_limit)


if __name__ == "__main__":
    raise SystemExit(main())

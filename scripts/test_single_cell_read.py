from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.resqml_reader import PropertyInfo, ResqmlReader  # noqa: E402


def _require_h5py():
    try:
        import h5py  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "h5py is required for HDF5 cell reads. Install project dependencies: "
            "pip install -r requirements.txt"
        ) from exc
    return h5py


def _find_property(properties: list[PropertyInfo], selector: str) -> PropertyInfo:
    selector_lower = selector.lower()
    matches = [
        prop
        for prop in properties
        if prop.uuid.lower() == selector_lower or prop.title.lower() == selector_lower
    ]
    if not matches:
        available = ", ".join(prop.title for prop in properties[:20])
        raise ValueError(f"Property not found: {selector}. First available properties: {available}")
    return matches[0]


def _candidate_indices(
    shape: tuple[int, ...],
    grid_shape: tuple[int | None, int | None, int | None],
    i: int,
    j: int,
    k: int,
) -> list[tuple[str, tuple[Any, ...]]]:
    ni, nj, nk = grid_shape
    if len(shape) == 3:
        return [
            ("KJI", (k, j, i)),
            ("IJK", (i, j, k)),
            ("JIK", (j, i, k)),
            ("KIJ", (k, i, j)),
        ]
    if len(shape) == 1 and ni is not None and nj is not None and nk is not None:
        return [
            ("flat KJI", (k * nj * ni + j * ni + i,)),
            ("flat IJK", (i * nj * nk + j * nk + k,)),
        ]
    return []


def _in_bounds(shape: tuple[int, ...], index: tuple[Any, ...]) -> bool:
    if len(shape) != len(index):
        return False
    return all(isinstance(value, int) and 0 <= value < size for value, size in zip(index, shape))


def read_single_cell(epc_path: str, property_selector: str, i: int, j: int, k: int) -> int:
    h5py = _require_h5py()
    reader = ResqmlReader(epc_path)
    reader.open()
    grids = reader.list_grids()
    if not grids:
        raise ValueError("No grids found in EPC.")
    reader.select_grid(grids[0].uuid)
    grid_shape = reader.get_grid_shape()
    prop = _find_property(reader.list_properties(), property_selector)
    if not prop.hdf_paths:
        raise ValueError(f"Property has no HDF5 path: {prop.title}")
    if reader.h5_path is None:
        raise ValueError("H5 file was not found next to EPC.")

    hdf_path = prop.hdf_paths[0]
    print(f"Property: {prop.title}")
    print(f"UUID: {prop.uuid}")
    print(f"H5: {reader.h5_path.resolve()}")
    print(f"Dataset: {hdf_path}")
    print(f"Requested zero-based cell: i={i}, j={j}, k={k}")

    with h5py.File(reader.h5_path, "r") as h5:
        if hdf_path not in h5:
            raise ValueError(f"Dataset path not found in H5: {hdf_path}")
        dataset = h5[hdf_path]
        shape = tuple(int(dim) for dim in dataset.shape)
        print(f"Shape: {' x '.join(str(dim) for dim in shape)}")
        print(f"DType: {dataset.dtype}")

        candidates = _candidate_indices(shape, grid_shape, i, j, k)
        if not candidates:
            print("No automatic index candidates for this dataset rank.")
            return 0

        print("Candidate reads:")
        for label, index in candidates:
            if not _in_bounds(shape, index):
                print(f"  {label}: index {index} is out of bounds")
                continue
            value = dataset[index]
            if hasattr(value, "item"):
                value = value.item()
            print(f"  {label}: index {index} -> {value}")

    value = reader.get_property_value(prop.uuid, i, j, k)
    print(f"Reader get_property_value(): {value}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read one RESQML property value from HDF5.")
    parser.add_argument("epc_path", help="Path to .epc file")
    parser.add_argument("property", help="Property title or UUID, e.g. NTG")
    parser.add_argument("i", type=int, help="Zero-based I index")
    parser.add_argument("j", type=int, help="Zero-based J index")
    parser.add_argument("k", type=int, help="Zero-based K index")
    args = parser.parse_args()
    return read_single_cell(args.epc_path, args.property, args.i, args.j, args.k)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.model_reader import open_model_reader  # noqa: E402
from core.rescue_reader import RescueReader  # noqa: E402


def _shape_text(shape: tuple[int, ...] | None) -> str:
    return "unknown" if shape is None else " x ".join(str(value) for value in shape)


def _format_number(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def _find_properties(reader: RescueReader, names: list[str]) -> list:
    properties = reader.list_properties()
    if not names:
        return properties
    wanted = {name.lower() for name in names}
    matched = [prop for prop in properties if prop.title.lower() in wanted]
    missing = sorted(wanted - {prop.title.lower() for prop in matched})
    if missing:
        print(f"Missing requested properties: {', '.join(missing)}")
    return matched


def inspect(
    model_path: str,
    *,
    property_limit: int,
    decode_limit: int,
    sample_i: int,
    sample_j: int,
    sample_k_limit: int,
    property_names: list[str],
) -> int:
    reader = open_model_reader(model_path)
    if not isinstance(reader, RescueReader):
        raise ValueError(f"Path is not a Rescue model: {model_path}")

    print(f"Opened Rescue model: {reader.epc_path.resolve()}")
    print(f"Backend: {reader.backend}")

    grids = reader.list_grids()
    print(f"Found grids: {len(grids)}")
    for grid in grids:
        ni = "?" if grid.ni is None else grid.ni
        nj = "?" if grid.nj is None else grid.nj
        nk = "?" if grid.nk is None else grid.nk
        print(f"[{grid.index}] Grid title: {grid.title}")
        print(f"UUID: {grid.uuid}")
        print(f"Type: {grid.grid_type or 'unknown'}")
        print(f"NI/NJ/NK: {ni} x {nj} x {nk}")
    print()

    properties = reader.list_properties()
    shown_properties = _find_properties(reader, property_names)[:property_limit]
    print(f"Properties for selected grid: {len(properties)}")
    for prop in shown_properties:
        print(f"[{prop.index}] {prop.title}")
        print(f"  UUID: {prop.uuid}")
        print(f"  Type: {prop.property_type or 'unknown'}")
        print(f"  Indexable element: {prop.indexable_element or 'unknown'}")
        print(f"  UOM: {prop.uom or 'unknown'}")
        print(f"  Property kind: {prop.property_kind or 'unknown'}")
        print(f"  Shape: {_shape_text(prop.shape)}")
        print(f"  DType: {prop.dtype or 'unknown'}")
        if prop.hdf_paths:
            print(f"  File: {prop.hdf_paths[0]}")
        print()

    if len(properties) > property_limit and not property_names:
        print(f"... {len(properties) - property_limit} more properties not shown")
        print()

    decode_properties = _find_properties(reader, property_names)[:decode_limit]
    if decode_properties:
        print("Decoded property stats:")
    for prop in decode_properties:
        stats = reader.get_property_decode_stats(prop.uuid)
        print(f"[{prop.index}] {prop.title}")
        print(f"  File id: {stats['file_id']}")
        print(f"  Logical cells: {stats['logical_count']}")
        print(f"  Stored stream values: {stats['stored_count']}")
        print(f"  Valid cells: {stats['valid_count']}")
        print(f"  Blank cells: {stats['blank_count']}")
        print(f"  First run length: {stats['first_run_length']}")
        print(f"  Undefined value: {_format_number(stats['undefined_value'])}")
        print(f"  Invalid abs limit: {_format_number(stats['invalid_abs_limit'])}")
        if stats["valid_min"] is not None or stats["valid_max"] is not None:
            print(f"  Valid range: {_format_number(stats['valid_min'])} .. {_format_number(stats['valid_max'])}")
        print(f"  Min/Max/Mean: {_format_number(stats['min'])} / {_format_number(stats['max'])} / {_format_number(stats['mean'])}")
        column = reader.get_property_column_values(prop.uuid, sample_i - 1, sample_j - 1)
        sample = ", ".join(_format_number(value) for value in column[:sample_k_limit])
        print(f"  Column I/J={sample_i}/{sample_j}, first {sample_k_limit} K: {sample}")
        print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Petrel Rescue metadata and decoded property streams.")
    parser.add_argument("model_path", help="Path to Rescue folder or main .bin file")
    parser.add_argument("--property-limit", type=int, default=50, help="Number of properties to print")
    parser.add_argument("--decode-limit", type=int, default=0, help="Number of properties to decode and summarize")
    parser.add_argument("--property", action="append", default=[], help="Property title to inspect; can be repeated")
    parser.add_argument("--sample-i", type=int, default=1, help="One-based I index for column sample")
    parser.add_argument("--sample-j", type=int, default=1, help="One-based J index for column sample")
    parser.add_argument("--sample-k-limit", type=int, default=12, help="Number of K values to show from the sample column")
    args = parser.parse_args()
    return inspect(
        args.model_path,
        property_limit=args.property_limit,
        decode_limit=args.decode_limit,
        sample_i=args.sample_i,
        sample_j=args.sample_j,
        sample_k_limit=args.sample_k_limit,
        property_names=args.property,
    )


if __name__ == "__main__":
    raise SystemExit(main())

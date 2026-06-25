from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.grid_indexer import FastGridIndexer  # noqa: E402
from core.exporter import default_extraction_output_path  # noqa: E402
from core.model_reader import open_model_reader  # noqa: E402
from core.property_extractor import ExtractionSettings, PropertyExtractor, write_extraction_log  # noqa: E402
from core.sleeves_loader import load_sleeves_table, validate_sleeves_table  # noqa: E402


def run_extraction(
    epc_path: str,
    sleeves_path: str,
    output_path: str | None,
    property_names: list[str],
    include_inactive: bool,
) -> int:
    output = str(default_extraction_output_path(sleeves_path) if output_path is None else Path(output_path).with_suffix(".xlsx"))
    reader = open_model_reader(epc_path)
    grids = reader.list_grids()
    if not grids:
        raise ValueError("No grids found in EPC.")
    grid = grids[0]
    reader.select_grid(grid.uuid)

    properties = reader.list_properties()
    selected = []
    requested = {name.lower() for name in property_names}
    for prop in properties:
        if prop.title.lower() in requested or prop.uuid.lower() in requested:
            selected.append(prop)
    if not selected:
        available = ", ".join(prop.title for prop in properties[:20])
        raise ValueError(f"No requested properties found. Available examples: {available}")

    sleeves = load_sleeves_table(sleeves_path)
    warnings = validate_sleeves_table(sleeves)
    if warnings:
        for warning in warnings:
            print(f"Warning: {warning}")

    indexer = FastGridIndexer(reader, grid)
    print("Building fast grid index...")
    indexer.build_column_index()
    print(f"Grid XY bbox: {indexer.bbox}")

    settings = ExtractionSettings(
        sampling_mode="fast",
        skip_inactive=not include_inactive,
        selected_property_uuids=[prop.uuid for prop in selected],
    )
    extractor = PropertyExtractor(reader, indexer, settings)

    def log(message: str) -> None:
        print(message)

    def progress(current: int, total: int) -> None:
        print(f"Progress: {current}/{total}")

    stats = extractor.extract_to_xlsx(
        sleeves,
        output_path=output,
        progress_callback=progress,
        log_callback=log,
    )
    log_path = Path(output).with_name("extraction_log.txt")
    write_extraction_log(
        log_path,
        epc_path=epc_path,
        h5_path=reader.h5_path,
        grid_title=grid.title,
        grid_uuid=grid.uuid,
        grid_shape=reader.get_grid_shape(),
        selected_properties=[prop.title for prop in selected],
        sleeves_path=sleeves_path,
        output_path=output,
        settings=settings,
        stats=stats,
    )
    print(f"Rows written: {stats.extracted_rows}")
    print(f"Log written: {log_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fast sleeve property extraction to XLSX.")
    parser.add_argument("epc_path")
    parser.add_argument("sleeves_path")
    parser.add_argument("output_path", nargs="?", help="Optional .xlsx output path. Defaults next to sleeves file.")
    parser.add_argument("--properties", nargs="+", required=True, help="Property titles or UUIDs")
    parser.add_argument("--include-inactive", action="store_true", help="Do not skip inactive cells")
    args = parser.parse_args()
    return run_extraction(
        args.epc_path,
        args.sleeves_path,
        args.output_path,
        args.properties,
        include_inactive=args.include_inactive,
    )


if __name__ == "__main__":
    raise SystemExit(main())

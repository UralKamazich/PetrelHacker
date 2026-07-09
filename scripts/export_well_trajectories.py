from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.model_reader import open_model_reader, resolve_model_path  # noqa: E402
from core.resqml_reader import ResqmlReader  # noqa: E402


def export(model_path: str, output_path: str | None, include_points: bool) -> int:
    resolved_path = resolve_model_path(model_path)
    if resolved_path.suffix.lower() == ".epc":
        reader = ResqmlReader(resolved_path)
        reader.open(include_properties=False)
    else:
        reader = open_model_reader(resolved_path)
    if not hasattr(reader, "list_well_trajectories"):
        print("Selected model backend does not expose RESQML well trajectories.")
        return 0

    trajectories = reader.list_well_trajectories()
    print(f"Model: {getattr(reader, 'epc_path', model_path)}")
    print(f"Backend: {getattr(reader, 'backend', '-')}")
    print(f"Well trajectories: {len(trajectories)}")
    for trajectory in trajectories:
        print(
            f"[{trajectory.index}] {trajectory.well_name} | {trajectory.title} | "
            f"points={trajectory.point_count or '?'} | xyz={trajectory.xyz_hdf_path or '-'} | md={trajectory.md_hdf_path or '-'}"
        )

    if not output_path:
        return 0

    output = Path(output_path)
    summary = pd.DataFrame(asdict(trajectory) for trajectory in trajectories)
    point_rows = []
    if include_points:
        for trajectory in trajectories:
            try:
                point_rows.extend(asdict(point) for point in reader.get_well_trajectory_points(trajectory.uuid))
            except Exception as exc:  # noqa: BLE001
                print(f"Warning: cannot read points for {trajectory.title}: {exc}")
    points = pd.DataFrame(point_rows)

    if output.suffix.lower() in {".xlsx", ".xlsm"}:
        with pd.ExcelWriter(output) as writer:
            summary.to_excel(writer, sheet_name="Trajectories", index=False)
            points.to_excel(writer, sheet_name="Points", index=False)
    else:
        if include_points:
            points.to_csv(output, index=False)
        else:
            summary.to_csv(output, index=False)
    print(f"Written: {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and export RESQML well trajectory points.")
    parser.add_argument("model_path", help="Path to RESQML .epc or model folder")
    parser.add_argument("--output", help="Optional .xlsx/.csv export path")
    parser.add_argument("--points", action="store_true", help="Export trajectory point rows as well")
    args = parser.parse_args()
    return export(args.model_path, args.output, args.points)


if __name__ == "__main__":
    raise SystemExit(main())

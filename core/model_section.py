from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core.grid_indexer import FastGridIndexer
from core.model_reader import open_model_reader, resolve_model_path
from core.resqml_reader import ResqmlReader, WellTrajectoryInfo


@dataclass(frozen=True)
class SectionCell:
    station_index: int
    well_name: str
    md: float | None
    distance: float
    horizontal_distance: float
    x: float
    y: float
    z: float
    i: int
    j: int
    k: int
    tvd_top: float
    tvd_base: float
    tvd_center: float
    value: float | None


@dataclass(frozen=True)
class SectionTrajectoryPoint:
    md: float | None
    distance: float
    horizontal_distance: float
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class SectionResult:
    model_path: str
    well_name: str
    trajectory_uuid: str
    property_title: str
    property_uuid: str
    station_count: int
    cell_count: int
    rows: list[SectionCell]
    trajectory_points: list[SectionTrajectoryPoint]


def extract_well_section(
    model_path: str | Path,
    property_uuid: str,
    *,
    grid_uuid: str | None = None,
    trajectory_model_path: str | Path | None = None,
    well_name: str | None = None,
    trajectory_uuid: str | None = None,
    sample_step: float = 25.0,
    depth_offset: float = 0.0,
    skip_inactive: bool = True,
    max_stations: int = 1200,
    extra_md_values: list[float] | tuple[float, ...] | None = None,
    progress_callback=None,
) -> SectionResult:
    resolved_path = resolve_model_path(model_path)
    resolved_trajectory_path = resolve_model_path(trajectory_model_path) if trajectory_model_path else resolved_path
    if resolved_trajectory_path.suffix.lower() != ".epc":
        raise ValueError("Well trajectory source requires a RESQML .epc model.")

    reader = open_model_reader(resolved_path)
    grids = reader.list_grids()
    if not grids:
        raise ValueError("No grids found in model.")
    grid = _select_grid(grids, grid_uuid)
    reader.select_grid(grid.uuid)

    trajectory_reader = reader if isinstance(reader, ResqmlReader) and resolved_trajectory_path == resolved_path else ResqmlReader(resolved_trajectory_path)
    if trajectory_reader is not reader:
        trajectory_reader.open(include_properties=False, validate_with_resqpy=False)

    trajectory = _select_trajectory(trajectory_reader.list_well_trajectories(), well_name, trajectory_uuid)
    prop = _select_property(reader.list_properties(), property_uuid)
    points = trajectory_reader.get_well_trajectory_points(trajectory.uuid)
    if len(points) < 2:
        raise ValueError(f"Trajectory has fewer than two points: {trajectory.well_name}")

    stations = _sample_trajectory(points, sample_step, max_stations, extra_md_values=extra_md_values)
    indexer = FastGridIndexer(reader, grid)
    indexer.build_column_index()
    matched_stations: list[tuple[dict[str, float | None], object | None]] = []
    unique_columns: set[tuple[int, int]] = set()
    for station in stations:
        match = indexer.find_column(station["x"], station["y"])
        matched_stations.append((station, match))
        if match is not None:
            unique_columns.add((match.i, match.j))

    column_cache = _read_section_columns(reader, prop, grid, unique_columns)
    rows: list[SectionCell] = []

    for station_index, (station, match) in enumerate(matched_stations):
        if progress_callback:
            progress_callback(station_index, len(stations))
        if match is None:
            continue
        key = (match.i, match.j)
        values, geometry, active = column_cache[key]
        station_geometry = _geometry_column_depths_at_xy(geometry, float(station["x"]), float(station["y"]))
        row_count = min(len(values), len(station_geometry["TVD_top"]), len(station_geometry["TVD_base"]))
        for k in range(row_count):
            if skip_inactive and active is not None and k < len(active) and not bool(active[k]):
                continue
            top = float(station_geometry["TVD_top"][k]) + depth_offset
            base = float(station_geometry["TVD_base"][k]) + depth_offset
            value = float(values[k]) if np.isfinite(values[k]) else None
            rows.append(
                SectionCell(
                    station_index=station_index,
                    well_name=trajectory.well_name,
                    md=station["md"],
                    distance=station["distance"],
                    horizontal_distance=station["horizontal_distance"],
                    x=station["x"],
                    y=station["y"],
                    z=station["z"],
                    i=match.i + 1,
                    j=match.j + 1,
                    k=k + 1,
                    tvd_top=top,
                    tvd_base=base,
                    tvd_center=(top + base) / 2.0,
                    value=value,
                )
            )

    if progress_callback:
        progress_callback(len(stations), len(stations))
    return SectionResult(
        model_path=str(resolved_path),
        well_name=trajectory.well_name,
        trajectory_uuid=trajectory.uuid,
        property_title=prop.title,
        property_uuid=prop.uuid,
        station_count=len(stations),
        cell_count=len(rows),
        rows=rows,
        trajectory_points=[
            SectionTrajectoryPoint(
                md=point.md,
                distance=point.distance_along,
                horizontal_distance=point.horizontal_distance,
                x=point.x,
                y=point.y,
                z=point.z,
            )
            for point in points
        ],
    )


def _select_grid(grids, grid_uuid: str | None):
    if grid_uuid:
        normalized = grid_uuid.lower()
        for grid in grids:
            if grid.uuid.lower() == normalized:
                return grid
        raise ValueError(f"Selected grid UUID was not found: {grid_uuid}")
    if len(grids) > 1:
        raise ValueError("Model contains multiple grids. Select an internal model before drawing a section.")
    return grids[0]


def _read_section_columns(reader, prop, grid, columns: set[tuple[int, int]]):
    if not isinstance(reader, ResqmlReader) and all(
        hasattr(reader, name) for name in ("get_property_column_values", "get_cell_geometry_column", "get_cell_active_column")
    ):
        return _read_section_columns_via_reader(reader, prop, columns)

    if reader.h5_path is None:
        raise ValueError("H5 file was not found next to EPC.")
    if not prop.hdf_paths:
        raise ValueError(f"Property has no HDF5 path: {prop.title}")

    try:
        import h5py  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("h5py is required for section reads.") from exc

    ni, nj, nk = reader.get_grid_shape()
    if ni is None or nj is None or nk is None:
        raise ValueError("Selected grid has incomplete NI/NJ/NK metadata.")
    points_path = reader._points_hdf_path()
    active_path = reader._cell_geometry_path()
    property_path = prop.hdf_paths[0]
    cache = {}
    with h5py.File(reader.h5_path, "r") as h5:
        if property_path not in h5:
            raise ValueError(f"Dataset path not found in H5: {property_path}")
        if points_path not in h5:
            raise ValueError(f"Points dataset path not found in H5: {points_path}")
        property_dataset = h5[property_path]
        points_dataset = h5[points_path]
        active_dataset = h5[active_path] if active_path and active_path in h5 else None
        for i, j in columns:
            values = _property_column_from_dataset(property_dataset, i, j, ni, nj, nk)
            geometry = _geometry_column_from_dataset(points_dataset, i, j, ni, nj, nk)
            active = _active_column_from_dataset(active_dataset, i, j, ni, nj, nk)
            cache[(i, j)] = (values, geometry, active)
    return cache


def _read_section_columns_via_reader(reader, prop, columns: set[tuple[int, int]]):
    get_columns = getattr(reader, "get_property_columns_values", None)
    values_by_column = get_columns(prop.uuid, columns) if callable(get_columns) else None
    cache = {}
    for i, j in columns:
        source_values = (
            values_by_column[(i, j)]
            if values_by_column is not None
            else reader.get_property_column_values(prop.uuid, i, j)
        )
        values = _safe_float_array(source_values)
        geometry = reader.get_cell_geometry_column(i, j)
        active = reader.get_cell_active_column(i, j)
        active_values = np.asarray(active, dtype=bool).reshape(-1) if active is not None else None
        cache[(i, j)] = (values.reshape(-1), geometry, active_values)
    return cache


def _safe_float_array(values) -> np.ndarray:
    converted = []
    for value in np.asarray(values, dtype=object).reshape(-1):
        if value is None:
            converted.append(np.nan)
            continue
        if isinstance(value, str):
            text = value.strip()
            if not text or text.lower() in {"nan", "none", "null", "undefined"}:
                converted.append(np.nan)
                continue
            value = text.replace(",", ".")
        try:
            converted.append(float(value))
        except (TypeError, ValueError):
            converted.append(np.nan)
    return np.asarray(converted, dtype=float)


def _property_column_from_dataset(dataset, i: int, j: int, ni: int, nj: int, nk: int) -> np.ndarray:
    shape = tuple(int(dim) for dim in dataset.shape)
    if shape == (nk, nj, ni):
        values = dataset[:, j, i]
    elif shape == (ni, nj, nk):
        values = dataset[i, j, :]
    elif len(shape) == 1 and shape[0] == nk * nj * ni:
        start = j * ni + i
        values = dataset[start : nk * nj * ni : nj * ni]
    else:
        raise ValueError(
            f"Unsupported property dataset shape: {shape}; expected {(nk, nj, ni)}, {(ni, nj, nk)} or flat {nk * nj * ni}"
        )
    return np.asarray(values, dtype=float).reshape(-1)


def _geometry_column_from_dataset(dataset, i: int, j: int, ni: int, nj: int, nk: int) -> dict[str, list[float]]:
    base_pillar_count = (ni + 1) * (nj + 1)
    pillar_indices = [
        j * (ni + 1) + i,
        j * (ni + 1) + i + 1,
        (j + 1) * (ni + 1) + i,
        (j + 1) * (ni + 1) + i + 1,
    ]
    if len(dataset.shape) == 4:
        if dataset.shape[0] < nk + 1 or dataset.shape[1] < nj + 1 or dataset.shape[2] < ni + 1:
            raise ValueError(f"Unsupported Points dataset shape: {dataset.shape}")
        points = np.asarray(
            [
                dataset[:, j, i, :],
                dataset[:, j, i + 1, :],
                dataset[:, j + 1, i, :],
                dataset[:, j + 1, i + 1, :],
            ],
            dtype=float,
        ).transpose(1, 0, 2)
    elif len(dataset.shape) == 3:
        if dataset.shape[0] < nk + 1 or dataset.shape[1] < base_pillar_count:
            raise ValueError(f"Unsupported Points dataset shape: {dataset.shape}")
        points = np.asarray(dataset[:, pillar_indices, :], dtype=float)
    else:
        raise ValueError(f"Unsupported Points dataset shape: {dataset.shape}")

    return {"points": points}


def _geometry_column_depths_at_xy(geometry: dict[str, np.ndarray], x: float, y: float) -> dict[str, list[float]]:
    if "points" not in geometry:
        return {
            "TVD_top": [float(value) for value in geometry.get("TVD_top", [])],
            "TVD_base": [float(value) for value in geometry.get("TVD_base", [])],
        }
    points = np.asarray(geometry["points"], dtype=float)
    interface_z = np.asarray([_plane_z_at_xy(interface_points, x, y) for interface_points in points], dtype=float)
    interface_depth = _z_to_depth(interface_z)
    top_depth = np.minimum(interface_depth[:-1], interface_depth[1:])
    base_depth = np.maximum(interface_depth[:-1], interface_depth[1:])
    return {
        "TVD_top": [float(value) for value in top_depth],
        "TVD_base": [float(value) for value in base_depth],
    }


def _plane_z_at_xy(interface_points: np.ndarray, x: float, y: float) -> float:
    corners = np.asarray(interface_points, dtype=float)
    finite = np.isfinite(corners).all(axis=1)
    corners = corners[finite]
    if len(corners) < 3:
        return float(np.nanmean(interface_points[:, 2]))
    matrix = np.column_stack([corners[:, 0], corners[:, 1], np.ones(len(corners), dtype=float)])
    try:
        coefficients, *_ = np.linalg.lstsq(matrix, corners[:, 2], rcond=None)
        z = float(coefficients[0] * x + coefficients[1] * y + coefficients[2])
    except Exception:  # noqa: BLE001
        z = float(np.nanmean(corners[:, 2]))
    if not np.isfinite(z):
        z = float(np.nanmean(corners[:, 2]))
    return z


def _active_column_from_dataset(dataset, i: int, j: int, ni: int, nj: int, nk: int) -> np.ndarray | None:
    if dataset is None:
        return None
    shape = tuple(int(dim) for dim in dataset.shape)
    if shape == (nk, nj, ni):
        values = dataset[:, j, i]
    elif shape == (ni, nj, nk):
        values = dataset[i, j, :]
    else:
        return None
    return np.asarray(values, dtype=bool).reshape(-1)


def _z_to_depth(values):
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size and float(np.nanmean(finite)) < 0.0:
        return -arr
    return arr


def _select_trajectory(
    trajectories: list[WellTrajectoryInfo],
    well_name: str | None,
    trajectory_uuid: str | None,
) -> WellTrajectoryInfo:
    if trajectory_uuid:
        normalized = trajectory_uuid.lower()
        for trajectory in trajectories:
            if trajectory.uuid == normalized:
                return trajectory
        raise ValueError(f"Trajectory UUID not found: {trajectory_uuid}")
    if well_name:
        for trajectory in trajectories:
            if trajectory.well_name == well_name:
                return trajectory
        raise ValueError(f"Well trajectory not found: {well_name}")
    raise ValueError("Select a well trajectory.")


def _select_property(properties, property_uuid: str):
    normalized = property_uuid.lower()
    for prop in properties:
        if prop.uuid.lower() == normalized:
            return prop
    raise ValueError(f"Property UUID not found: {property_uuid}")


def _sample_trajectory(
    points,
    sample_step: float,
    max_stations: int,
    *,
    extra_md_values: list[float] | tuple[float, ...] | None = None,
) -> list[dict[str, float | None]]:
    md_values = np.asarray([np.nan if point.md is None else point.md for point in points], dtype=float)
    distance_values = np.asarray([point.distance_along for point in points], dtype=float)
    horizontal_distance_values = np.asarray([point.horizontal_distance for point in points], dtype=float)
    x_values = np.asarray([point.x for point in points], dtype=float)
    y_values = np.asarray([point.y for point in points], dtype=float)
    z_values = np.asarray([point.z for point in points], dtype=float)

    if np.isfinite(md_values).all() and np.nanmax(md_values) > np.nanmin(md_values):
        axis = md_values
        axis_name = "md"
    else:
        axis = distance_values
        axis_name = "distance"
    order = np.argsort(axis)
    axis = axis[order]
    distance_values = distance_values[order]
    horizontal_distance_values = horizontal_distance_values[order]
    md_values = md_values[order]
    x_values = x_values[order]
    y_values = y_values[order]
    z_values = z_values[order]

    unique_axis, unique_indices = np.unique(axis, return_index=True)
    axis = unique_axis
    distance_values = distance_values[unique_indices]
    horizontal_distance_values = horizontal_distance_values[unique_indices]
    md_values = md_values[unique_indices]
    x_values = x_values[unique_indices]
    y_values = y_values[unique_indices]
    z_values = z_values[unique_indices]
    if len(axis) < 2:
        raise ValueError("Trajectory has fewer than two unique measured points.")

    start = float(axis[0])
    stop = float(axis[-1])
    step = float(sample_step) if sample_step and sample_step > 0 else 0.0
    if step > 0:
        samples = np.arange(start, stop, step, dtype=float)
        if not len(samples) or samples[-1] < stop:
            samples = np.concatenate([samples, np.asarray([stop], dtype=float)])
    else:
        samples = axis
    if axis_name == "md" and extra_md_values:
        extra = np.asarray([value for value in extra_md_values if np.isfinite(value) and start <= value <= stop], dtype=float)
        if len(extra):
            samples = np.concatenate([samples, extra])
            samples = np.unique(samples)
    if len(samples) > max_stations:
        required = np.asarray([], dtype=float)
        if axis_name == "md" and extra_md_values:
            required = np.asarray([value for value in extra_md_values if np.isfinite(value) and start <= value <= stop], dtype=float)
            required = np.unique(required)
        regular_count = max(2, int(max_stations) - len(required))
        samples = np.concatenate([np.linspace(start, stop, regular_count), required])
        samples = np.unique(samples)

    stations: list[dict[str, float | None]] = []
    for value in samples:
        md = float(np.interp(value, axis, md_values)) if np.isfinite(md_values).all() else None
        distance = float(np.interp(value, axis, distance_values))
        horizontal_distance = float(np.interp(value, axis, horizontal_distance_values))
        stations.append(
            {
                "md": md if axis_name == "md" else md,
                "distance": distance,
                "horizontal_distance": horizontal_distance,
                "x": float(np.interp(value, axis, x_values)),
                "y": float(np.interp(value, axis, y_values)),
                "z": float(np.interp(value, axis, z_values)),
            }
        )
    return stations

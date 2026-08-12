from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import math
import re
import struct
from xml.etree import ElementTree as ET

import numpy as np

from core.resqml_reader import GridInfo, PropertyInfo, WellTrajectoryInfo, WellTrajectoryPoint


RESCUE_MODEL_HEADER = b"\x25Rescue Model File\x00"
RESCUE_GEOMETRY_LABEL = b"Rescue Geometry File"
RESCUE_PROPERTY_LABEL = b"Rescue Property File"
RESCUE_TRIPLET_LABEL = b"Rescue Triplet File"
PROPERTY_ARRAY_OFFSET = 25
RESCUE_TRAILER = b"abracadabra jump jump\x00"
DEFAULT_INVALID_ABS_VALUE_LIMIT = np.float32(1e15)


@dataclass(frozen=True)
class _PropertyFile:
    file_id: int
    path: Path
    values_offset: int
    value_count: int
    undefined_value: float | None
    first_run_length: int


@dataclass(frozen=True)
class _GeometryFile:
    path: Path
    block_starts: tuple[int, ...]
    raw_ni: int
    raw_nj: int
    raw_nk: int


@dataclass(frozen=True)
class RescueNamedHorizon:
    uuid: str
    title: str
    grid_uuid: str
    k_index: int = -1


@dataclass(frozen=True)
class _HorizonFile:
    file_id: int
    path: Path
    title: str


@dataclass(frozen=True)
class _TrajectoryFile:
    file_id: int
    path: Path
    title: str


def is_rescue_path(path: str | Path) -> bool:
    candidate = Path(path)
    if candidate.is_dir():
        return _find_rescue_model_file(candidate) is not None
    if not candidate.is_file():
        return False
    try:
        return _read_file_head(candidate, len(RESCUE_MODEL_HEADER)).startswith(RESCUE_MODEL_HEADER)
    except OSError:
        return False


class RescueReader:
    """Small Petrel Rescue flat-file reader.

    This reader intentionally implements the same narrow API that the existing
    extractor uses from ResqmlReader. Rescue stores Petrel grid exports in a
    compact proprietary flat-file layout. The implementation below supports the
    pieces needed by PetrelHacker: model metadata, property file discovery,
    regular XY indexing from CRS examples, and streaming big-endian float32
    property values.
    """

    def __init__(self, path: str | Path):
        self.model_path = Path(path)
        self.root_path: Path | None = None
        self.main_path: Path | None = None
        self.backend = "rescue"
        self._grids: list[GridInfo] = []
        self._properties: list[PropertyInfo] = []
        self._property_files: dict[str, _PropertyFile] = {}
        self._decoded_properties: OrderedDict[str, np.ndarray] = OrderedDict()
        self._decoded_property_cache_limit = 3
        self._decoded_geometry_columns: OrderedDict[int, np.ndarray] = OrderedDict()
        self._decoded_geometry_cache_limit = 256
        self._selected_grid_uuid: str | None = None
        self._xy_bounds: tuple[float, float, float, float] | None = None
        self._geometry_file: _GeometryFile | None = None
        self._horizon_files: dict[str, _HorizonFile] = {}
        self._decoded_horizon_z: OrderedDict[str, np.ndarray] = OrderedDict()
        self._decoded_horizon_cache_limit = 64
        self._horizon_xy: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self._horizon_cell_xy: np.ndarray | None = None
        self._geometry_blocks_by_xy: dict[tuple[float, float], int] | None = None
        self._trajectory_files: dict[str, _TrajectoryFile] = {}

    @property
    def epc_path(self) -> Path:
        return self.main_path or self.model_path

    @property
    def h5_path(self) -> Path | None:
        return None

    def open(self) -> None:
        self.main_path = self._resolve_main_path(self.model_path)
        self.root_path = self.main_path.parent
        geom_path = self._find_geometry_file()
        raw_ni, raw_nj, raw_nk = _read_rescue_geometry_shape(geom_path)
        if raw_ni < 2 or raw_nj < 2 or raw_nk < 2:
            raise ValueError(f"Rescue geometry has invalid raw node shape: {raw_ni}/{raw_nj}/{raw_nk}")
        ni, nj, nk = raw_ni - 1, raw_nj - 1, raw_nk - 1
        self._geometry_file = _read_rescue_geometry_file_info(geom_path, raw_ni, raw_nj, raw_nk)
        self._xy_bounds = _read_xy_bounds_from_crsmeta(self.root_path)

        grid_uuid = f"rescue-grid:{self.main_path.stem}"
        self._grids = [
            GridInfo(
                index=0,
                title=self.main_path.stem,
                uuid=grid_uuid,
                ni=ni,
                nj=nj,
                nk=nk,
                grid_type="RescueGrid",
                hdf_paths=(),
            )
        ]
        self._selected_grid_uuid = grid_uuid
        property_files = self._discover_property_files()
        self._properties = self._parse_properties(property_files)
        self._horizon_files = self._discover_horizon_files()
        self._trajectory_files = self._discover_trajectory_files()

    def list_grids(self) -> list[GridInfo]:
        return list(self._grids)

    def select_grid(self, grid_uuid: str) -> None:
        if not any(grid.uuid == grid_uuid for grid in self._grids):
            raise ValueError(f"Grid UUID not found: {grid_uuid}")
        self._selected_grid_uuid = grid_uuid

    def list_properties(self) -> list[PropertyInfo]:
        return list(self._properties)

    def list_named_horizons(self) -> list[RescueNamedHorizon]:
        grid_uuid = self._grids[0].uuid if self._grids else ""
        return [
            RescueNamedHorizon(uuid=uuid, title=info.title, grid_uuid=grid_uuid)
            for uuid, info in self._horizon_files.items()
        ]

    def get_named_horizon_depth(self, horizon_uuid: str, x: float, y: float) -> float | None:
        return self.get_named_horizon_depths((horizon_uuid,), x, y).get(horizon_uuid)

    def get_named_horizon_depths(
        self,
        horizon_uuids: list[str] | tuple[str, ...],
        x: float,
        y: float,
    ) -> dict[str, float]:
        selected = [uuid for uuid in horizon_uuids if uuid in self._horizon_files]
        if not selected or self._xy_bounds is None:
            return {}
        local_x, local_y, source_indices = self._horizon_sample_points()
        if local_x.size == 0:
            return {}
        xmin, xmax, ymin, ymax = self._xy_bounds
        query_x = float(x) - (xmin - float(np.nanmin(local_x)))
        query_y = float(y) - (ymin - float(np.nanmin(local_y)))
        distances_sq = (local_x - query_x) ** 2 + (local_y - query_y) ** 2
        nearest = int(np.nanargmin(distances_sq))
        cell_size = max(
            abs(xmax - xmin) / max(self._grids[0].ni or 1, 1),
            abs(ymax - ymin) / max(self._grids[0].nj or 1, 1),
        )
        if float(distances_sq[nearest]) > (cell_size * 2.0) ** 2:
            return {}
        source_index = int(source_indices[nearest])
        result: dict[str, float] = {}
        for horizon_uuid in selected:
            z = float(self._horizon_z_values(horizon_uuid)[source_index])
            if math.isfinite(z) and abs(z) < 1e20:
                result[horizon_uuid] = abs(z)
        return result

    def list_md_datums(self) -> list[object]:
        return []

    def list_well_trajectories(self) -> list[WellTrajectoryInfo]:
        return [
            WellTrajectoryInfo(
                index=index,
                title=info.title,
                uuid=uuid,
                well_name=info.title,
                trajectory_type="RescueTripletTrajectory",
                hdf_paths=(str(info.path),),
                xyz_hdf_path=str(info.path),
                point_count=_triplet_point_count(info.path),
            )
            for index, (uuid, info) in enumerate(self._trajectory_files.items())
        ]

    def get_well_trajectory_points(self, trajectory_uuid: str) -> list[WellTrajectoryPoint]:
        info = self._trajectory_files.get(trajectory_uuid)
        if info is None:
            raise ValueError(f"Well trajectory UUID not found: {trajectory_uuid}")
        x_values, y_values, z_values = _decode_triplet_file(info.path)
        valid = (
            np.isfinite(x_values)
            & np.isfinite(y_values)
            & np.isfinite(z_values)
            & (np.abs(x_values) < 1e20)
            & (np.abs(y_values) < 1e20)
            & (np.abs(z_values) < 1e20)
        )
        xyz = np.stack((x_values[valid], y_values[valid], z_values[valid]), axis=1).astype(float)
        if xyz.size == 0:
            return []
        offset_x, offset_y = self._local_xy_offsets()
        xyz[:, 0] += offset_x
        xyz[:, 1] += offset_y
        distances = _cumulative_distances(xyz)
        horizontal_distances = _cumulative_distances(xyz[:, :2])
        return [
            WellTrajectoryPoint(
                trajectory_uuid=trajectory_uuid,
                trajectory_title=info.title,
                well_name=info.title,
                point_index=index,
                x=float(values[0]),
                y=float(values[1]),
                z=float(values[2]),
                tvd=-float(values[2]),
                md=float(distances[index]),
                distance_along=float(distances[index]),
                horizontal_distance=float(horizontal_distances[index]),
            )
            for index, values in enumerate(xyz)
        ]

    def get_grid_shape(self) -> tuple[int | None, int | None, int | None]:
        self._require_selected_grid()
        grid = self._grids[0]
        return grid.ni, grid.nj, grid.nk

    def get_property_value(self, property_uuid: str, i: int, j: int, k: int):
        return self._read_property_value(property_uuid, i, j, k)

    def get_property_column_values(self, property_uuid: str, i: int, j: int):
        self._require_selected_grid()
        ni, nj, nk = self._require_shape()
        if not (0 <= i < ni and 0 <= j < nj):
            raise IndexError(f"Column index out of bounds: i={i}, j={j}; shape NI/NJ={ni}/{nj}")
        return self.get_property_columns_values(property_uuid, {(i, j)})[(i, j)]

    def get_property_columns_values(
        self,
        property_uuid: str,
        columns: set[tuple[int, int]],
    ) -> dict[tuple[int, int], np.ndarray]:
        self._require_selected_grid()
        ni, nj, nk = self._require_shape()
        for i, j in columns:
            if not (0 <= i < ni and 0 <= j < nj):
                raise IndexError(f"Column index out of bounds: i={i}, j={j}; shape NI/NJ={ni}/{nj}")
        cube = self._decoded_property_values(property_uuid).reshape(nk, nj, ni)
        scale = _output_value_scale(self._property_info(property_uuid))
        return {
            (i, j): np.asarray(cube[::-1, j, i], dtype=float) * scale
            for i, j in columns
        }

    def get_property_decode_stats(self, property_uuid: str) -> dict[str, float | int | str | None]:
        prop_file = self._property_files.get(property_uuid)
        if prop_file is None:
            raise ValueError(f"Property UUID not found: {property_uuid}")
        prop = self._property_info(property_uuid)
        values = self._decoded_property_values(property_uuid)
        valid = values[np.isfinite(values)]
        valid_range = _valid_value_range(prop)
        stats: dict[str, float | int | str | None] = {
            "path": str(prop_file.path),
            "file_id": prop_file.file_id,
            "logical_count": int(values.size),
            "stored_count": int(prop_file.value_count),
            "valid_count": int(valid.size),
            "blank_count": int(values.size - valid.size),
            "first_run_length": int(prop_file.first_run_length),
            "undefined_value": float(prop_file.undefined_value) if prop_file.undefined_value is not None else None,
            "invalid_abs_limit": float(_invalid_abs_value_limit(prop)),
            "valid_min": float(valid_range[0]) if valid_range is not None else None,
            "valid_max": float(valid_range[1]) if valid_range is not None else None,
            "min": None,
            "max": None,
            "mean": None,
        }
        if valid.size:
            stats["min"] = float(valid.min())
            stats["max"] = float(valid.max())
            stats["mean"] = float(valid.mean())
        return stats

    def get_cell_active_column(self, i: int, j: int):
        return None

    def get_cell_geometry_column(self, i: int, j: int) -> dict[str, list[float]]:
        ni, nj, nk = self._require_shape()
        if not (0 <= i < ni and 0 <= j < nj):
            raise IndexError(f"Column index out of bounds: i={i}, j={j}; shape NI/NJ={ni}/{nj}")
        size_i, size_j = self._cell_xy_size()
        pillar_values = self._decoded_cell_geometry_pillars(i, j)
        if any(values is None for values in pillar_values):
            tvd_top = [math.nan] * nk
            tvd_base = [math.nan] * nk
            cell_height = [math.nan] * nk
            points = None
        else:
            pillar_stack = np.stack(pillar_values)
            interfaces = np.nanmean(pillar_stack, axis=0)
            tvd_top, tvd_base, cell_height = _geometry_from_z_interfaces(interfaces)
            points = self._cell_corner_points(i, j, pillar_stack) if self._xy_bounds is not None else None
        result = {
            "TVD_top": tvd_top,
            "TVD_base": tvd_base,
            "CellHeight": cell_height,
            "CellSizeI": [size_i] * nk,
            "CellSizeJ": [size_j] * nk,
            "CellAreaXY": [size_i * size_j] * nk,
        }
        if points is not None:
            result["points"] = points
        return result

    def get_column_centers_xy(self) -> np.ndarray:
        ni, nj, _nk = self._require_shape()
        if self._xy_bounds is None:
            raise ValueError("Rescue CRS metadata was not found; cannot build XY grid.")
        if self._horizon_files:
            points = self._horizon_cell_points()
            counts = np.count_nonzero(np.isfinite(points), axis=2)
            centers = np.full((nj, ni, 2), np.nan, dtype=float)
            np.divide(np.nansum(points, axis=2), counts, out=centers, where=counts > 0)
            offset_x, offset_y = self._local_xy_offsets()
            centers[:, :, 0] += offset_x
            centers[:, :, 1] += offset_y
            return centers
        xmin, xmax, ymin, ymax = self._xy_bounds
        x_nodes = np.linspace(xmin, xmax, ni + 1, dtype=float)
        y_nodes = np.linspace(ymin, ymax, nj + 1, dtype=float)
        xs = (x_nodes[:-1] + x_nodes[1:]) / 2.0
        ys = (y_nodes[:-1] + y_nodes[1:]) / 2.0
        xx, yy = np.meshgrid(xs, ys)
        return np.stack((xx, yy), axis=2)

    def _read_property_value(self, property_uuid: str, i: int, j: int, k: int):
        ni, nj, nk = self._require_shape()
        if not (0 <= i < ni and 0 <= j < nj and 0 <= k < nk):
            raise IndexError(f"Cell index out of bounds: i={i}, j={j}, k={k}; shape NI/NJ/NK={ni}/{nj}/{nk}")
        prop_file = self._property_files.get(property_uuid)
        if prop_file is None:
            raise ValueError(f"Property UUID not found: {property_uuid}")

        flat_index = (nk - 1 - k) * nj * ni + j * ni + i
        values = self._decoded_property_values(property_uuid)
        if flat_index >= values.size:
            return ""
        value = float(values[flat_index])
        if not math.isfinite(value):
            return ""
        return value * _output_value_scale(self._property_info(property_uuid))

    def _resolve_main_path(self, path: Path) -> Path:
        if path.is_file():
            if not is_rescue_path(path):
                raise ValueError(f"Not a Rescue model file: {path}")
            return path
        main = _find_rescue_model_file(path)
        if main is None:
            raise FileNotFoundError(f"Rescue model file was not found in: {path}")
        return main

    def _find_geometry_file(self) -> Path:
        assert self.root_path is not None
        for path in self.root_path.glob("*.bin.*"):
            try:
                if RESCUE_GEOMETRY_LABEL in _read_file_head(path):
                    return path
            except OSError:
                continue
        raise FileNotFoundError(f"Rescue geometry file was not found in: {self.root_path}")

    def _discover_property_files(self) -> dict[int, _PropertyFile]:
        assert self.root_path is not None
        files: dict[int, _PropertyFile] = {}
        for path in self.root_path.glob("*.bin.*"):
            try:
                head = _read_file_head(path)
            except OSError:
                continue
            if RESCUE_PROPERTY_LABEL not in head:
                continue
            try:
                file_id = int(path.name.rsplit(".", 1)[1])
            except ValueError:
                continue
            files[file_id] = _read_property_file_info(file_id, path)
        return files

    def _discover_horizon_files(self) -> dict[str, _HorizonFile]:
        assert self.root_path is not None
        assert self.main_path is not None
        titles = _horizon_titles_from_model(self.main_path.read_bytes())
        expected_count = 4 * (self._grids[0].ni or 0) * (self._grids[0].nj or 0)
        triplets: list[tuple[int, Path]] = []
        for path in self.root_path.glob("*.bin.*"):
            try:
                head = _read_file_head(path, 32)
                file_id = int(path.name.rsplit(".", 1)[1])
            except (OSError, ValueError):
                continue
            if RESCUE_TRIPLET_LABEL not in head or len(head) < 28:
                continue
            if int.from_bytes(head[24:28], "big", signed=False) == expected_count:
                triplets.append((file_id, path))
        triplets.sort()
        if len(titles) != len(triplets):
            return {}
        return {
            f"rescue-horizon:{file_id}": _HorizonFile(file_id=file_id, path=path, title=title)
            for title, (file_id, path) in zip(titles, triplets)
        }

    def _discover_trajectory_files(self) -> dict[str, _TrajectoryFile]:
        assert self.root_path is not None
        assert self.main_path is not None
        triplets: dict[int, Path] = {}
        for path in self.root_path.iterdir():
            try:
                file_id = int(path.name.rsplit(".", 1)[1])
                head = _read_file_head(path, 28)
            except (IndexError, OSError, ValueError):
                continue
            if RESCUE_TRIPLET_LABEL in head:
                triplets[file_id] = path
        horizon_ids = {info.file_id for info in self._horizon_files.values()}
        records = _trajectory_records_from_model(
            self.main_path.read_bytes(),
            set(triplets) - horizon_ids,
        )
        return {
            f"rescue-trajectory:{file_id}": _TrajectoryFile(file_id=file_id, path=triplets[file_id], title=title)
            for file_id, title in records
        }

    def _horizon_sample_points(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._horizon_xy is not None:
            return self._horizon_xy
        first = next(iter(self._horizon_files.values()), None)
        if first is None:
            empty = np.asarray([], dtype=float)
            self._horizon_xy = empty, empty, np.asarray([], dtype=np.int64)
            return self._horizon_xy
        x_values, y_values, _z_values = _decode_triplet_file(first.path)
        valid = (
            np.isfinite(x_values)
            & np.isfinite(y_values)
            & (np.abs(x_values) < 1e20)
            & (np.abs(y_values) < 1e20)
        )
        indices = np.flatnonzero(valid)
        self._horizon_xy = x_values[indices].astype(float), y_values[indices].astype(float), indices
        return self._horizon_xy

    def _horizon_cell_points(self) -> np.ndarray:
        if self._horizon_cell_xy is not None:
            return self._horizon_cell_xy
        first = next(iter(self._horizon_files.values()), None)
        ni, nj, _nk = self._require_shape()
        if first is None:
            self._horizon_cell_xy = np.full((nj, ni, 4, 2), np.nan, dtype=float)
            return self._horizon_cell_xy
        x_values, y_values, _z_values = _decode_triplet_file(first.path)
        expected = ni * nj * 4
        if x_values.size != expected or y_values.size != expected:
            raise ValueError(
                f"Unsupported Rescue surface topology: {x_values.size} values; expected {expected}"
            )
        points = _reshape_triplet_cell_points(x_values, y_values, ni, nj)
        points[(~np.isfinite(points)) | (np.abs(points) > 1e20)] = np.nan
        self._horizon_cell_xy = points
        return points

    def _geometry_block_index(self) -> dict[tuple[float, float], int]:
        if self._geometry_blocks_by_xy is not None:
            return self._geometry_blocks_by_xy
        geometry_file = self._geometry_file
        if geometry_file is None:
            self._geometry_blocks_by_xy = {}
            return self._geometry_blocks_by_xy
        result = _triplet_geometry_block_index(
            self._horizon_cell_points(),
            len(geometry_file.block_starts),
        )
        self._geometry_blocks_by_xy = result
        return result

    def _horizon_z_values(self, horizon_uuid: str) -> np.ndarray:
        cached = self._decoded_horizon_z.get(horizon_uuid)
        if cached is not None:
            self._decoded_horizon_z.move_to_end(horizon_uuid)
            return cached
        _x, _y, values = _decode_triplet_file(self._horizon_files[horizon_uuid].path, z_only=True)
        self._decoded_horizon_z[horizon_uuid] = values
        while len(self._decoded_horizon_z) > self._decoded_horizon_cache_limit:
            self._decoded_horizon_z.popitem(last=False)
        return values

    def _local_xy_offsets(self) -> tuple[float, float]:
        if self._xy_bounds is None or not self._horizon_files:
            return 0.0, 0.0
        local_x, local_y, _indices = self._horizon_sample_points()
        if local_x.size == 0:
            return 0.0, 0.0
        xmin, _xmax, ymin, _ymax = self._xy_bounds
        return xmin - float(np.nanmin(local_x)), ymin - float(np.nanmin(local_y))

    def _parse_properties(self, property_files: dict[int, _PropertyFile]) -> list[PropertyInfo]:
        assert self.main_path is not None
        main_bytes = self.main_path.read_bytes()
        parsed: list[PropertyInfo] = []
        for file_id, prop_file in sorted(property_files.items()):
            title, kind, uom = _property_metadata_from_model(main_bytes, file_id)
            uuid = f"rescue-property:{file_id}"
            self._property_files[uuid] = prop_file
            parsed.append(
                PropertyInfo(
                    index=len(parsed),
                    title=title or f"property_{file_id}",
                    uuid=uuid,
                    indexable_element="cells",
                    uom=uom,
                    property_kind=kind,
                    property_type="RescueProperty",
                    supporting_grid_uuid=self._grids[0].uuid if self._grids else None,
                    hdf_paths=(str(prop_file.path),),
                    shape=(prop_file.value_count,),
                    dtype=">f4",
                )
            )
        return parsed

    def _require_selected_grid(self) -> None:
        if self._selected_grid_uuid is None:
            raise ValueError("No grid selected")

    def _require_shape(self) -> tuple[int, int, int]:
        self._require_selected_grid()
        ni, nj, nk = self.get_grid_shape()
        if ni is None or nj is None or nk is None:
            raise ValueError("Selected grid has incomplete NI/NJ/NK metadata.")
        return int(ni), int(nj), int(nk)

    def _cell_xy_size(self) -> tuple[float, float]:
        ni, nj, _nk = self._require_shape()
        if self._xy_bounds is None:
            return math.nan, math.nan
        xmin, xmax, ymin, ymax = self._xy_bounds
        size_i = abs(xmax - xmin) / max(ni, 1)
        size_j = abs(ymax - ymin) / max(nj, 1)
        return float(size_i), float(size_j)

    def _cell_corner_points(self, i: int, j: int, pillar_z: np.ndarray) -> np.ndarray:
        ni, nj, _nk = self._require_shape()
        assert self._xy_bounds is not None
        if self._horizon_files:
            xy = self._horizon_cell_points()[j, i].copy()
            offset_x, offset_y = self._local_xy_offsets()
            xy[:, 0] += offset_x
            xy[:, 1] += offset_y
        else:
            xmin, xmax, ymin, ymax = self._xy_bounds
            x_nodes = np.linspace(xmin, xmax, ni + 1, dtype=float)
            y_nodes = np.linspace(ymin, ymax, nj + 1, dtype=float)
            xy = np.asarray(
                [
                    [x_nodes[i], y_nodes[j]],
                    [x_nodes[i + 1], y_nodes[j]],
                    [x_nodes[i], y_nodes[j + 1]],
                    [x_nodes[i + 1], y_nodes[j + 1]],
                ],
                dtype=float,
            )
        points = np.empty((pillar_z.shape[1], 4, 3), dtype=float)
        points[:, :, :2] = xy[None, :, :]
        points[:, :, 2] = pillar_z[:, ::-1].T
        return points

    def _decoded_property_values(self, property_uuid: str) -> np.ndarray:
        cached = self._decoded_properties.get(property_uuid)
        if cached is not None:
            self._decoded_properties.move_to_end(property_uuid)
            return cached
        prop_file = self._property_files.get(property_uuid)
        if prop_file is None:
            raise ValueError(f"Property UUID not found: {property_uuid}")
        prop = self._property_info(property_uuid)
        ni, nj, nk = self._require_shape()
        values = _decode_compact_property_file(
            prop_file,
            ni * nj * nk,
            _invalid_abs_value_limit(prop),
            _valid_value_range(prop),
        )
        self._decoded_properties[property_uuid] = values
        while len(self._decoded_properties) > self._decoded_property_cache_limit:
            self._decoded_properties.popitem(last=False)
        return values

    def _decoded_geometry_column(self, i: int, j: int) -> np.ndarray | None:
        geometry_file = self._geometry_file
        if geometry_file is None:
            return None
        raw_ni, raw_nj, raw_nk = geometry_file.raw_ni, geometry_file.raw_nj, geometry_file.raw_nk
        if not (0 <= i < raw_ni and 0 <= j < raw_nj):
            return None
        column_index = i * raw_nj + j
        cached = self._decoded_geometry_columns.get(column_index)
        if cached is not None:
            self._decoded_geometry_columns.move_to_end(column_index)
            return cached
        if column_index >= len(geometry_file.block_starts):
            return None
        start = geometry_file.block_starts[column_index]
        next_start = (
            geometry_file.block_starts[column_index + 1]
            if column_index + 1 < len(geometry_file.block_starts)
            else geometry_file.path.stat().st_size
        )
        values = _decode_geometry_column_block(geometry_file.path, start, next_start, raw_nk)
        if values is None:
            return None
        self._decoded_geometry_columns[column_index] = values
        while len(self._decoded_geometry_columns) > self._decoded_geometry_cache_limit:
            self._decoded_geometry_columns.popitem(last=False)
        return values

    def _decoded_cell_geometry_pillars(self, i: int, j: int) -> list[np.ndarray | None]:
        geometry_file = self._geometry_file
        if geometry_file is None:
            return [None] * 4
        if len(geometry_file.block_starts) == geometry_file.raw_ni * geometry_file.raw_nj:
            return [
                self._decoded_geometry_column(i, j),
                self._decoded_geometry_column(i + 1, j),
                self._decoded_geometry_column(i, j + 1),
                self._decoded_geometry_column(i + 1, j + 1),
            ]
        points = self._horizon_cell_points()[j, i]
        block_map = self._geometry_block_index()
        result: list[np.ndarray | None] = []
        for point in points:
            if not np.isfinite(point).all():
                result.append(None)
                continue
            block_index = block_map.get((float(point[0]), float(point[1])))
            result.append(self._decoded_geometry_block(block_index) if block_index is not None else None)
        return result

    def _decoded_geometry_block(self, block_index: int) -> np.ndarray | None:
        geometry_file = self._geometry_file
        if geometry_file is None or not (0 <= block_index < len(geometry_file.block_starts)):
            return None
        cached = self._decoded_geometry_columns.get(block_index)
        if cached is not None:
            self._decoded_geometry_columns.move_to_end(block_index)
            return cached
        start = geometry_file.block_starts[block_index]
        end = (
            geometry_file.block_starts[block_index + 1]
            if block_index + 1 < len(geometry_file.block_starts)
            else geometry_file.path.stat().st_size
        )
        values = _decode_geometry_column_block(geometry_file.path, start, end, geometry_file.raw_nk)
        if values is None:
            return None
        self._decoded_geometry_columns[block_index] = values
        while len(self._decoded_geometry_columns) > self._decoded_geometry_cache_limit:
            self._decoded_geometry_columns.popitem(last=False)
        return values

    def _property_info(self, property_uuid: str) -> PropertyInfo:
        for prop in self._properties:
            if prop.uuid == property_uuid:
                return prop
        raise ValueError(f"Property UUID not found: {property_uuid}")


def _find_rescue_model_file(path: Path) -> Path | None:
    for candidate in sorted(path.glob("*.bin")):
        try:
            if _read_file_head(candidate, len(RESCUE_MODEL_HEADER)).startswith(RESCUE_MODEL_HEADER):
                return candidate
        except OSError:
            continue
    return None


def _read_file_head(path: Path, size: int = 64) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def _read_rescue_geometry_shape(path: Path) -> tuple[int, int, int]:
    with path.open("rb") as handle:
        data = handle.read(64)
    # Rescue flat files use a one-byte file kind, a zero-terminated label, a
    # three-byte version field, then big-endian int32 dimensions.
    return (
        int.from_bytes(data[29:33], "big", signed=True),
        int.from_bytes(data[33:37], "big", signed=True),
        int.from_bytes(data[37:41], "big", signed=True),
    )


def _read_rescue_geometry_file_info(path: Path, ni: int, nj: int, nk: int) -> _GeometryFile | None:
    data = path.read_bytes()
    pattern = nk.to_bytes(4, "big", signed=True) + (1).to_bytes(4, "big", signed=True)
    starts: list[int] = []
    position = 0
    while True:
        index = data.find(pattern, position)
        if index < 0:
            break
        command_pos = index + len(pattern)
        if command_pos < len(data) and _read_compact_run_length(data, command_pos, len(data)) is not None:
            starts.append(index)
        position = index + 1
    if not starts:
        return None
    return _GeometryFile(path=path, block_starts=tuple(starts), raw_ni=ni, raw_nj=nj, raw_nk=nk)


def _read_property_file_info(file_id: int, path: Path) -> _PropertyFile:
    with path.open("rb") as handle:
        head = handle.read(64)
    if len(head) < 30 or RESCUE_PROPERTY_LABEL not in head[:24]:
        raise ValueError(f"Invalid Rescue property file: {path}")
    value_count = int.from_bytes(head[PROPERTY_ARRAY_OFFSET : PROPERTY_ARRAY_OFFSET + 4], "big", signed=False)
    first_code = head[PROPERTY_ARRAY_OFFSET + 4]
    if first_code == 0xFD:
        first_run_length = head[PROPERTY_ARRAY_OFFSET + 5]
    elif first_code in (0xFE, 0xFF):
        first_run_length = int.from_bytes(
            head[PROPERTY_ARRAY_OFFSET + 5 : PROPERTY_ARRAY_OFFSET + 9], "big", signed=False
        )
    else:
        first_run_length = first_code
    return _PropertyFile(
        file_id=file_id,
        path=path,
        values_offset=PROPERTY_ARRAY_OFFSET,
        value_count=value_count,
        undefined_value=None,
        first_run_length=first_run_length,
    )


def _decode_compact_property_file(
    prop_file: _PropertyFile,
    logical_count: int,
    invalid_abs_value_limit: np.float32 = DEFAULT_INVALID_ABS_VALUE_LIMIT,
    valid_range: tuple[np.float32, np.float32] | None = None,
) -> np.ndarray:
    data = prop_file.path.read_bytes()
    values, _position = _decode_triplet_array(data, prop_file.values_offset, keep=True)
    if values.size != logical_count:
        raise ValueError(
            f"Rescue property logical size mismatch: decoded {values.size}, expected {logical_count}"
        )

    if prop_file.undefined_value is not None and math.isfinite(prop_file.undefined_value):
        values[values == np.float32(prop_file.undefined_value)] = np.nan
    values[~np.isfinite(values)] = np.nan
    values[np.abs(values) > invalid_abs_value_limit] = np.nan
    if valid_range is not None:
        min_value, max_value = valid_range
        values[(values < min_value) | (values > max_value)] = np.nan
    return values


def _decode_geometry_column_block(path: Path, start: int, end: int, nk: int) -> np.ndarray | None:
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read(end - start)
    if len(data) < 9 or int.from_bytes(data[:4], "big", signed=True) != nk:
        return None

    values: list[float] = []
    pos = 8
    decoded = _read_plausible_geometry_run(data, pos)
    if decoded is None:
        return None
    run_length, pos = decoded
    while pos < len(data) and len(values) < nk:
        take = min(run_length, nk - len(values), max(0, (len(data) - pos) // 4))
        for _ in range(take):
            value = struct.unpack_from(">f", data, pos)[0]
            values.append(value)
            pos += 4
        if len(values) >= nk:
            break
        while len(values) < nk:
            if not _geometry_token_looks_like_fill(data, pos):
                return None
            fill_count = data[pos]
            fill_value = struct.unpack_from(">f", data, pos + 1)[0]
            values.extend([fill_value] * min(fill_count, nk - len(values)))
            pos += 5
            if len(values) >= nk:
                break

            # Rescue geometry can encode a chain of short fill commands such as
            # "02 + float, 02 + float..." where the leading byte is ambiguous
            # with a short run length. Prefer the fill interpretation when two
            # plausible fill tokens are adjacent; otherwise resume raw floats.
            if _geometry_token_looks_like_fill_chain(data, pos):
                continue
            decoded = _read_plausible_geometry_run(data, pos)
            if decoded is not None:
                run_length, pos = decoded
                break

    if len(values) != nk:
        return None
    array = np.asarray(values, dtype=np.float32)
    array[~np.isfinite(array)] = np.nan
    array[np.abs(array) > np.float32(1e20)] = np.nan
    if np.count_nonzero(np.isfinite(array)) != nk:
        return None
    return array


def _read_plausible_geometry_run(data: bytes, pos: int) -> tuple[int, int] | None:
    decoded = _read_compact_run_length(data, pos, len(data))
    if decoded is None:
        return None
    run_length, next_pos = decoded
    if not _geometry_run_looks_plausible(data, next_pos, run_length):
        return None
    return run_length, next_pos


def _geometry_run_looks_plausible(data: bytes, pos: int, run_length: int) -> bool:
    if run_length <= 0 or pos + run_length * 4 > len(data):
        return False
    for index in range(run_length):
        value = struct.unpack_from(">f", data, pos + index * 4)[0]
        if not _is_plausible_geometry_z(value):
            return False
    return True


def _geometry_token_looks_like_fill_chain(data: bytes, pos: int) -> bool:
    return _geometry_token_looks_like_fill(data, pos) and _geometry_token_looks_like_fill(data, pos + 5)


def _geometry_token_looks_like_fill(data: bytes, pos: int) -> bool:
    if pos + 5 > len(data):
        return False
    if data[pos] > 64:
        return False
    value = struct.unpack_from(">f", data, pos + 1)[0]
    return _is_plausible_geometry_z(value)


def _is_plausible_geometry_z(value: float) -> bool:
    return math.isfinite(value) and -10000.0 <= value <= 1000.0


def _geometry_from_z_centers(z_values: np.ndarray) -> tuple[list[float], list[float], list[float]]:
    z = np.asarray(z_values, dtype=float)
    if z.size == 0:
        return [], [], []
    if z.size == 1:
        value = float(z[0])
        return [value], [value], [0.0]

    boundaries = np.empty(z.size + 1, dtype=float)
    boundaries[1:-1] = (z[:-1] + z[1:]) / 2.0
    boundaries[0] = z[0] - (z[1] - z[0]) / 2.0
    boundaries[-1] = z[-1] + (z[-1] - z[-2]) / 2.0

    if z[-1] >= z[0]:
        top = boundaries[1:]
        base = boundaries[:-1]
    else:
        top = boundaries[:-1]
        base = boundaries[1:]
    height = np.abs(top - base)
    top = np.abs(top)
    base = np.abs(base)
    return top.tolist(), base.tolist(), height.tolist()


def _geometry_from_z_interfaces(z_values: np.ndarray) -> tuple[list[float], list[float], list[float]]:
    z = np.asarray(z_values, dtype=float)[::-1]
    if z.size < 2:
        return [], [], []
    depth = np.abs(z)
    first = depth[:-1]
    second = depth[1:]
    top = np.minimum(first, second)
    base = np.maximum(first, second)
    height = np.abs(second - first)
    return top.tolist(), base.tolist(), height.tolist()


def _invalid_abs_value_limit(prop: PropertyInfo) -> np.float32:
    title = prop.title.lower()
    kind = (prop.property_kind or "").lower()
    text = f"{title} {kind}"
    if title == "fbid" or "segmentid" in text or "segment id" in text:
        return DEFAULT_INVALID_ABS_VALUE_LIMIT
    if "density" in text or "dens" in title:
        return np.float32(20.0)
    if "poisson" in text or title.startswith("pr_"):
        return np.float32(10.0)
    if "friction angle" in text or title == "fang":
        return np.float32(360.0)
    if "strain" in text or "eigenvector" in title:
        return np.float32(10.0)
    if "shmin" in text or "shmax" in text:
        return np.float32(100000.0)
    return np.float32(1e6)


def _valid_value_range(prop: PropertyInfo) -> tuple[np.float32, np.float32] | None:
    title = prop.title.lower()
    kind = (prop.property_kind or "").lower()
    text = f"{title} {kind}"
    if "density" in text or "dens" in title:
        return np.float32(1.0), np.float32(5.0)
    if "poisson" in text or title.startswith("pr_"):
        return np.float32(0.01), np.float32(0.5)
    if "friction angle" in text or title == "fang":
        return np.float32(0.0), np.float32(90.0)
    if "shmin" in text or "shmax" in text:
        return np.float32(0.0), np.float32(100000.0)
    return None


def _output_value_scale(prop: PropertyInfo) -> float:
    return 1.0


def _read_compact_command(
    data: bytes,
    pos: int,
    end: int,
    remaining_logical: int,
) -> tuple[int, int, int, int] | None:
    candidates: list[tuple[int, int, int, int, int]] = []
    for start in range(pos, min(pos + 7, end)):
        if start + 6 > end:
            continue
        skip_count = data[start]
        decoded = _read_compact_run_length(data, start + 5, end)
        if decoded is None:
            continue
        next_run_length, next_pos = decoded
        if skip_count > remaining_logical or next_run_length > remaining_logical - skip_count:
            continue
        filler = data[start + 1 : start + 5]
        code = data[start + 5]
        score = 0
        if start == pos:
            score += 100
        if filler == b"\x7f\x7f\xff\xff":
            score += 50
        else:
            score -= 80
        if code in (0xFD, 0xFE):
            score += 20
        if next_run_length > 0:
            score += 5
        candidates.append((score, start, skip_count, next_run_length, next_pos))
    if not candidates:
        return None
    _score, start, skip_count, next_run_length, next_pos = max(candidates)
    return start, skip_count, next_run_length, next_pos


def _read_compact_run_length(data: bytes, pos: int, end: int) -> tuple[int, int] | None:
    if pos >= end:
        return None
    code = data[pos]
    if code == 0xFD:
        if pos + 2 > end:
            return None
        return data[pos + 1], pos + 2
    if code == 0xFE:
        if pos + 5 > end:
            return None
        return int.from_bytes(data[pos + 1 : pos + 5], "big", signed=False), pos + 5
    if code < 0xFD:
        return code, pos + 1
    return None


def _find_trailer_offset(path: Path) -> int | None:
    tail_size = min(path.stat().st_size, 256)
    with path.open("rb") as handle:
        handle.seek(path.stat().st_size - tail_size)
        tail = handle.read(tail_size)
    index = tail.rfind(RESCUE_TRAILER)
    if index < 0:
        return None
    return path.stat().st_size - tail_size + index


def _read_xy_bounds_from_crsmeta(root_path: Path | None) -> tuple[float, float, float, float] | None:
    if root_path is None:
        return None
    for path in root_path.glob("*.crsmeta.xml"):
        try:
            tree = ET.parse(path)
        except (OSError, ET.ParseError):
            continue
        points: list[tuple[float, float]] = []
        for element in tree.iter():
            if element.tag.rsplit("}", 1)[-1] != "Point":
                continue
            if element.attrib.get("coordinateReferenceSystemId") not in {None, "GK42-13N"}:
                continue
            location = element.attrib.get("location")
            if not location:
                continue
            values = location.split()
            if len(values) >= 2:
                try:
                    points.append((float(values[0]), float(values[1])))
                except ValueError:
                    pass
        if points:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            return min(xs), max(xs), min(ys), max(ys)
    return None


def _horizon_titles_from_model(main_bytes: bytes) -> list[str]:
    intervals: list[tuple[str, str]] = []
    for text, _start, _end in _ascii_string_spans(main_bytes[:2048]):
        if " - " not in text:
            continue
        top, base = (value.strip() for value in text.split(" - ", 1))
        if not top or not base:
            continue
        if intervals and intervals[-1][1] != top:
            continue
        intervals.append((top, base))
    if not intervals:
        return []
    return [intervals[0][0], *(base for _top, base in intervals)]


def _trajectory_records_from_model(main_bytes: bytes, triplet_ids: set[int]) -> list[tuple[int, str]]:
    marker = b"\x00\x04EOD\x00"
    records: list[tuple[int, str]] = []
    position = 0
    seen: set[int] = set()
    while True:
        marker_offset = main_bytes.find(marker, position)
        if marker_offset < 0:
            break
        position = marker_offset + 1
        if marker_offset < 4 or marker_offset + len(marker) + 2 > len(main_bytes):
            continue
        file_id = int.from_bytes(main_bytes[marker_offset - 4 : marker_offset], "big", signed=False)
        if file_id not in triplet_ids or file_id in seen:
            continue
        length_offset = marker_offset + len(marker)
        title_length = int.from_bytes(main_bytes[length_offset : length_offset + 2], "big", signed=False)
        if not (1 <= title_length <= 256):
            continue
        title_bytes = main_bytes[length_offset + 2 : length_offset + 2 + title_length].rstrip(b"\x00")
        try:
            title = title_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            title = title_bytes.decode("cp1251", errors="replace").strip()
        if not title or title == "EOD":
            continue
        records.append((file_id, title))
        seen.add(file_id)
    return records


def _triplet_point_count(path: Path) -> int:
    head = _read_file_head(path, 28)
    return int.from_bytes(head[24:28], "big", signed=False) if len(head) >= 28 else 0


def _cumulative_distances(values: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return np.asarray([], dtype=float)
    if len(values) == 1:
        return np.asarray([0.0], dtype=float)
    segments = np.linalg.norm(np.diff(values, axis=0), axis=1)
    return np.concatenate((np.asarray([0.0]), np.cumsum(segments)))


def _decode_triplet_file(path: Path, *, z_only: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = path.read_bytes()
    if RESCUE_TRIPLET_LABEL not in data[:24]:
        raise ValueError(f"Not a Rescue triplet file: {path}")
    position = 24
    x_values, position = _decode_triplet_array(data, position, keep=not z_only)
    y_values, position = _decode_triplet_array(data, position, keep=not z_only)
    z_values, _position = _decode_triplet_array(data, position, keep=True)
    return x_values, y_values, z_values


def _reshape_triplet_cell_points(
    x_values: np.ndarray,
    y_values: np.ndarray,
    ni: int,
    nj: int,
) -> np.ndarray:
    expected = ni * nj * 4
    if x_values.size != expected or y_values.size != expected:
        raise ValueError(f"Unsupported Rescue surface topology: {x_values.size} values; expected {expected}")

    # Rescue serializes the four corners as a (2 * NJ) by (2 * NI)
    # matrix: two complete corner rows per logical J row and two values
    # per logical I cell. Convert it to [J, I, corner, XY].
    stored = np.stack((x_values, y_values), axis=1).astype(float)
    return stored.reshape(nj, 2, ni, 2, 2).transpose(0, 2, 1, 3, 4).reshape(nj, ni, 4, 2)


def _triplet_geometry_block_index(
    cell_points: np.ndarray,
    expected_block_count: int,
) -> dict[tuple[float, float], int]:
    nj, ni = cell_points.shape[:2]
    nodes = np.full((nj + 1, ni + 1, 2), np.nan, dtype=float)
    for corner, (dj, di) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
        values = cell_points[:, :, corner, :]
        target = nodes[dj : dj + nj, di : di + ni]
        fill = np.isfinite(values).all(axis=2) & ~np.isfinite(target).all(axis=2)
        target[fill] = values[fill]

    valid = np.isfinite(nodes).all(axis=2) & (np.abs(nodes) < 1e20).all(axis=2)
    if int(np.count_nonzero(valid)) != expected_block_count:
        raise ValueError(
            "Rescue sparse geometry does not match surface topology: "
            f"{expected_block_count} geometry blocks, {int(np.count_nonzero(valid))} surface vertices."
        )

    # Geometry blocks are serialized with J varying fastest (I-major).
    result: dict[tuple[float, float], int] = {}
    block_index = 0
    for i in range(ni + 1):
        for j in range(nj + 1):
            if not valid[j, i]:
                continue
            point = nodes[j, i]
            result[(float(point[0]), float(point[1]))] = block_index
            block_index += 1
    return result


def _decode_triplet_array(data: bytes, position: int, *, keep: bool) -> tuple[np.ndarray, int]:
    if position + 4 > len(data):
        raise ValueError("Truncated Rescue triplet array header.")
    count = int.from_bytes(data[position : position + 4], "big", signed=False)
    position += 4
    values = np.empty(count, dtype=np.float32) if keep else np.asarray([], dtype=np.float32)
    logical = 0
    while logical < count:
        if position >= len(data):
            raise ValueError("Truncated Rescue triplet array.")
        code = data[position]
        position += 1
        if code in (0xFD, 0xFE):
            if code == 0xFD:
                run_length = data[position]
                position += 1
            else:
                run_length = int.from_bytes(data[position : position + 4], "big", signed=False)
                position += 4
            if logical + run_length > count or position + run_length * 4 > len(data):
                raise ValueError("Invalid raw run in Rescue triplet array.")
            if keep:
                values[logical : logical + run_length] = np.frombuffer(
                    data, dtype=">f4", count=run_length, offset=position
                )
            position += run_length * 4
        else:
            if code == 0xFF:
                run_length = int.from_bytes(data[position : position + 4], "big", signed=False)
                position += 4
            else:
                run_length = code
            if logical + run_length > count or position + 4 > len(data):
                raise ValueError("Invalid fill run in Rescue triplet array.")
            value = struct.unpack_from(">f", data, position)[0]
            position += 4
            if keep:
                values[logical : logical + run_length] = value
        logical += run_length
    return values, position


def _property_metadata_from_model(main_bytes: bytes, file_id: int) -> tuple[str | None, str | None, str | None]:
    positions = [match.start() for match in re.finditer(re.escape(file_id.to_bytes(4, "big")), main_bytes)]
    for position in positions:
        dirty_index = main_bytes.find(b"dirtyMinMax", position, position + 48)
        if dirty_index < 0:
            continue
        start = max(0, dirty_index - 160)
        spans = _ascii_string_spans(main_bytes[start:dirty_index], offset=start)
        segment_start = 0
        for text, span_start, span_end in spans:
            if text == "EOD":
                segment_start = span_end
        segment_strings = [text for text, span_start, _span_end in spans if span_start >= segment_start]
        candidates = [value for value in segment_strings if _is_property_metadata_candidate(value)]
        title, kind = _select_property_metadata(candidates)
        if title:
            uom = next((value for value in segment_strings if "Unit" in value), None)
            return title, kind, uom
    return None, None, None


def _select_property_metadata(candidates: list[str]) -> tuple[str | None, str | None]:
    values = [_clean_property_metadata(value) for value in candidates]
    values = [value for value in values if value and value not in {"General", "SegmentID"}]
    if not values:
        return None, None

    visible_values = [value for value in values if not _is_internal_property_token(value)]
    if not visible_values:
        visible_values = values

    code_like = [value for value in visible_values if _is_property_code_like(value)]
    title = code_like[0] if code_like else visible_values[0]
    kind = next((value for value in visible_values if value != title), None)
    return title, kind


def _clean_property_metadata(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    cleaned = re.sub(r"\s*\($", "", cleaned).strip()
    return cleaned


def _is_internal_property_token(value: str) -> bool:
    return bool(re.fullmatch(r"t.", value))


def _is_property_code_like(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", value))


def _is_property_metadata_candidate(value: str) -> bool:
    if value in {"EOD", "dirtyMinMax", "minMax", "Dummy Unit Of Measure"}:
        return False
    if value in {"Bytes"} or value.startswith("Byte "):
        return False
    if re.fullmatch(r"[A-Za-z]\W?", value):
        return False
    if re.fullmatch(r"[A-Za-z]\}", value):
        return False
    return any(char.isalpha() for char in value)


def _ascii_strings(data: bytes) -> list[str]:
    return [text for text, _start, _end in _ascii_string_spans(data)]


def _ascii_string_spans(data: bytes, offset: int = 0) -> list[tuple[str, int, int]]:
    values: list[tuple[str, int, int]] = []
    for match in re.finditer(rb"[ -~]{2,}", data):
        text = match.group().decode("ascii", errors="ignore").strip("\x00")
        if text:
            values.append((text, offset + match.start(), offset + match.end()))
    return values

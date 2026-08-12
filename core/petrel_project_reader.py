from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3

import numpy as np

from core.petrel_grid_reader import PetrelGridReader, read_petrel_grid_horizontal_shape
from core.petrel_model_metadata import read_petrel_object_names, read_petrel_parent_names
from core.petrel_trajectory_reader import read_petrel_trajectory, read_petrel_trajectory_point_count
from core.resqml_reader import (
    GridInfo,
    PropertyInfo,
    ResqmlReader,
    WellTrajectoryInfo,
    WellTrajectoryPoint,
)
from core.petrel_property_reader import PetrelPropertyReader, read_petrel_property_shape


PETREL_PROJECT_SUFFIX = ".pet"
PETREL_PROJECT_DATA = "Data.ptd"
GEOLOGICAL_PROPERTY_MARKERS = ("PORO", "PERM", "NTG")
MILLIDARCY_TO_SQUARE_METRES = 9.869233e-16


@dataclass(frozen=True)
class PetrelProjectPath:
    project_path: Path
    ptd_path: Path
    data_path: Path


def is_petrel_project_path(path: str | Path) -> bool:
    try:
        resolve_petrel_project_path(path)
        return True
    except (FileNotFoundError, ValueError, OSError):
        return False


def resolve_petrel_project_path(path: str | Path) -> PetrelProjectPath:
    candidate = Path(path)
    if candidate.is_file() and candidate.suffix.lower() == PETREL_PROJECT_SUFFIX:
        ptd_path = candidate.with_suffix(".ptd")
        data_path = ptd_path / PETREL_PROJECT_DATA
        if data_path.is_file():
            return PetrelProjectPath(candidate, ptd_path, data_path)
        raise FileNotFoundError(f"Petrel project data was not found: {data_path}")

    if candidate.is_dir():
        direct_data = candidate / PETREL_PROJECT_DATA
        if candidate.suffix.lower() == ".ptd" and direct_data.is_file():
            project_path = candidate.with_suffix(PETREL_PROJECT_SUFFIX)
            return PetrelProjectPath(project_path, candidate, direct_data)

        pet_files = sorted(candidate.glob("*.pet"))
        for pet_file in pet_files:
            ptd_path = pet_file.with_suffix(".ptd")
            data_path = ptd_path / PETREL_PROJECT_DATA
            if data_path.is_file():
                return PetrelProjectPath(pet_file, ptd_path, data_path)

        ptd_dirs = sorted(child for child in candidate.glob("*.ptd") if child.is_dir())
        for ptd_path in ptd_dirs:
            data_path = ptd_path / PETREL_PROJECT_DATA
            if data_path.is_file():
                project_path = ptd_path.with_suffix(PETREL_PROJECT_SUFFIX)
                return PetrelProjectPath(project_path, ptd_path, data_path)

    raise ValueError(f"Not a Petrel project path: {candidate}")


class PetrelProjectReader:
    """Reader facade for native Petrel projects backed by Data.ptd.

    Native Petrel projects store domain object payloads in a SQLite database
    (`*.ptd/Data.ptd`). This class exposes project contents and the user's
    selected internal grid through the same narrow API used by RESQML and
    Rescue readers. Straight-pillar geometry and supported property values are
    decoded natively; companion RESQML remains a fallback for other layouts.
    """

    def __init__(self, path: str | Path):
        self.input_path = Path(path)
        self.project: PetrelProjectPath | None = None
        self.backend = "petrel-project"
        self._grids: list[GridInfo] = []
        self._properties: list[PropertyInfo] = []
        self._selected_grid_uuid: str | None = None
        self._property_counts: dict[str, int] = {}
        self._property_names: dict[str, tuple[str, ...]] = {}
        self._geological_grid_uuid: str | None = None
        self._model_names: dict[str, str] = {}
        self._companion_epc_path: Path | None = None
        self._companion_readers: dict[str, ResqmlReader] = {}
        self._column_centers_cache: dict[str, object] = {}
        self._native_grid_readers: dict[str, PetrelGridReader] = {}
        self._native_property_readers: dict[str, PetrelPropertyReader] = {}
        self._trajectories: list[WellTrajectoryInfo] | None = None
        self._trajectory_data_pks: dict[str, int] = {}

    @property
    def epc_path(self) -> Path:
        return self.project.project_path if self.project else self.input_path

    @property
    def h5_path(self) -> Path | None:
        return None

    @property
    def data_path(self) -> Path:
        if self.project is None:
            raise RuntimeError("Petrel project is not opened.")
        return self.project.data_path

    def open(self) -> None:
        self.project = resolve_petrel_project_path(self.input_path)
        object_rows = _query_project_objects(
            self.data_path,
            ("PillarGrid2", "FloatProperty", "IntProperty"),
        )
        self._model_names = read_petrel_object_names(
            self.project.ptd_path,
            [row[1] for row in object_rows],
        )
        self._grids = self._load_grids()
        self._properties = self._load_properties()
        self._apply_native_grid_shapes_from_properties()
        self._apply_native_metadata_summary()
        self._enrich_from_companion_resqml()
        if len(self._grids) == 1:
            self._selected_grid_uuid = self._grids[0].uuid

    def list_grids(self) -> list[GridInfo]:
        return list(self._grids)

    def select_grid(self, grid_uuid: str) -> None:
        selected = next((grid.uuid for grid in self._grids if grid.uuid.lower() == grid_uuid.lower()), None)
        if selected is None:
            raise ValueError(f"Petrel project grid UUID not found: {grid_uuid}")
        self._selected_grid_uuid = selected
        companion = self._selected_companion_reader(required=False)
        if companion is not None:
            companion.select_grid(_plain_uuid(grid_uuid))
        native = self._native_grid_reader(required=False)
        if native is not None:
            self._apply_native_grid_shape(native)

    def list_properties(self) -> list[PropertyInfo]:
        if self._selected_grid_uuid is None:
            return list(self._properties)
        selected = _plain_uuid(self._selected_grid_uuid)
        scoped = [
            prop
            for prop in self._properties
            if prop.supporting_grid_uuid and _plain_uuid(prop.supporting_grid_uuid) == selected
        ]
        return scoped or list(self._properties)

    def list_md_datums(self) -> list[object]:
        return []

    def list_well_trajectories(self) -> list[WellTrajectoryInfo]:
        if self._trajectories is None:
            self._load_trajectories()
        return list(self._trajectories or [])

    def get_well_trajectory_points(self, trajectory_uuid: str) -> list[WellTrajectoryPoint]:
        normalized = _plain_uuid(trajectory_uuid)
        info = next(
            (item for item in self.list_well_trajectories() if _plain_uuid(item.uuid) == normalized),
            None,
        )
        if info is None:
            raise ValueError(f"Petrel trajectory UUID not found: {trajectory_uuid}")
        data_pk = self._trajectory_data_pks.get(normalized)
        if data_pk is None:
            raise ValueError(f"Petrel trajectory has no Data.ptd object reference: {info.title}")
        first_md, xyz = read_petrel_trajectory(self.data_path, data_pk)
        distance = _trajectory_distances(xyz)
        horizontal_distance = _trajectory_distances(xyz[:, :2])
        md = first_md + distance
        tvd = _z_to_depth(xyz[:, 2])
        return [
            WellTrajectoryPoint(
                trajectory_uuid=info.uuid,
                trajectory_title=info.title,
                well_name=info.well_name,
                point_index=index,
                x=float(values[0]),
                y=float(values[1]),
                z=float(values[2]),
                tvd=float(tvd[index]),
                md=float(md[index]),
                distance_along=float(distance[index]),
                horizontal_distance=float(horizontal_distance[index]),
            )
            for index, values in enumerate(xyz)
        ]

    def get_grid_shape(self) -> tuple[int | None, int | None, int | None]:
        self._require_selected_grid()
        grid = next(grid for grid in self._grids if grid.uuid == self._selected_grid_uuid)
        return grid.ni, grid.nj, grid.nk

    def get_property_value(self, property_uuid: str, i: int, j: int, k: int):
        native = self._native_property_reader(property_uuid, required=False)
        if native is not None:
            value = native.get_value(i, j, k)
            return _scale_native_property_value(self._property_by_uuid(property_uuid), value)
        reader = self._selected_companion_reader()
        return reader.get_property_value(_plain_uuid(property_uuid), i, j, k)

    def get_property_column_values(self, property_uuid: str, i: int, j: int):
        native = self._native_property_reader(property_uuid, required=False)
        if native is not None:
            values = native.get_column_values(i, j)
            return values * _native_property_scale(self._property_by_uuid(property_uuid))
        reader = self._selected_companion_reader()
        return reader.get_property_column_values(_plain_uuid(property_uuid), i, j)

    def get_property_columns_values(self, property_uuid: str, columns: set[tuple[int, int]]):
        native = self._native_property_reader(property_uuid, required=False)
        if native is not None:
            scale = _native_property_scale(self._property_by_uuid(property_uuid))
            return {column: values * scale for column, values in native.get_columns_values(columns).items()}
        reader = self._selected_companion_reader()
        return {
            column: reader.get_property_column_values(_plain_uuid(property_uuid), *column)
            for column in columns
        }

    def get_column_centers_xy(self):
        if self._selected_grid_uuid is None:
            raise ValueError("Select an internal Petrel model before reading project data.")
        cached = self._column_centers_cache.get(self._selected_grid_uuid)
        if cached is not None:
            return cached
        native = self._native_grid_reader(required=False)
        if native is not None:
            centers = native.get_column_centers_xy()
            self._column_centers_cache[self._selected_grid_uuid] = centers
            return centers
        from core.grid_indexer import FastGridIndexer

        reader = self._selected_companion_reader()
        companion_grid = next(
            grid for grid in reader.list_grids() if grid.uuid == _plain_uuid(self._selected_grid_uuid)
        )
        indexer = FastGridIndexer(reader, companion_grid)
        indexer.build_column_index()
        self._column_centers_cache[self._selected_grid_uuid] = indexer.column_centers
        return indexer.column_centers

    def get_cell_depths(self, i: int, j: int, k: int):
        geometry = self.get_cell_geometry_column(i, j)
        points = geometry.get("points")
        if points is None:
            raise ValueError("Companion RESQML grid has no readable cell geometry.")
        return points[k : k + 2]

    def get_cell_geometry_column(self, i: int, j: int):
        native = self._native_grid_reader(required=False)
        if native is not None:
            return native.get_cell_geometry_column(i, j)
        import h5py

        from core.model_section import _geometry_column_from_dataset

        reader = self._selected_companion_reader()
        ni, nj, nk = reader.get_grid_shape()
        if ni is None or nj is None or nk is None:
            raise ValueError("Companion RESQML grid has incomplete dimensions.")
        points_path = reader._points_hdf_path()
        if reader.h5_path is None:
            raise ValueError("Companion RESQML H5 file was not found.")
        with h5py.File(reader.h5_path, "r") as h5:
            return _geometry_column_from_dataset(h5[points_path], i, j, ni, nj, nk)

    def get_cell_active_column(self, i: int, j: int):
        native = self._native_grid_reader(required=False)
        if native is not None:
            return native.get_cell_active_column(i, j)
        return self._selected_companion_reader().get_cell_active_column(i, j)

    def grid_to_dict(self, grid: GridInfo) -> dict[str, object]:
        result = _grid_to_dict(grid)
        property_names = self._property_names.get(grid.uuid, ())
        result.update(
            propertyCount=self._property_counts.get(grid.uuid, 0),
            propertyNames=list(property_names),
            isGeological=grid.uuid == self._geological_grid_uuid,
        )
        return result

    def _load_grids(self) -> list[GridInfo]:
        rows = _query_project_objects(self.data_path, ("PillarGrid2",))
        grids: list[GridInfo] = []
        for index, row in enumerate(rows):
            data_pk, droid, blob_type, time_stamp, bytes_size = row
            try:
                ni, nj = read_petrel_grid_horizontal_shape(self.data_path, data_pk)
            except (EOFError, OSError, ValueError):
                ni, nj = None, None
            title = self._model_names.get(_plain_uuid(str(droid)))
            if not title:
                title = f"Petrel model {index + 1} - {_format_bytes(bytes_size)}"
            if time_stamp and title.startswith("Petrel model "):
                title = f"{title} ({time_stamp})"
            grids.append(
                GridInfo(
                    index=index,
                    title=title,
                    uuid=str(droid),
                    ni=ni,
                    nj=nj,
                    nk=None,
                    grid_type=str(blob_type),
                    hdf_paths=(f"Data.ptd:data_pk={data_pk}; bytes={int(bytes_size or 0)}",),
                )
            )
        return grids

    def _load_properties(self) -> list[PropertyInfo]:
        rows = _query_project_objects(self.data_path, ("FloatProperty", "IntProperty"))
        grid_by_property = _property_grid_assignments(self.data_path)
        grids_by_horizontal_shape = {
            (grid.ni, grid.nj): grid.uuid
            for grid in self._grids
            if grid.ni is not None and grid.nj is not None
        }
        properties: list[PropertyInfo] = []
        for index, row in enumerate(rows):
            data_pk, droid, blob_type, time_stamp, bytes_size = row
            title = self._model_names.get(_plain_uuid(str(droid)))
            if not title:
                title = f"{blob_type} {index + 1}"
            if time_stamp and title.startswith(("FloatProperty ", "IntProperty ")):
                title = f"{title} ({time_stamp})"
            try:
                ni, nj, nk = read_petrel_property_shape(self.data_path, data_pk)
                shape = (nk, nj, ni)
            except (EOFError, OSError, ValueError):
                ni, nj, nk = None, None, None
                shape = None
            supporting_grid_uuid = grids_by_horizontal_shape.get((ni, nj))
            if supporting_grid_uuid is None:
                supporting_grid_uuid = grid_by_property.get(_plain_uuid(str(droid)))
            properties.append(
                PropertyInfo(
                    index=index,
                    title=title,
                    uuid=str(droid),
                    property_type=str(blob_type),
                    supporting_grid_uuid=supporting_grid_uuid,
                    hdf_paths=(f"Data.ptd:data_pk={data_pk}; bytes={int(bytes_size or 0)}",),
                    shape=shape,
                    dtype="float32" if blob_type == "FloatProperty" else "int32",
                )
            )
        return properties

    def _load_trajectories(self) -> None:
        if self.project is None:
            raise RuntimeError("Petrel project is not opened.")
        rows = _query_project_objects(self.data_path, ("XYZTrajectoryProviderData",))
        well_names = read_petrel_parent_names(self.project.ptd_path, [row[1] for row in rows])
        trajectories: list[WellTrajectoryInfo] = []
        for data_pk, droid, _blob_type, _time_stamp, _bytes_size in rows:
            normalized = _plain_uuid(droid)
            well_name = well_names.get(normalized)
            if not well_name:
                continue
            point_count = read_petrel_trajectory_point_count(self.data_path, data_pk)
            if point_count is None or point_count < 2:
                continue
            self._trajectory_data_pks[normalized] = data_pk
            trajectories.append(
                WellTrajectoryInfo(
                    index=len(trajectories),
                    title=well_name,
                    uuid=normalized,
                    well_name=well_name,
                    trajectory_type="XYZTrajectoryProviderData",
                    point_count=point_count,
                )
            )
        self._trajectories = trajectories

    def _enrich_from_companion_resqml(self) -> None:
        if self.project is None:
            return
        petrel_grids = {_plain_uuid(grid.uuid): grid for grid in self._grids}
        petrel_properties = {_plain_uuid(prop.uuid): prop for prop in self._properties}
        for epc_path in _companion_epc_candidates(self.project):
            reader = ResqmlReader(epc_path)
            try:
                reader.open(validate_with_resqpy=False)
            except (OSError, ValueError):
                continue
            matched_grids = [grid for grid in reader.list_grids() if _plain_uuid(grid.uuid) in petrel_grids]
            if not matched_grids:
                continue

            matched_grid_ids = {_plain_uuid(grid.uuid) for grid in matched_grids}
            matched_properties = [
                prop
                for prop in reader.list_properties()
                if _plain_uuid(prop.uuid) in petrel_properties
                and _plain_uuid(prop.supporting_grid_uuid or "") in matched_grid_ids
            ]
            self._apply_companion_metadata(matched_grids, matched_properties)
            for grid in matched_grids:
                self._companion_readers[_petrel_droid(grid.uuid)] = reader
            matched_names = [prop.title for prop in matched_properties]
            if _has_geological_properties(matched_names) or self._companion_epc_path is None:
                self._companion_epc_path = epc_path

    def _apply_native_metadata_summary(self) -> None:
        names_by_grid: dict[str, list[str]] = {}
        for prop in self._properties:
            if prop.supporting_grid_uuid:
                names_by_grid.setdefault(prop.supporting_grid_uuid, []).append(prop.title)
        for grid in self._grids:
            names = tuple(names_by_grid.get(grid.uuid, ()))
            if not names:
                continue
            self._property_counts[grid.uuid] = len(names)
            self._property_names[grid.uuid] = names
            if _has_geological_properties(list(names)):
                self._geological_grid_uuid = grid.uuid

    def _apply_native_grid_shapes_from_properties(self) -> None:
        nk_by_grid: dict[str, int] = {}
        for prop in self._properties:
            if prop.supporting_grid_uuid and prop.shape and len(prop.shape) == 3:
                nk_by_grid.setdefault(prop.supporting_grid_uuid, int(prop.shape[0]))
        self._grids = [
            GridInfo(
                index=grid.index,
                title=grid.title,
                uuid=grid.uuid,
                ni=grid.ni,
                nj=grid.nj,
                nk=nk_by_grid.get(grid.uuid, grid.nk),
                grid_type=grid.grid_type,
                hdf_paths=grid.hdf_paths,
            )
            for grid in self._grids
        ]

    def _apply_companion_metadata(
        self,
        companion_grids: list[GridInfo],
        companion_properties: list[PropertyInfo],
    ) -> None:
        grid_metadata = {_plain_uuid(grid.uuid): grid for grid in companion_grids}
        property_metadata = {_plain_uuid(prop.uuid): prop for prop in companion_properties}
        properties: list[PropertyInfo] = []
        for prop in self._properties:
            metadata = property_metadata.get(_plain_uuid(prop.uuid))
            if metadata is None:
                properties.append(prop)
                continue
            properties.append(
                PropertyInfo(
                    index=prop.index,
                    title=metadata.title,
                    uuid=prop.uuid,
                    indexable_element=metadata.indexable_element,
                    uom=metadata.uom,
                    property_kind=metadata.property_kind,
                    property_type=prop.property_type,
                    supporting_grid_uuid=_petrel_droid(metadata.supporting_grid_uuid or ""),
                    hdf_paths=prop.hdf_paths,
                    shape=metadata.shape,
                    dtype=prop.dtype,
                )
            )
        self._properties = properties

        names_by_grid: dict[str, list[str]] = {}
        for prop in companion_properties:
            grid_uuid = _plain_uuid(prop.supporting_grid_uuid or "")
            names_by_grid.setdefault(grid_uuid, []).append(prop.title)

        grids: list[GridInfo] = []
        for grid in self._grids:
            plain_uuid = _plain_uuid(grid.uuid)
            metadata = grid_metadata.get(plain_uuid)
            names = list(self._property_names.get(grid.uuid, ()))
            for name in names_by_grid.get(plain_uuid, []):
                if name not in names:
                    names.append(name)
            is_geological = _has_geological_properties(names)
            title = grid.title
            if metadata:
                role = "Geological model" if is_geological else "Petrel model"
                title = f"{role} - {metadata.title}"
            grids.append(
                GridInfo(
                    index=grid.index,
                    title=title,
                    uuid=grid.uuid,
                    ni=metadata.ni if metadata else grid.ni,
                    nj=metadata.nj if metadata else grid.nj,
                    nk=metadata.nk if metadata else grid.nk,
                    grid_type=grid.grid_type,
                    hdf_paths=grid.hdf_paths,
                )
            )
            if names:
                self._property_counts[grid.uuid] = len(names)
                self._property_names[grid.uuid] = tuple(names)
            if is_geological:
                self._geological_grid_uuid = grid.uuid
        self._grids = grids

    def _require_selected_grid(self) -> None:
        if self._selected_grid_uuid is None:
            raise ValueError("Select an internal Petrel model before reading project data.")

    def _selected_companion_reader(self, *, required: bool = True) -> ResqmlReader | None:
        if self._selected_grid_uuid is None:
            raise ValueError("Select an internal Petrel model before reading project data.")
        reader = self._companion_readers.get(_petrel_droid(self._selected_grid_uuid))
        if reader is None and required:
            raise NotImplementedError(_unsupported_decode_message())
        return reader

    def _native_property_reader(
        self,
        property_uuid: str,
        *,
        required: bool = True,
    ) -> PetrelPropertyReader | None:
        normalized = _plain_uuid(property_uuid)
        prop = next((item for item in self._properties if _plain_uuid(item.uuid) == normalized), None)
        if prop is None:
            raise ValueError(f"Petrel property UUID not found: {property_uuid}")
        cached = self._native_property_readers.get(prop.uuid)
        if cached is not None:
            return cached
        data_pk = _data_pk_from_paths(prop.hdf_paths)
        if data_pk is None:
            if required:
                raise ValueError(f"Petrel property has no Data.ptd object reference: {prop.title}")
            return None
        try:
            native = PetrelPropertyReader(self.data_path, data_pk, prop.property_type or "")
        except ValueError:
            if required:
                raise
            return None
        selected_shape = self.get_grid_shape()
        native_shape = (native.layout.ni, native.layout.nj, native.layout.nk)
        if all(selected_shape) and native_shape != selected_shape:
            if required:
                raise ValueError(
                    f"Petrel property shape {native_shape} does not match selected grid {selected_shape}"
                )
            return None
        self._native_property_readers[prop.uuid] = native
        return native

    def _native_grid_reader(self, *, required: bool = True) -> PetrelGridReader | None:
        self._require_selected_grid()
        assert self._selected_grid_uuid is not None
        cached = self._native_grid_readers.get(self._selected_grid_uuid)
        if cached is not None:
            return cached
        grid = next(item for item in self._grids if item.uuid == self._selected_grid_uuid)
        data_pk = _data_pk_from_paths(grid.hdf_paths)
        if data_pk is None:
            if required:
                raise ValueError(f"Petrel grid has no Data.ptd object reference: {grid.title}")
            return None
        try:
            native = PetrelGridReader(self.data_path, data_pk)
        except ValueError:
            if required:
                raise
            return None
        selected_shape = self.get_grid_shape()
        native_shape = (native.layout.ni, native.layout.nj, native.layout.nk)
        if all(selected_shape) and native_shape != selected_shape:
            if required:
                raise ValueError(f"Native Petrel grid shape {native_shape} does not match {selected_shape}")
            return None
        self._native_grid_readers[self._selected_grid_uuid] = native
        return native

    def _property_by_uuid(self, property_uuid: str) -> PropertyInfo:
        normalized = _plain_uuid(property_uuid)
        prop = next((item for item in self._properties if _plain_uuid(item.uuid) == normalized), None)
        if prop is None:
            raise ValueError(f"Petrel property UUID not found: {property_uuid}")
        return prop

    def _apply_native_grid_shape(self, native: PetrelGridReader) -> None:
        shape = (native.layout.ni, native.layout.nj, native.layout.nk)
        self._grids = [
            GridInfo(
                index=grid.index,
                title=grid.title,
                uuid=grid.uuid,
                ni=shape[0],
                nj=shape[1],
                nk=shape[2],
                grid_type=grid.grid_type,
                hdf_paths=grid.hdf_paths,
            )
            if grid.uuid == self._selected_grid_uuid
            else grid
            for grid in self._grids
        ]


def describe_petrel_project(path: str | Path) -> dict[str, object]:
    reader = PetrelProjectReader(path)
    reader.open()
    return {
        "kind": "petrel-project",
        "path": str(reader.epc_path),
        "dataPath": str(reader.data_path),
        "grids": [reader.grid_to_dict(grid) for grid in reader.list_grids()],
        "propertyCount": len(reader._properties),
        "selectedPropertyCount": len(reader.list_properties()),
        "geologicalGridUuid": reader._geological_grid_uuid,
        "companionResqmlPath": str(reader._companion_epc_path) if reader._companion_epc_path else None,
    }


def _query_project_objects(data_path: Path, blob_types: tuple[str, ...]) -> list[tuple[int, str, str, str, int]]:
    placeholders = ",".join("?" for _value in blob_types)
    sql = f"""
        select d.data_pk,
               d.droid,
               d.blob_type,
               d.time_stamp,
               coalesce(sum(length(bp.blob_data)), 0) as bytes_size
          from data d
          left join blob_parts bp on bp.data_fk = d.data_pk
         where d.blob_type in ({placeholders})
         group by d.data_pk
         order by d.time_stamp, d.data_pk
    """
    with sqlite3.connect(f"file:{data_path}?mode=ro", uri=True) as connection:
        return [
            (int(data_pk), str(droid), str(blob_type), str(time_stamp or ""), int(bytes_size or 0))
            for data_pk, droid, blob_type, time_stamp, bytes_size in connection.execute(sql, blob_types)
        ]


def _property_grid_assignments(data_path: Path) -> dict[str, str]:
    with sqlite3.connect(f"file:{data_path}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """
            select data_pk, droid, blob_type
              from data
             where blob_type in ('PillarGrid2', 'FloatProperty', 'IntProperty')
             order by data_pk
            """
        )
        current_grid: str | None = None
        previous_type: str | None = None
        assignments: dict[str, str] = {}
        for _data_pk, droid, blob_type in rows:
            if blob_type == "PillarGrid2":
                current_grid = None if previous_type == "PillarGrid2" else _petrel_droid(str(droid))
            elif current_grid is not None:
                assignments[_plain_uuid(str(droid))] = current_grid
            previous_type = str(blob_type)
        return assignments


def _grid_to_dict(grid: GridInfo) -> dict[str, object]:
    return {
        "index": grid.index,
        "title": grid.title,
        "uuid": grid.uuid,
        "ni": grid.ni,
        "nj": grid.nj,
        "nk": grid.nk,
        "gridType": grid.grid_type,
        "hdfPaths": list(grid.hdf_paths),
    }


def _companion_epc_candidates(project: PetrelProjectPath) -> list[Path]:
    roots = (project.project_path.parent, project.project_path.parent.parent)
    candidates: set[Path] = set()
    for root in roots:
        candidates.update(root.glob("*.epc"))
        candidates.update(root.glob("*/*.epc"))
    return sorted(candidates)


def _plain_uuid(value: str) -> str:
    match = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        value,
    )
    return match.group(1).lower() if match else value.lower()


def _petrel_droid(value: str) -> str:
    plain_uuid = _plain_uuid(value)
    return f"://Petrel/{plain_uuid}" if plain_uuid else value


def _has_geological_properties(names: list[str]) -> bool:
    normalized = [name.upper() for name in names]
    return any(any(marker in name for marker in GEOLOGICAL_PROPERTY_MARKERS) for name in normalized)


def _data_pk_from_paths(paths: tuple[str, ...]) -> int | None:
    for path in paths:
        match = re.search(r"data_pk=(\d+)", path)
        if match:
            return int(match.group(1))
    return None


def _native_property_scale(prop: PropertyInfo) -> float:
    title = prop.title.upper()
    return MILLIDARCY_TO_SQUARE_METRES if title == "PERM" or title.startswith("PERM_") else 1.0


def _scale_native_property_value(prop: PropertyInfo, value):
    if value == "":
        return value
    return value * _native_property_scale(prop)


def _trajectory_distances(points: np.ndarray) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)
    if len(values) == 0:
        return np.asarray([], dtype=np.float64)
    increments = np.linalg.norm(np.diff(values, axis=0), axis=1)
    return np.concatenate(([0.0], np.cumsum(increments)))


def _z_to_depth(values: np.ndarray) -> np.ndarray:
    output = np.asarray(values, dtype=np.float64)
    finite = output[np.isfinite(output)]
    return -output if finite.size and float(np.nanmean(finite)) < 0.0 else output


def _format_bytes(value: int) -> str:
    size = float(value or 0)
    for suffix in ("B", "KB", "MB", "GB"):
        if size < 1024 or suffix == "GB":
            return f"{size:.1f} {suffix}" if suffix != "B" else f"{int(size)} B"
        size /= 1024


def _unsupported_decode_message() -> str:
    return (
        "Native Petrel project metadata is readable, but PillarGrid2 geometry "
        "and property value decoding is not implemented yet."
    )

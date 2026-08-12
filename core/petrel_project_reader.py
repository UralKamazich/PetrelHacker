from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3

from core.resqml_reader import GridInfo, PropertyInfo, ResqmlReader


PETREL_PROJECT_SUFFIX = ".pet"
PETREL_PROJECT_DATA = "Data.ptd"
GEOLOGICAL_PROPERTY_MARKERS = ("PORO", "PERM", "NTG")


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
    (`*.ptd/Data.ptd`). This class currently exposes project contents and the
    user's selected internal grid through the same narrow metadata API used by
    RESQML and Rescue readers. Geometry/value decoding is intentionally kept
    behind explicit methods so extraction fails clearly until that parser is
    implemented for the selected project payloads.
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
        self._companion_epc_path: Path | None = None
        self._companion_readers: dict[str, ResqmlReader] = {}
        self._column_centers_cache: dict[str, object] = {}

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
        self._grids = self._load_grids()
        self._properties = self._load_properties()
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

    def get_grid_shape(self) -> tuple[int | None, int | None, int | None]:
        self._require_selected_grid()
        grid = next(grid for grid in self._grids if grid.uuid == self._selected_grid_uuid)
        return grid.ni, grid.nj, grid.nk

    def get_property_value(self, property_uuid: str, i: int, j: int, k: int):
        reader = self._selected_companion_reader()
        return reader.get_property_value(_plain_uuid(property_uuid), i, j, k)

    def get_property_column_values(self, property_uuid: str, i: int, j: int):
        reader = self._selected_companion_reader()
        return reader.get_property_column_values(_plain_uuid(property_uuid), i, j)

    def get_column_centers_xy(self):
        if self._selected_grid_uuid is None:
            raise ValueError("Select an internal Petrel model before reading project data.")
        cached = self._column_centers_cache.get(self._selected_grid_uuid)
        if cached is not None:
            return cached
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
            title = f"Petrel model {index + 1} - {_format_bytes(bytes_size)}"
            if time_stamp:
                title = f"{title} ({time_stamp})"
            grids.append(
                GridInfo(
                    index=index,
                    title=title,
                    uuid=str(droid),
                    ni=None,
                    nj=None,
                    nk=None,
                    grid_type=str(blob_type),
                    hdf_paths=(f"Data.ptd:data_pk={data_pk}; bytes={int(bytes_size or 0)}",),
                )
            )
        return grids

    def _load_properties(self) -> list[PropertyInfo]:
        rows = _query_project_objects(self.data_path, ("FloatProperty", "IntProperty"))
        properties: list[PropertyInfo] = []
        for index, row in enumerate(rows):
            data_pk, droid, blob_type, time_stamp, bytes_size = row
            title = f"{blob_type} {index + 1}"
            if time_stamp:
                title = f"{title} ({time_stamp})"
            properties.append(
                PropertyInfo(
                    index=index,
                    title=title,
                    uuid=str(droid),
                    property_type=str(blob_type),
                    supporting_grid_uuid=None,
                    hdf_paths=(f"Data.ptd:data_pk={data_pk}; bytes={int(bytes_size or 0)}",),
                    dtype="float32" if blob_type == "FloatProperty" else "int32",
                )
            )
        return properties

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

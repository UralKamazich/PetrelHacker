from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET


GRID_TYPES = (
    "IjkGridRepresentation",
    "Grid2dRepresentation",
    "UnstructuredGridRepresentation",
)
PROPERTY_TYPES = (
    "ContinuousProperty",
    "DiscreteProperty",
    "CategoricalProperty",
    "PointsProperty",
)


@dataclass(frozen=True)
class GridInfo:
    index: int
    title: str
    uuid: str
    ni: int | None = None
    nj: int | None = None
    nk: int | None = None
    grid_type: str | None = None
    hdf_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class PropertyInfo:
    index: int
    title: str
    uuid: str
    indexable_element: str | None = None
    uom: str | None = None
    property_kind: str | None = None
    property_type: str | None = None
    supporting_grid_uuid: str | None = None
    hdf_paths: tuple[str, ...] = ()
    shape: tuple[int, ...] | None = None
    dtype: str | None = None


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _local_name(element: ET.Element) -> str:
    return _strip_namespace(element.tag)


def _child_text(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if _local_name(element) == local_name and element.text:
            return element.text.strip()
    return None


def _children_text(root: ET.Element, local_name: str) -> list[str]:
    values: list[str] = []
    for element in root.iter():
        if _local_name(element) == local_name and element.text:
            value = element.text.strip()
            if value:
                values.append(value)
    return values


def _uuid_from_name(name: str) -> str | None:
    match = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        name,
    )
    return match.group(1).lower() if match else None


def _object_kind(root: ET.Element, fallback_name: str) -> str:
    xsi_type = root.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
    if ":" in xsi_type:
        xsi_type = xsi_type.split(":", 1)[1]
    if xsi_type.startswith("obj_"):
        xsi_type = xsi_type[4:]
    return xsi_type or _local_name(root) or fallback_name


def _title(root: ET.Element) -> str:
    citation_seen = False
    for element in root.iter():
        name = _local_name(element)
        if name == "Citation":
            citation_seen = True
        elif citation_seen and name == "Title" and element.text:
            return element.text.strip()
    return _child_text(root, "Title") or "(untitled)"


def _int_text(root: ET.Element, local_name: str) -> int | None:
    value = _child_text(root, local_name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _first_data_reference(root: ET.Element, content_type_fragment: str) -> tuple[str | None, str | None]:
    for ref in root.iter():
        content = None
        title = None
        uuid = None
        for child in ref.iter():
            name = _local_name(child)
            if name == "ContentType" and child.text:
                content = child.text.strip()
            elif name == "Title" and child.text:
                title = child.text.strip()
            elif name == "UUID" and child.text:
                uuid = child.text.strip().lower()
        if content and content_type_fragment in content:
            return uuid, title
    return None, None


class ResqmlReader:
    """Small metadata reader for EPC packages.

    The implementation deliberately avoids loading HDF5 arrays. It uses resqpy
    when available for basic opening validation, then parses EPC XML metadata
    directly so the console inspector works in a minimal environment.
    """

    def __init__(self, epc_path: str | Path):
        self.epc_path = Path(epc_path)
        self.model = None
        self.backend = "xml"
        self._objects: list[tuple[str, str, ET.Element]] = []
        self._grids: list[GridInfo] = []
        self._properties: list[PropertyInfo] = []
        self._selected_grid_uuid: str | None = None

    @property
    def h5_path(self) -> Path | None:
        candidate = self.epc_path.with_suffix(".h5")
        return candidate if candidate.exists() else None

    def open(self) -> None:
        if not self.epc_path.exists():
            raise FileNotFoundError(f"EPC file does not exist: {self.epc_path}")
        if not zipfile.is_zipfile(self.epc_path):
            raise ValueError(f"EPC is not a readable ZIP package: {self.epc_path}")

        self._try_open_with_resqpy()
        self._load_xml_objects()
        self._grids = self._parse_grids()
        self._properties = self._parse_properties()

    def list_grids(self) -> list[GridInfo]:
        return list(self._grids)

    def select_grid(self, grid_uuid: str) -> None:
        normalized = grid_uuid.lower()
        if not any(grid.uuid == normalized for grid in self._grids):
            raise ValueError(f"Grid UUID not found: {grid_uuid}")
        self._selected_grid_uuid = normalized

    def list_properties(self) -> list[PropertyInfo]:
        if self._selected_grid_uuid is None:
            return list(self._properties)
        return [
            prop
            for prop in self._properties
            if prop.supporting_grid_uuid in (None, self._selected_grid_uuid)
        ]

    def get_grid_shape(self) -> tuple[int | None, int | None, int | None]:
        if self._selected_grid_uuid is None:
            raise ValueError("No grid selected")
        for grid in self._grids:
            if grid.uuid == self._selected_grid_uuid:
                return grid.ni, grid.nj, grid.nk
        raise ValueError("Selected grid is not available")

    def get_property_value(self, property_uuid: str, i: int, j: int, k: int):
        if self._selected_grid_uuid is None:
            raise ValueError("No grid selected")
        prop = self._property_by_uuid(property_uuid)
        if not prop.hdf_paths:
            raise ValueError(f"Property has no HDF5 path: {prop.title}")
        if self.h5_path is None:
            raise ValueError("H5 file was not found next to EPC.")

        try:
            import h5py  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("h5py is required for HDF5 property reads.") from exc

        ni, nj, nk = self.get_grid_shape()
        if ni is None or nj is None or nk is None:
            raise ValueError("Selected grid has incomplete NI/NJ/NK metadata.")
        if not (0 <= i < ni and 0 <= j < nj and 0 <= k < nk):
            raise IndexError(f"Cell index out of bounds: i={i}, j={j}, k={k}; shape NI/NJ/NK={ni}/{nj}/{nk}")

        hdf_path = prop.hdf_paths[0]
        with h5py.File(self.h5_path, "r") as h5:
            if hdf_path not in h5:
                raise ValueError(f"Dataset path not found in H5: {hdf_path}")
            dataset = h5[hdf_path]
            shape = tuple(int(dim) for dim in dataset.shape)
            if shape == (nk, nj, ni):
                value = dataset[k, j, i]
            elif shape == (ni, nj, nk):
                value = dataset[i, j, k]
            elif len(shape) == 1 and shape[0] == nk * nj * ni:
                value = dataset[k * nj * ni + j * ni + i]
            else:
                raise ValueError(
                    f"Unsupported property dataset shape for {prop.title}: {shape}; "
                    f"expected {(nk, nj, ni)}, {(ni, nj, nk)} or flat {nk * nj * ni}"
                )

        return value.item() if hasattr(value, "item") else value

    def get_property_column_values(self, property_uuid: str, i: int, j: int):
        if self._selected_grid_uuid is None:
            raise ValueError("No grid selected")
        prop = self._property_by_uuid(property_uuid)
        if not prop.hdf_paths:
            raise ValueError(f"Property has no HDF5 path: {prop.title}")
        if self.h5_path is None:
            raise ValueError("H5 file was not found next to EPC.")

        try:
            import h5py  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("h5py is required for HDF5 property reads.") from exc

        ni, nj, nk = self.get_grid_shape()
        if ni is None or nj is None or nk is None:
            raise ValueError("Selected grid has incomplete NI/NJ/NK metadata.")
        if not (0 <= i < ni and 0 <= j < nj):
            raise IndexError(f"Column index out of bounds: i={i}, j={j}; shape NI/NJ={ni}/{nj}")

        hdf_path = prop.hdf_paths[0]
        with h5py.File(self.h5_path, "r") as h5:
            if hdf_path not in h5:
                raise ValueError(f"Dataset path not found in H5: {hdf_path}")
            dataset = h5[hdf_path]
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
                    f"Unsupported property dataset shape for {prop.title}: {shape}; "
                    f"expected {(nk, nj, ni)}, {(ni, nj, nk)} or flat {nk * nj * ni}"
                )
        return values

    def get_cell_active_column(self, i: int, j: int):
        if self._selected_grid_uuid is None:
            raise ValueError("No grid selected")
        if self.h5_path is None:
            return None

        path = self._cell_geometry_path()
        if path is None:
            return None

        try:
            import h5py  # type: ignore[import-not-found]
        except Exception:
            return None

        ni, nj, nk = self.get_grid_shape()
        if ni is None or nj is None or nk is None:
            return None
        if not (0 <= i < ni and 0 <= j < nj):
            raise IndexError(f"Column index out of bounds: i={i}, j={j}; shape NI/NJ={ni}/{nj}")

        with h5py.File(self.h5_path, "r") as h5:
            if path not in h5:
                return None
            return h5[path][:, j, i].astype(bool)

    def get_cell_geometry_column(self, i: int, j: int) -> dict[str, list[float]]:
        if self._selected_grid_uuid is None:
            raise ValueError("No grid selected")
        if self.h5_path is None:
            raise ValueError("H5 file was not found next to EPC.")

        try:
            import h5py  # type: ignore[import-not-found]
            import numpy as np
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("h5py and numpy are required for geometry reads.") from exc

        ni, nj, nk = self.get_grid_shape()
        if ni is None or nj is None or nk is None:
            raise ValueError("Selected grid has incomplete NI/NJ/NK metadata.")
        if not (0 <= i < ni and 0 <= j < nj):
            raise IndexError(f"Column index out of bounds: i={i}, j={j}; shape NI/NJ={ni}/{nj}")

        points_path = self._points_hdf_path()
        base_pillar_count = (ni + 1) * (nj + 1)
        pillar_indices = [
            j * (ni + 1) + i,
            j * (ni + 1) + i + 1,
            (j + 1) * (ni + 1) + i,
            (j + 1) * (ni + 1) + i + 1,
        ]

        with h5py.File(self.h5_path, "r") as h5:
            if points_path not in h5:
                raise ValueError(f"Points dataset path not found in H5: {points_path}")
            dataset = h5[points_path]
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

        interface_z = points[:, :, 2].mean(axis=1)
        interface_depth = _z_to_depth(interface_z)
        top_depth = np.minimum(interface_depth[:-1], interface_depth[1:])
        base_depth = np.maximum(interface_depth[:-1], interface_depth[1:])
        height = np.abs(interface_depth[1:] - interface_depth[:-1])

        size_i: list[float] = []
        size_j: list[float] = []
        area_xy: list[float] = []
        for k in range(nk):
            corners = points[k : k + 2, :, :2]
            top = corners[0]
            base = corners[1]
            i_edges = [
                _xy_distance(top[0], top[1]),
                _xy_distance(top[2], top[3]),
                _xy_distance(base[0], base[1]),
                _xy_distance(base[2], base[3]),
            ]
            j_edges = [
                _xy_distance(top[0], top[2]),
                _xy_distance(top[1], top[3]),
                _xy_distance(base[0], base[2]),
                _xy_distance(base[1], base[3]),
            ]
            size_i.append(float(np.mean(i_edges)))
            size_j.append(float(np.mean(j_edges)))
            area_xy.append(float(_polygon_area_xy(top[[0, 1, 3, 2]])))

        return {
            "TVD_top": [float(value) for value in top_depth],
            "TVD_base": [float(value) for value in base_depth],
            "CellHeight": [float(value) for value in height],
            "CellSizeI": size_i,
            "CellSizeJ": size_j,
            "CellAreaXY": area_xy,
        }

    def _property_by_uuid(self, property_uuid: str) -> PropertyInfo:
        normalized = property_uuid.lower()
        for prop in self._properties:
            if prop.uuid == normalized:
                return prop
        raise ValueError(f"Property UUID not found: {property_uuid}")

    def _cell_geometry_path(self) -> str | None:
        if self._selected_grid_uuid is None:
            return None
        for grid in self._grids:
            if grid.uuid == self._selected_grid_uuid:
                for path in grid.hdf_paths:
                    if path.endswith("/CellGeometryIsDefined"):
                        return path
        return None

    def _points_hdf_path(self) -> str:
        if self._selected_grid_uuid is None:
            raise ValueError("No grid selected")
        for grid in self._grids:
            if grid.uuid == self._selected_grid_uuid:
                for path in grid.hdf_paths:
                    if path.endswith("/Points"):
                        return path
        raise ValueError("Selected grid has no Points HDF path.")

    def _try_open_with_resqpy(self) -> None:
        try:
            import resqpy.model as rq_model  # type: ignore[import-not-found]
        except Exception:
            self.backend = "xml"
            return

        try:
            self.model = rq_model.Model(str(self.epc_path))
            self.backend = "resqpy+xml"
        except Exception:
            self.model = None
            self.backend = "xml"

    def _load_xml_objects(self) -> None:
        objects: list[tuple[str, str, ET.Element]] = []
        with zipfile.ZipFile(self.epc_path) as package:
            for name in package.namelist():
                if not name.lower().endswith(".xml"):
                    continue
                try:
                    root = _parse_epc_xml(package.read(name))
                except ET.ParseError:
                    continue
                objects.append((name, _object_kind(root, name), root))
        self._objects = objects

    def _parse_grids(self) -> list[GridInfo]:
        grids: list[GridInfo] = []
        for name, kind, root in self._objects:
            if not any(grid_type in kind for grid_type in GRID_TYPES):
                continue
            grids.append(
                GridInfo(
                    index=len(grids),
                    title=_title(root),
                    uuid=(root.attrib.get("uuid") or _uuid_from_name(name) or "").lower(),
                    ni=_int_text(root, "Ni"),
                    nj=_int_text(root, "Nj"),
                    nk=_int_text(root, "Nk"),
                    grid_type=kind,
                    hdf_paths=tuple(_children_text(root, "PathInHdfFile")),
                )
            )
        return grids

    def _parse_properties(self) -> list[PropertyInfo]:
        properties: list[PropertyInfo] = []
        h5_path = self.h5_path
        for name, kind, root in self._objects:
            if not any(property_type in kind for property_type in PROPERTY_TYPES):
                continue
            grid_uuid, _grid_title = _first_data_reference(root, "obj_IjkGridRepresentation")
            _kind_uuid, kind_title = _first_data_reference(root, "obj_PropertyKind")
            hdf_paths = tuple(_children_text(root, "PathInHdfFile"))
            hdf_info = _read_first_hdf_info(h5_path, hdf_paths)
            properties.append(
                PropertyInfo(
                    index=len(properties),
                    title=_title(root),
                    uuid=(root.attrib.get("uuid") or _uuid_from_name(name) or "").lower(),
                    indexable_element=_child_text(root, "IndexableElement"),
                    uom=_child_text(root, "Uom"),
                    property_kind=kind_title,
                    property_type=kind,
                    supporting_grid_uuid=grid_uuid,
                    hdf_paths=hdf_paths,
                    shape=hdf_info[0],
                    dtype=hdf_info[1],
                )
            )
        return properties


def _read_first_hdf_info(
    h5_path: Path | None,
    hdf_paths: tuple[str, ...],
) -> tuple[tuple[int, ...] | None, str | None]:
    if h5_path is None or not hdf_paths:
        return None, None
    try:
        import h5py  # type: ignore[import-not-found]
    except Exception:
        return None, None

    try:
        with h5py.File(h5_path, "r") as h5:
            for path in hdf_paths:
                if path in h5:
                    dataset = h5[path]
                    return tuple(int(dim) for dim in dataset.shape), str(dataset.dtype)
    except Exception:
        return None, None
    return None, None


def _parse_epc_xml(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        # Some Petrel/fesapi exports declare UTF-8 but contain legacy-encoded
        # bytes in free-text titles. Keep structural XML readable by replacing
        # only those invalid text bytes.
        return ET.fromstring(data.decode("utf-8", errors="replace"))


def _z_to_depth(values):
    import numpy as np

    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size and float(np.nanmean(finite)) < 0.0:
        return -arr
    return arr


def _xy_distance(a, b) -> float:
    import numpy as np

    delta = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    return float(np.sqrt(np.dot(delta, delta)))


def _polygon_area_xy(points) -> float:
    import numpy as np

    pts = np.asarray(points, dtype=float)
    x = pts[:, 0]
    y = pts[:, 1]
    return float(abs(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))))

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import math
import re
import struct
from xml.etree import ElementTree as ET

import numpy as np

from core.resqml_reader import GridInfo, PropertyInfo


RESCUE_MODEL_HEADER = b"\x25Rescue Model File\x00"
RESCUE_GEOMETRY_LABEL = b"Rescue Geometry File"
RESCUE_PROPERTY_LABEL = b"Rescue Property File"
PROPERTY_VALUES_OFFSET = 34
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


def is_rescue_path(path: str | Path) -> bool:
    candidate = Path(path)
    if candidate.is_dir():
        return _find_rescue_model_file(candidate) is not None
    if not candidate.is_file():
        return False
    try:
        return candidate.read_bytes().startswith(RESCUE_MODEL_HEADER)
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
        self._selected_grid_uuid: str | None = None
        self._xy_bounds: tuple[float, float, float, float] | None = None

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
        ni, nj, nk = _read_rescue_geometry_shape(geom_path)
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

    def list_grids(self) -> list[GridInfo]:
        return list(self._grids)

    def select_grid(self, grid_uuid: str) -> None:
        if not any(grid.uuid == grid_uuid for grid in self._grids):
            raise ValueError(f"Grid UUID not found: {grid_uuid}")
        self._selected_grid_uuid = grid_uuid

    def list_properties(self) -> list[PropertyInfo]:
        return list(self._properties)

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
        return np.asarray([self._read_property_value(property_uuid, i, j, k) for k in range(nk)], dtype=object)

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
        return {
            "TVD_top": [math.nan] * nk,
            "TVD_base": [math.nan] * nk,
            "CellHeight": [math.nan] * nk,
            "CellSizeI": [size_i] * nk,
            "CellSizeJ": [size_j] * nk,
            "CellAreaXY": [size_i * size_j] * nk,
        }

    def get_column_centers_xy(self) -> np.ndarray:
        ni, nj, _nk = self._require_shape()
        if self._xy_bounds is None:
            raise ValueError("Rescue CRS metadata was not found; cannot build XY grid.")
        xmin, xmax, ymin, ymax = self._xy_bounds
        xs = np.linspace(xmin, xmax, ni, dtype=float)
        ys = np.linspace(ymin, ymax, nj, dtype=float)
        xx, yy = np.meshgrid(xs, ys)
        return np.stack((xx, yy), axis=2)

    def _read_property_value(self, property_uuid: str, i: int, j: int, k: int):
        ni, nj, nk = self._require_shape()
        if not (0 <= i < ni and 0 <= j < nj and 0 <= k < nk):
            raise IndexError(f"Cell index out of bounds: i={i}, j={j}, k={k}; shape NI/NJ/NK={ni}/{nj}/{nk}")
        prop_file = self._property_files.get(property_uuid)
        if prop_file is None:
            raise ValueError(f"Property UUID not found: {property_uuid}")

        flat_index = k * nj * ni + j * ni + i
        values = self._decoded_property_values(property_uuid)
        if flat_index >= values.size:
            return ""
        value = float(values[flat_index])
        if not math.isfinite(value):
            return ""
        return value

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
                if RESCUE_GEOMETRY_LABEL in path.read_bytes()[:64]:
                    return path
            except OSError:
                continue
        raise FileNotFoundError(f"Rescue geometry file was not found in: {self.root_path}")

    def _discover_property_files(self) -> dict[int, _PropertyFile]:
        assert self.root_path is not None
        files: dict[int, _PropertyFile] = {}
        for path in self.root_path.glob("*.bin.*"):
            try:
                head = path.read_bytes()[:64]
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
        size_i = abs(xmax - xmin) / max(ni - 1, 1)
        size_j = abs(ymax - ymin) / max(nj - 1, 1)
        return float(size_i), float(size_j)

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

    def _property_info(self, property_uuid: str) -> PropertyInfo:
        for prop in self._properties:
            if prop.uuid == property_uuid:
                return prop
        raise ValueError(f"Property UUID not found: {property_uuid}")


def _find_rescue_model_file(path: Path) -> Path | None:
    for candidate in sorted(path.glob("*.bin")):
        try:
            if candidate.read_bytes().startswith(RESCUE_MODEL_HEADER):
                return candidate
        except OSError:
            continue
    return None


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


def _read_property_file_info(file_id: int, path: Path) -> _PropertyFile:
    with path.open("rb") as handle:
        head = handle.read(64)
        undefined_value = struct.unpack_from(">f", head, 26)[0]
    marker = _find_trailer_offset(path)
    end = marker - 2 if marker is not None else path.stat().st_size
    value_count = max(0, (end - PROPERTY_VALUES_OFFSET) // 4)
    return _PropertyFile(
        file_id=file_id,
        path=path,
        values_offset=PROPERTY_VALUES_OFFSET,
        value_count=value_count,
        undefined_value=undefined_value,
        first_run_length=int.from_bytes(head[30:34], "big", signed=False),
    )


def _decode_compact_property_file(
    prop_file: _PropertyFile,
    logical_count: int,
    invalid_abs_value_limit: np.float32 = DEFAULT_INVALID_ABS_VALUE_LIMIT,
    valid_range: tuple[np.float32, np.float32] | None = None,
) -> np.ndarray:
    data = prop_file.path.read_bytes()
    trailer = data.rfind(RESCUE_TRAILER)
    end = trailer - 2 if trailer > 0 else len(data)
    values = np.full(logical_count, np.nan, dtype=np.float32)

    pos = prop_file.values_offset
    logical = 0
    run_length = prop_file.first_run_length
    while pos < end and logical < logical_count:
        take = min(run_length, logical_count - logical, max(0, (end - pos) // 4))
        if take:
            block = np.frombuffer(data, dtype=">f4", count=take, offset=pos).astype(np.float32, copy=False)
            values[logical : logical + take] = block
            pos += take * 4
            logical += take
        if take < run_length or pos >= end or logical >= logical_count:
            break

        command = _read_compact_command(data, pos, end, logical_count - logical)
        if command is None:
            # Last-resort resync for slightly shifted streams. If we cannot find
            # a structural command nearby, leave the remaining cells as NaN.
            break
        command_pos, skip_count, next_run_length, next_pos = command
        pos = next_pos
        logical += min(skip_count, logical_count - logical)
        run_length = next_run_length
        if command_pos != pos and run_length < 0:
            break

    if prop_file.undefined_value is not None and math.isfinite(prop_file.undefined_value):
        values[values == np.float32(prop_file.undefined_value)] = np.nan
    values[~np.isfinite(values)] = np.nan
    values[np.abs(values) > invalid_abs_value_limit] = np.nan
    if valid_range is not None:
        min_value, max_value = valid_range
        values[(values < min_value) | (values > max_value)] = np.nan
    return values


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
    return None


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
        title_candidates = [value for value in candidates if value not in {"General", "SegmentID"} and len(value) > 1]
        if title_candidates:
            title = title_candidates[0]
            kind = candidates[1] if len(candidates) > 1 else None
            uom = next((value for value in segment_strings if "Unit" in value), None)
            return title, kind, uom
    return None, None, None


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

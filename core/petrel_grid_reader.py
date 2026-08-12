from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile

import numpy as np

from core.petrel_lz4 import PetrelLz4Blob
from core.petrel_property_reader import _read_bxml_dictionary, _read_varint, _tag


_STRAIGHT_PILLAR_MARKER = b"\x40\x06\x00\x88\x07"
_POSITION_MARKER = b"\x4c\x01\x93\x02"
_Z_VALUES_MARKER = b"\x5a\x01\x91"
_PILLAR_HEADER_SIZE = 256


@dataclass(frozen=True)
class PetrelGridLayout:
    data_pk: int
    ni: int
    nj: int
    nk: int


class PetrelGridReader:
    """Read straight-pillar Petrel PillarGrid2 geometry on demand."""

    def __init__(self, data_path: str | Path, data_pk: int) -> None:
        self.blob = PetrelLz4Blob(data_path, data_pk)
        ni, nj = _parse_horizontal_shape(self.blob)
        cached = _load_grid_index(self.blob.data_path, int(data_pk), ni, nj)
        if cached is None:
            cached = self._build_pillar_index(ni, nj)
            _save_grid_index(self.blob.data_path, int(data_pk), ni, nj, cached)
        self._pillar_xy, self._z_offsets, self._z_counts = cached
        unique_counts = np.unique(self._z_counts)
        if len(unique_counts) != 1 or int(unique_counts[0]) < 2:
            raise ValueError("Petrel grid uses variable or unreadable pillar Z sequences")
        self.layout = PetrelGridLayout(
            data_pk=int(data_pk),
            ni=ni,
            nj=nj,
            nk=int(unique_counts[0]) - 1,
        )

    def get_column_centers_xy(self) -> np.ndarray:
        pillars = self._pillar_xy.reshape(self.layout.nj + 1, self.layout.ni + 1, 2)
        return (
            pillars[:-1, :-1]
            + pillars[:-1, 1:]
            + pillars[1:, :-1]
            + pillars[1:, 1:]
        ) / 4.0

    def get_cell_geometry_column(self, i: int, j: int) -> dict[str, np.ndarray]:
        self._validate_column(i, j)
        stride = self.layout.ni + 1
        pillar_indices = (
            j * stride + i,
            j * stride + i + 1,
            (j + 1) * stride + i,
            (j + 1) * stride + i + 1,
        )
        pillars = []
        for pillar_index in pillar_indices:
            xy = self._pillar_xy[pillar_index]
            z = self._read_pillar_z(pillar_index)
            points = np.empty((self.layout.nk + 1, 3), dtype=np.float64)
            points[:, :2] = xy
            points[:, 2] = z
            points[~np.isfinite(z)] = np.nan
            pillars.append(points)
        return {"points": np.stack(pillars, axis=1)}

    def get_cell_active_column(self, i: int, j: int) -> np.ndarray:
        points = self.get_cell_geometry_column(i, j)["points"]
        interfaces_defined = np.isfinite(points).all(axis=(1, 2))
        return interfaces_defined[:-1] & interfaces_defined[1:]

    def _build_pillar_index(
        self,
        ni: int,
        nj: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        pillar_count = (ni + 1) * (nj + 1)
        xy = np.full((pillar_count, 2), np.nan, dtype=np.float64)
        z_offsets = np.full(pillar_count, -1, dtype=np.int64)
        z_counts = np.zeros(pillar_count, dtype=np.uint32)
        found_count = 0
        stream_offset = 0
        carry = b""
        last_marker_offset = -1

        for raw in self.blob.iter_blocks():
            combined = carry + raw
            combined_offset = stream_offset - len(carry)
            marker_offset = combined.find(_STRAIGHT_PILLAR_MARKER)
            while marker_offset >= 0:
                absolute_offset = combined_offset + marker_offset
                if absolute_offset > last_marker_offset:
                    if len(combined) - marker_offset < _PILLAR_HEADER_SIZE:
                        break
                    parsed = _parse_straight_pillar_header(combined, marker_offset, combined_offset)
                    if parsed is not None:
                        if found_count >= pillar_count:
                            raise ValueError("Petrel grid contains more pillars than its node dimensions")
                        xy[found_count], z_offsets[found_count], z_counts[found_count] = parsed
                        found_count += 1
                        last_marker_offset = absolute_offset
                marker_offset = combined.find(_STRAIGHT_PILLAR_MARKER, marker_offset + 1)
            carry = combined[-_PILLAR_HEADER_SIZE:]
            stream_offset += len(raw)

        if found_count != pillar_count:
            raise ValueError(
                f"Unsupported Petrel PillarGrid2 geometry: found {found_count} straight pillars; "
                f"expected {pillar_count}"
            )
        return xy, z_offsets, z_counts

    @lru_cache(maxsize=128)
    def _read_pillar_z(self, pillar_index: int) -> np.ndarray:
        count = int(self._z_counts[pillar_index])
        raw_size = count * 4
        offset = int(self._z_offsets[pillar_index])
        available = min(raw_size + 4096, self.blob.uncompressed_size - offset)
        raw = _remove_bxml_stream_metadata(self.blob.read_range(offset, available))[:raw_size]
        if len(raw) != raw_size:
            raise ValueError(f"Petrel pillar Z sequence is truncated: {len(raw)} < {raw_size}")
        values = np.frombuffer(raw, dtype="<f4", count=count).astype(np.float64)
        values[~np.isfinite(values) | (np.abs(values) >= 3.4e38)] = np.nan
        return values

    def _validate_column(self, i: int, j: int) -> None:
        if not (0 <= i < self.layout.ni and 0 <= j < self.layout.nj):
            raise IndexError(
                f"Petrel grid column is out of bounds: i={i}, j={j}; "
                f"shape={self.layout.ni}/{self.layout.nj}/{self.layout.nk}"
            )


def _parse_horizontal_shape(blob: PetrelLz4Blob) -> tuple[int, int]:
    first_block = blob.read_range(0, min(blob.uncompressed_size, 1024 * 1024))
    names, body_offset = _read_bxml_dictionary(first_block)
    try:
        node_size_tag = _tag(names.index("node_size"))
        int_tag = _tag(names.index("int"))
    except ValueError as exc:
        raise ValueError("Petrel grid has no readable node_size metadata") from exc
    marker = node_size_tag + b"\x03" + int_tag + b"\x01\x8d\x02"
    marker_offset = first_block.find(marker, body_offset)
    if marker_offset < 0:
        raise ValueError("Cannot locate Petrel grid dimensions in BXML")
    shape_offset = marker_offset + len(marker)
    node_i, node_j = struct.unpack_from("<II", first_block, shape_offset)
    node_k = first_block[shape_offset + 8]
    if node_i < 2 or node_j < 2 or node_k != 1:
        raise ValueError(f"Unsupported Petrel grid node dimensions: {node_i}/{node_j}/{node_k}")
    return node_i - 1, node_j - 1


def _parse_straight_pillar_header(
    data: bytes,
    marker_offset: int,
    data_offset: int,
) -> tuple[tuple[float, float], int, int] | None:
    header = data[marker_offset : marker_offset + _PILLAR_HEADER_SIZE]
    cleaned, original_offsets = _remove_bxml_page_frames(header)
    position_offset = cleaned.find(_POSITION_MARKER)
    z_values_offset = cleaned.find(_Z_VALUES_MARKER)
    if position_offset < 0 or z_values_offset < 0:
        return None
    position_payload = original_offsets[position_offset + len(_POSITION_MARKER) - 1] + 1
    x, y = struct.unpack_from("<dd", header, position_payload)
    count, cleaned_payload_offset = _read_varint(cleaned, z_values_offset + len(_Z_VALUES_MARKER))
    if count < 2:
        return None
    payload_offset = original_offsets[cleaned_payload_offset - 1] + 1
    return (x, y), data_offset + marker_offset + payload_offset, count


def _remove_bxml_page_frames(data: bytes) -> tuple[bytes, list[int]]:
    cleaned = bytearray()
    original_offsets: list[int] = []
    offset = 0
    while offset < len(data):
        frame_end = _bxml_page_frame_end(data, offset)
        if frame_end is not None:
            offset = frame_end
            continue
        cleaned.append(data[offset])
        original_offsets.append(offset)
        offset += 1
    return bytes(cleaned), original_offsets


def _remove_bxml_stream_metadata(data: bytes) -> bytes:
    output = bytearray()
    offset = 0
    while offset < len(data):
        frame_end = _bxml_page_frame_end(data, offset)
        if frame_end is not None:
            offset = frame_end
            continue
        dictionary_end = _bxml_dictionary_extension_end(data, offset)
        if dictionary_end is not None:
            offset = dictionary_end
            continue
        output.append(data[offset])
        offset += 1
    return bytes(output)


def _bxml_page_frame_end(data: bytes, offset: int) -> int | None:
    if offset >= len(data) or data[offset] != 0xA0:
        return None
    try:
        size, end = _read_varint(data, offset + 1)
    except (IndexError, ValueError):
        return None
    return end if 1024 <= size <= 8192 else None


def _bxml_dictionary_extension_end(data: bytes, offset: int) -> int | None:
    if offset >= len(data) or data[offset] != 0xA1:
        return None
    cursor = offset
    name_count = 0
    while cursor + 2 <= len(data) and data[cursor] == 0xA1:
        size = data[cursor + 1]
        end = cursor + 2 + size
        if not size or end > len(data):
            return None
        name = data[cursor + 2 : end]
        if not all(0x20 <= byte < 0x7F for byte in name):
            return None
        name_count += 1
        cursor = end
    if name_count < 2 or cursor >= len(data) or data[cursor] != 0xA0:
        return None
    try:
        _size, end = _read_varint(data, cursor + 1)
    except (IndexError, ValueError):
        return None
    return end


def _grid_index_path(data_path: Path, data_pk: int) -> Path:
    identity = hashlib.sha256(f"{data_path.resolve()}:{data_pk}".encode("utf-8")).hexdigest()[:24]
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches" / "PetrelHacker"
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "PetrelHacker"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "petrelhacker"
    return root / "grid-index" / f"{identity}.npz"


def _load_grid_index(
    data_path: Path,
    data_pk: int,
    ni: int,
    nj: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    path = _grid_index_path(data_path, data_pk)
    try:
        stat = data_path.stat()
        with np.load(path, allow_pickle=False) as cached:
            if (
                int(cached["source_size"]) != stat.st_size
                or int(cached["source_mtime_ns"]) != stat.st_mtime_ns
                or int(cached["ni"]) != ni
                or int(cached["nj"]) != nj
            ):
                return None
            expected = (ni + 1) * (nj + 1)
            xy = np.asarray(cached["xy"], dtype=np.float64)
            offsets = np.asarray(cached["z_offsets"], dtype=np.int64)
            counts = np.asarray(cached["z_counts"], dtype=np.uint32)
            if xy.shape != (expected, 2) or offsets.shape != (expected,) or counts.shape != (expected,):
                return None
            return xy, offsets, counts
    except (OSError, KeyError, ValueError):
        return None


def _save_grid_index(
    data_path: Path,
    data_pk: int,
    ni: int,
    nj: int,
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    path = _grid_index_path(data_path, data_pk)
    try:
        stat = data_path.stat()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as stream:
            temporary_path = Path(stream.name)
        try:
            np.savez_compressed(
                temporary_path,
                source_size=np.int64(stat.st_size),
                source_mtime_ns=np.int64(stat.st_mtime_ns),
                ni=np.int32(ni),
                nj=np.int32(nj),
                xy=arrays[0],
                z_offsets=arrays[1],
                z_counts=arrays[2],
            )
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError:
        return

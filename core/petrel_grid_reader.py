from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile

import numpy as np

from core.petrel_lz4 import PetrelLz4Blob, read_first_petrel_lz4_block
from core.petrel_property_reader import _read_bxml_dictionary, _read_varint, _tag


_GRID_INDEX_VERSION = 5
_STRAIGHT_PILLAR_MARKER = b"\x40\x06\x00\x88\x07"
_POSITION_MARKER = b"\x4c\x01\x93\x02"
_CURVE_SIZE_MARKER = b"\x4c\x89\x03"
_VERTICES_MARKER = b"\x50\x01\x93"
_Z_VALUES_MARKER = b"\x5a\x01\x91"
_PILLAR_HEADER_SIZE = 256
_VERTICAL_CURVE_XY_TOLERANCE = 1e-3


@dataclass(frozen=True)
class _PillarMarkers:
    """Byte markers inside pillar records.

    Each marker starts with a BXML tag byte whose value depends on the name's
    position in the file dictionary, so it shifts when a grid stores extra
    sections (for example ``connections``).
    """

    straight: bytes = _STRAIGHT_PILLAR_MARKER
    position: bytes = _POSITION_MARKER
    curve_size: bytes = _CURVE_SIZE_MARKER
    vertices: bytes = _VERTICES_MARKER
    z_values: bytes = _Z_VALUES_MARKER


_DEFAULT_MARKERS = _PillarMarkers()


@dataclass(frozen=True)
class PetrelGridLayout:
    data_pk: int
    ni: int
    nj: int
    nk: int


@dataclass(frozen=True)
class _GridIndex:
    xy: np.ndarray
    z_offsets: np.ndarray
    z_counts: np.ndarray
    page_logical_starts: np.ndarray
    page_raw_starts: np.ndarray
    page_sizes: np.ndarray
    geometry_mode: str


class PetrelGridReader:
    """Read Petrel PillarGrid2 geometry and normalize vertical pillar curves."""

    def __init__(self, data_path: str | Path, data_pk: int) -> None:
        self.blob = PetrelLz4Blob(data_path, data_pk)
        ni, nj = _parse_horizontal_shape(self.blob)
        index = _load_grid_index(self.blob.data_path, int(data_pk), ni, nj)
        if index is None:
            index = self._build_pillar_index(ni, nj)
            _save_grid_index(self.blob.data_path, int(data_pk), ni, nj, index)
        self._pillar_xy = index.xy
        self._z_offsets = index.z_offsets
        self._z_counts = index.z_counts
        self._page_logical_starts = index.page_logical_starts
        self._page_raw_starts = index.page_raw_starts
        self._page_sizes = index.page_sizes
        self.geometry_mode = index.geometry_mode

        unique_counts = np.unique(self._z_counts[self._z_counts > 0])
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

    def _build_pillar_index(self, ni: int, nj: int) -> _GridIndex:
        prefix = self.blob.read_range(0, min(self.blob.uncompressed_size, 16 * 1024 * 1024))
        geometry_mode = _detect_geometry_mode_prefix(prefix)
        markers = _pillar_markers(prefix)
        if self.blob.uncompressed_size > 256 * 1024 * 1024:
            if geometry_mode != "position":
                raise ValueError("Large Petrel curve grids are not supported by the streaming decoder")
            return self._build_streaming_position_index(ni, nj, prefix, markers)

        raw = b"".join(self.blob.iter_blocks())
        pillar_count = (ni + 1) * (nj + 1)
        pillar_types, _type_pages = _read_pillar_types(raw, pillar_count)
        pillar_data, pillar_pages, _names = _read_paged_section(raw, b"pillars")

        records: list[tuple[tuple[float, float], int, int]] = []
        marker_offset = pillar_data.find(markers.straight)
        while marker_offset >= 0:
            if geometry_mode == "position":
                parsed = _parse_position_pillar_header(pillar_data, marker_offset, markers)
            else:
                parsed = _parse_vertical_curve_pillar_header(pillar_data, marker_offset, markers)
            if parsed is not None:
                records.append(parsed)
            marker_offset = pillar_data.find(markers.straight, marker_offset + 1)

        defined_indices = np.flatnonzero(pillar_types != 0)
        if len(records) != len(defined_indices):
            raise ValueError(
                f"Unsupported Petrel PillarGrid2 {geometry_mode} geometry: found {len(records)} "
                f"defined pillars; expected {len(defined_indices)}"
            )

        xy = np.full((pillar_count, 2), np.nan, dtype=np.float64)
        z_offsets = np.full(pillar_count, -1, dtype=np.int64)
        z_counts = np.zeros(pillar_count, dtype=np.uint32)
        for pillar_index, (pillar_xy, logical_offset, count) in zip(defined_indices, records):
            xy[pillar_index] = pillar_xy
            z_offsets[pillar_index] = logical_offset
            z_counts[pillar_index] = count

        return _GridIndex(
            xy=xy,
            z_offsets=z_offsets,
            z_counts=z_counts,
            page_logical_starts=np.asarray([page[0] for page in pillar_pages], dtype=np.int64),
            page_raw_starts=np.asarray([page[1] for page in pillar_pages], dtype=np.int64),
            page_sizes=np.asarray([page[2] for page in pillar_pages], dtype=np.int64),
            geometry_mode=geometry_mode,
        )

    def _build_streaming_position_index(
        self,
        ni: int,
        nj: int,
        prefix: bytes,
        markers: _PillarMarkers = _DEFAULT_MARKERS,
    ) -> _GridIndex:
        """Index pillars of a large grid without loading the whole blob.

        The pillars section is a sequence of BXML pages; page frames can split a
        pillar record (even its marker), so markers are searched in the
        de-framed logical stream and Z offsets are stored as logical offsets
        together with the page map.
        """
        pillar_count = (ni + 1) * (nj + 1)
        try:
            pillar_types, _type_pages = _read_pillar_types(prefix, pillar_count)
            defined_indices = np.flatnonzero(pillar_types != 0)
        except ValueError:
            defined_indices = np.arange(pillar_count)
        section_offset = prefix.find(b"\xa1\x07pillars")
        if section_offset < 0:
            raise ValueError("Petrel BXML has no pillars section")
        _names, cursor = _read_dictionary_extension(prefix, section_offset)

        xy = np.full((pillar_count, 2), np.nan, dtype=np.float64)
        z_offsets = np.full(pillar_count, -1, dtype=np.int64)
        z_counts = np.zeros(pillar_count, dtype=np.uint32)
        page_logical_starts: list[int] = []
        page_raw_starts: list[int] = []
        page_sizes: list[int] = []
        found_count = 0
        carry = b""
        carry_logical = 0
        logical = 0
        last_marker = -1

        def scan(chunk: bytes) -> None:
            nonlocal carry, carry_logical, found_count, last_marker
            combined = carry + chunk
            base = carry_logical
            marker_offset = combined.find(markers.straight)
            while marker_offset >= 0:
                absolute = base + marker_offset
                if absolute > last_marker:
                    if len(combined) - marker_offset < _PILLAR_HEADER_SIZE:
                        break
                    parsed = _parse_position_pillar_header(combined, marker_offset, markers)
                    if parsed is not None:
                        if found_count >= len(defined_indices):
                            raise ValueError("Petrel grid contains more pillars than its node dimensions")
                        pillar_index = defined_indices[found_count]
                        xy[pillar_index] = parsed[0]
                        z_offsets[pillar_index] = base + parsed[1]
                        z_counts[pillar_index] = parsed[2]
                        found_count += 1
                    last_marker = absolute
                marker_offset = combined.find(markers.straight, marker_offset + 1)
            keep = min(len(combined), _PILLAR_HEADER_SIZE)
            carry = combined[len(combined) - keep :]
            carry_logical = base + len(combined) - keep

        stream = _BlobStream(self.blob)
        total = self.blob.uncompressed_size
        while cursor < total:
            head = stream.read(cursor, 16)
            if head[:1] == b"\xa0":
                size, payload_offset = _read_varint(head, 1)
                payload_start = cursor + payload_offset
                if size <= 0 or payload_start + size > total:
                    break
                page_logical_starts.append(logical)
                page_raw_starts.append(payload_start)
                page_sizes.append(size)
                scan(stream.read(payload_start, size))
                logical += size
                cursor = payload_start + size
                continue
            if head[:1] == b"\xa1":
                try:
                    _extra, extension_end = _read_dictionary_extension(stream.read(cursor, 4096), 0)
                except (UnicodeDecodeError, ValueError):
                    pass
                else:
                    cursor += extension_end
                    continue
            # Unframed tail: treat the rest of the blob as one page.
            size = total - cursor
            page_logical_starts.append(logical)
            page_raw_starts.append(cursor)
            page_sizes.append(size)
            for chunk_start in range(cursor, total, 4 * 1024 * 1024):
                scan(stream.read(chunk_start, min(4 * 1024 * 1024, total - chunk_start)))
            break
        scan(b"\0" * _PILLAR_HEADER_SIZE)

        if found_count != len(defined_indices):
            raise ValueError(
                f"Unsupported Petrel PillarGrid2 position geometry: found {found_count} pillars; "
                f"expected {len(defined_indices)}"
            )
        return _GridIndex(
            xy=xy,
            z_offsets=z_offsets,
            z_counts=z_counts,
            page_logical_starts=np.asarray(page_logical_starts, dtype=np.int64),
            page_raw_starts=np.asarray(page_raw_starts, dtype=np.int64),
            page_sizes=np.asarray(page_sizes, dtype=np.int64),
            geometry_mode="position",
        )

    @lru_cache(maxsize=128)
    def _read_pillar_z(self, pillar_index: int) -> np.ndarray:
        count = int(self._z_counts[pillar_index])
        if count == 0:
            return np.full(self.layout.nk + 1, np.nan, dtype=np.float64)
        if len(self._page_sizes):
            raw = self._read_paged_range(int(self._z_offsets[pillar_index]), count * 4)
        else:
            raw_size = count * 4
            offset = int(self._z_offsets[pillar_index])
            available = min(raw_size + 4096, self.blob.uncompressed_size - offset)
            raw = _remove_bxml_stream_metadata(self.blob.read_range(offset, available))[:raw_size]
            if len(raw) != raw_size:
                raise ValueError(f"Petrel pillar Z sequence is truncated: {len(raw)} < {raw_size}")
        values = np.frombuffer(raw, dtype="<f4", count=count).astype(np.float64)
        values[~np.isfinite(values) | (np.abs(values) >= 3.4e38)] = np.nan
        return values

    def _read_paged_range(self, logical_offset: int, size: int) -> bytes:
        output = bytearray()
        cursor = logical_offset
        pending = size
        while pending:
            page_index = bisect_right(self._page_logical_starts, cursor) - 1
            if page_index < 0:
                raise ValueError("Petrel pillar sequence starts outside its BXML pages")
            within_page = cursor - int(self._page_logical_starts[page_index])
            available = int(self._page_sizes[page_index]) - within_page
            if available <= 0:
                raise ValueError("Petrel pillar sequence crosses an unreadable BXML page")
            count = min(pending, available)
            output.extend(
                self.blob.read_range(int(self._page_raw_starts[page_index]) + within_page, count)
            )
            cursor += count
            pending -= count
        return bytes(output)

    def _validate_column(self, i: int, j: int) -> None:
        if not (0 <= i < self.layout.ni and 0 <= j < self.layout.nj):
            raise IndexError(
                f"Petrel grid column is out of bounds: i={i}, j={j}; "
                f"shape={self.layout.ni}/{self.layout.nj}/{self.layout.nk}"
            )


class _BlobStream:
    """Sequential reader over decompressed blob blocks with a small buffer."""

    def __init__(self, blob: PetrelLz4Blob) -> None:
        self._blocks = blob.iter_blocks()
        self._buffer = bytearray()
        self._start = 0

    def read(self, offset: int, size: int) -> bytes:
        if offset < self._start:
            raise ValueError("Petrel blob stream cannot seek backwards")
        while offset > self._start + len(self._buffer):
            self._start += len(self._buffer)
            self._buffer.clear()
            block = next(self._blocks, None)
            if block is None:
                return b""
            self._buffer.extend(block)
        del self._buffer[: offset - self._start]
        self._start = offset
        while len(self._buffer) < size:
            block = next(self._blocks, None)
            if block is None:
                break
            self._buffer.extend(block)
        return bytes(self._buffer[:size])


def _parse_horizontal_shape(blob: PetrelLz4Blob) -> tuple[int, int]:
    first_block = blob.read_range(0, min(blob.uncompressed_size, 1024 * 1024))
    return _parse_horizontal_shape_data(first_block)


def read_petrel_grid_horizontal_shape(data_path: str | Path, data_pk: int) -> tuple[int, int]:
    first_block = read_first_petrel_lz4_block(data_path, data_pk)
    return _parse_horizontal_shape_data(first_block)


def _parse_horizontal_shape_data(first_block: bytes) -> tuple[int, int]:
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


def _detect_geometry_mode(data: bytes) -> str:
    _section, _pages, names = _read_paged_section(data, b"pillars")
    if "position" in names:
        return "position"
    if {"curve", "vertices", "zvalues"}.issubset(names):
        return "vertical_curve"
    raise ValueError("Unsupported Petrel pillar geometry encoding")


def _detect_geometry_mode_prefix(data: bytes) -> str:
    has_position = b"\xa1\x08position" in data
    has_curve = b"\xa1\x05curve" in data and b"\xa1\x08vertices" in data
    if has_position and not has_curve:
        return "position"
    if has_curve and not has_position:
        return "vertical_curve"
    raise ValueError("Cannot determine Petrel pillar geometry encoding")


def _pillar_markers(data: bytes) -> _PillarMarkers:
    """Derive pillar record markers from the tags used by this file."""
    marker = b"\xa1\x07pillars"
    offset = data.find(marker)
    if offset < 0:
        return _DEFAULT_MARKERS
    try:
        names, cursor = _read_dictionary_extension(data, offset)
        _size, payload = _read_varint(data, cursor + 1)
    except (IndexError, UnicodeDecodeError, ValueError):
        return _DEFAULT_MARKERS
    # The page starts with the "pillars" element: [flag] 0x42 <tag>.
    tag_offset = data.find(b"\x42", payload, payload + 8)
    if tag_offset < 0 or names[0] != "pillars":
        return _DEFAULT_MARKERS
    base = data[tag_offset + 1]

    def tag(name: str, default: bytes) -> bytes:
        if name not in names:
            return default[:1]
        value = base + 2 * names.index(name)
        return bytes((value,)) if value <= 0xFF else default[:1]

    return _PillarMarkers(
        straight=tag("pillar", _STRAIGHT_PILLAR_MARKER) + _STRAIGHT_PILLAR_MARKER[1:],
        position=tag("double", _POSITION_MARKER) + _POSITION_MARKER[1:],
        curve_size=tag("size", _CURVE_SIZE_MARKER) + _CURVE_SIZE_MARKER[1:],
        vertices=tag("double", _VERTICES_MARKER) + _VERTICES_MARKER[1:],
        z_values=tag("float", _Z_VALUES_MARKER) + _Z_VALUES_MARKER[1:],
    )


def _read_pillar_types(data: bytes, expected_count: int) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    section, pages, _names = _read_paged_section(data, b"pillar_types")
    marker_offset = section.find(b"\x01\x8d")
    while marker_offset >= 0:
        try:
            count, payload_offset = _read_varint(section, marker_offset + 2)
        except (IndexError, ValueError):
            count = -1
            payload_offset = 0
        if count == expected_count and payload_offset + count * 4 <= len(section):
            values = np.frombuffer(section, dtype="<i4", count=count, offset=payload_offset).copy()
            # 0 = undefined, 2 = straight; other small codes (4, 5) are faulted
            # pillars, read as their first z-sequence.
            if len(values) and int(values.min()) >= 0 and int(values.max()) < 64:
                return values, pages
        marker_offset = section.find(b"\x01\x8d", marker_offset + 1)
    raise ValueError(f"Cannot read {expected_count} Petrel pillar type entries")


def _read_paged_section(
    data: bytes,
    section_name: bytes,
) -> tuple[bytes, list[tuple[int, int, int]], list[str]]:
    marker = b"\xa1" + bytes((len(section_name),)) + section_name
    cursor = data.find(marker)
    if cursor < 0:
        raise ValueError(f"Petrel BXML has no {section_name.decode('ascii')} section")
    names, cursor = _read_dictionary_extension(data, cursor)

    chunks: list[bytes] = []
    pages: list[tuple[int, int, int]] = []
    logical_start = 0
    while cursor < len(data):
        if data[cursor] == 0xA0:
            size, payload_start = _read_varint(data, cursor + 1)
            payload_end = payload_start + size
            if size <= 0 or payload_end > len(data):
                raise ValueError("Invalid Petrel BXML page size")
            chunks.append(data[payload_start:payload_end])
            pages.append((logical_start, payload_start, size))
            logical_start += size
            cursor = payload_end
            continue
        if data[cursor] == 0xA1:
            try:
                extra_names, extension_end = _read_dictionary_extension(data, cursor)
            except (UnicodeDecodeError, ValueError):
                break
            if section_name == b"pillar_types" and extra_names[0] == "pillars":
                break
            names.extend(extra_names)
            cursor = extension_end
            continue
        break
    if cursor < len(data) and (section_name == b"pillars" or data[cursor] != 0xA1):
        pages.append((logical_start, cursor, len(data) - cursor))
        chunks.append(data[cursor:])
    if not pages:
        raise ValueError(f"Petrel BXML {section_name.decode('ascii')} section has no pages")
    return b"".join(chunks), pages, names


def _read_dictionary_extension(data: bytes, offset: int) -> tuple[list[str], int]:
    names: list[str] = []
    cursor = offset
    while cursor + 2 <= len(data) and data[cursor] == 0xA1:
        size = data[cursor + 1]
        end = cursor + 2 + size
        if not size or end > len(data):
            raise ValueError("Truncated Petrel BXML dictionary extension")
        name = data[cursor + 2 : end]
        if not all(0x20 <= byte < 0x7F for byte in name):
            raise ValueError("Invalid Petrel BXML dictionary name")
        names.append(name.decode("ascii"))
        cursor = end
    if not names or cursor >= len(data) or data[cursor] != 0xA0:
        raise ValueError("Petrel BXML dictionary extension has no page")
    return names, cursor


def _parse_position_pillar_header(
    data: bytes,
    marker_offset: int,
    markers: _PillarMarkers = _DEFAULT_MARKERS,
) -> tuple[tuple[float, float], int, int] | None:
    header = data[marker_offset : marker_offset + _PILLAR_HEADER_SIZE]
    position_offset = header.find(markers.position)
    z_values_offset = header.find(markers.z_values)
    if position_offset < 0 or z_values_offset < 0:
        return None
    position_payload = position_offset + len(markers.position)
    x, y = struct.unpack_from("<dd", header, position_payload)
    count, payload_offset = _read_varint(header, z_values_offset + len(markers.z_values))
    if count < 2:
        return None
    return (x, y), marker_offset + payload_offset, count


def _parse_framed_position_pillar_header(
    data: bytes,
    marker_offset: int,
    data_offset: int,
    markers: _PillarMarkers = _DEFAULT_MARKERS,
) -> tuple[tuple[float, float], int, int] | None:
    header = data[marker_offset : marker_offset + _PILLAR_HEADER_SIZE]
    cleaned, original_offsets = _remove_bxml_page_frames(header)
    position_offset = cleaned.find(markers.position)
    z_values_offset = cleaned.find(markers.z_values)
    if position_offset < 0 or z_values_offset < 0:
        return None
    position_payload = original_offsets[position_offset + len(markers.position) - 1] + 1
    x, y = struct.unpack_from("<dd", header, position_payload)
    count, cleaned_payload_offset = _read_varint(
        cleaned, z_values_offset + len(markers.z_values)
    )
    if count < 2:
        return None
    payload_offset = original_offsets[cleaned_payload_offset - 1] + 1
    return (x, y), data_offset + marker_offset + payload_offset, count


def _parse_vertical_curve_pillar_header(
    data: bytes,
    marker_offset: int,
    markers: _PillarMarkers = _DEFAULT_MARKERS,
) -> tuple[tuple[float, float], int, int] | None:
    header = data[marker_offset : marker_offset + _PILLAR_HEADER_SIZE]
    if header.find(markers.curve_size) < 0:
        return None
    vertices_offset = header.find(markers.vertices)
    z_values_offset = header.find(markers.z_values)
    if vertices_offset < 0 or z_values_offset < 0:
        return None
    value_count, vertices_payload = _read_varint(
        header, vertices_offset + len(markers.vertices)
    )
    if value_count != 9 or vertices_payload + value_count * 8 > len(header):
        return None
    vertices = np.frombuffer(header, dtype="<f8", count=value_count, offset=vertices_payload).reshape(3, 3)
    xy_spread = np.ptp(vertices[:, :2], axis=0)
    if not np.isfinite(vertices).all() or float(np.max(xy_spread)) > _VERTICAL_CURVE_XY_TOLERANCE:
        raise ValueError(
            "Petrel grid contains curved pillars that cannot be normalized as vertical geometry"
        )
    count, payload_offset = _read_varint(header, z_values_offset + len(markers.z_values))
    if count < 2:
        return None
    xy = tuple(np.mean(vertices[:, :2], axis=0))
    return (float(xy[0]), float(xy[1])), marker_offset + payload_offset, count


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


# Kept for small framed values and compatibility with existing binary fixtures.
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


def _load_grid_index(data_path: Path, data_pk: int, ni: int, nj: int) -> _GridIndex | None:
    path = _grid_index_path(data_path, data_pk)
    try:
        stat = data_path.stat()
        with np.load(path, allow_pickle=False) as cached:
            if "version" not in cached.files:
                if (
                    int(cached["source_size"]) == stat.st_size
                    and int(cached["source_mtime_ns"]) == stat.st_mtime_ns
                    and int(cached["ni"]) == ni
                    and int(cached["nj"]) == nj
                ):
                    expected = (ni + 1) * (nj + 1)
                    xy = np.asarray(cached["xy"], dtype=np.float64)
                    offsets = np.asarray(cached["z_offsets"], dtype=np.int64)
                    counts = np.asarray(cached["z_counts"], dtype=np.uint32)
                    if xy.shape == (expected, 2) and offsets.shape == counts.shape == (expected,):
                        empty = np.asarray([], dtype=np.int64)
                        return _GridIndex(xy, offsets, counts, empty, empty, empty, "position")
                return None
            if (
                int(cached["version"]) != _GRID_INDEX_VERSION
                or int(cached["source_size"]) != stat.st_size
                or int(cached["source_mtime_ns"]) != stat.st_mtime_ns
                or int(cached["ni"]) != ni
                or int(cached["nj"]) != nj
            ):
                return None
            expected = (ni + 1) * (nj + 1)
            index = _GridIndex(
                xy=np.asarray(cached["xy"], dtype=np.float64),
                z_offsets=np.asarray(cached["z_offsets"], dtype=np.int64),
                z_counts=np.asarray(cached["z_counts"], dtype=np.uint32),
                page_logical_starts=np.asarray(cached["page_logical_starts"], dtype=np.int64),
                page_raw_starts=np.asarray(cached["page_raw_starts"], dtype=np.int64),
                page_sizes=np.asarray(cached["page_sizes"], dtype=np.int64),
                geometry_mode=str(cached["geometry_mode"].item()),
            )
            if (
                index.xy.shape != (expected, 2)
                or index.z_offsets.shape != (expected,)
                or index.z_counts.shape != (expected,)
                or len(index.page_logical_starts) != len(index.page_sizes)
                or len(index.page_raw_starts) != len(index.page_sizes)
            ):
                return None
            return index
    except (OSError, KeyError, ValueError):
        return None


def _save_grid_index(data_path: Path, data_pk: int, ni: int, nj: int, index: _GridIndex) -> None:
    path = _grid_index_path(data_path, data_pk)
    try:
        stat = data_path.stat()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as stream:
            temporary_path = Path(stream.name)
        try:
            np.savez_compressed(
                temporary_path,
                version=np.int32(_GRID_INDEX_VERSION),
                source_size=np.int64(stat.st_size),
                source_mtime_ns=np.int64(stat.st_mtime_ns),
                ni=np.int32(ni),
                nj=np.int32(nj),
                xy=index.xy,
                z_offsets=index.z_offsets,
                z_counts=index.z_counts,
                page_logical_starts=index.page_logical_starts,
                page_raw_starts=index.page_raw_starts,
                page_sizes=index.page_sizes,
                geometry_mode=np.asarray(index.geometry_mode),
            )
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError:
        return

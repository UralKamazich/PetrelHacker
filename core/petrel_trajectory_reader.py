from __future__ import annotations

from pathlib import Path
import struct

import numpy as np

from core.petrel_lz4 import read_petrel_lz4
from core.petrel_property_reader import _read_bxml_dictionary, _read_varint, _tag


def read_petrel_well_shape(data_path: str | Path, data_pk: int) -> tuple[np.ndarray, np.ndarray]:
    raw = read_petrel_lz4(data_path, data_pk, max_bytes=64 * 1024 * 1024)
    return decode_petrel_well_shape(raw)


def decode_petrel_well_shape(raw: bytes) -> tuple[np.ndarray, np.ndarray]:
    names, body_offset = _read_bxml_dictionary(raw)
    raw = _join_bxml_pages(raw, body_offset)
    body_offset = 0
    records_tag = _tag(names.index("records")) + b"\x06\x08"
    records_offset = raw.find(records_tag, body_offset)
    if records_offset < 0:
        raise ValueError("Petrel well shape has no records")
    count, offset = _read_bxml_integer(raw, records_offset + len(records_tag))
    if count < 2:
        raise ValueError(f"Petrel well shape has fewer than two points: {count}")

    item_marker = _tag(names.index("item")) + _tag(names.index("md"))
    vertex_marker = (
        _tag(names.index("vertex"))
        + b"\x03"
        + _tag(names.index("double"))
        + b"\x01\x93\x03"
    )
    trailing_fields = ("inclination", "azimuth", "dx_tn", "dy_tn", "dls")
    trailing_markers = [_tag(names.index(field)) for field in trailing_fields]
    md = np.empty(count, dtype=np.float64)
    points = np.empty((count, 3), dtype=np.float64)
    for index in range(count):
        offset = _consume_marker(raw, offset, item_marker)
        md[index], offset = _read_bxml_number(raw, offset)
        offset = _consume_marker(raw, offset, vertex_marker)
        points[index] = struct.unpack_from("<3d", raw, offset)
        offset += 24
        offset = _consume_terminator(raw, offset, f"vertex at point {index}")
        for marker in trailing_markers:
            offset = _consume_marker(raw, offset, marker)
            _value, offset = _read_bxml_number(raw, offset)
        offset = _consume_terminator(raw, offset, f"record at point {index}")
    return md, points


def read_petrel_trajectory(data_path: str | Path, data_pk: int) -> tuple[float, np.ndarray]:
    raw = read_petrel_lz4(data_path, data_pk, max_bytes=64 * 1024 * 1024)
    names, body_offset = _read_bxml_dictionary(raw)
    first_md = _read_first_md(raw, names, body_offset)
    records_tag = _tag(names.index("records")) + b"\x06\x08"
    records_offset = raw.find(records_tag, body_offset)
    if records_offset < 0:
        raise ValueError("Petrel trajectory has no records")
    count, offset = _read_bxml_integer(raw, records_offset + len(records_tag))
    if count < 2:
        raise ValueError(f"Petrel trajectory has fewer than two points: {count}")

    item_marker = _tag(names.index("item")) + _tag(names.index("x")) + b"\x93"
    y_marker = _tag(names.index("y")) + b"\x93"
    z_marker = _tag(names.index("z"))
    points = np.empty((count, 3), dtype=np.float64)
    for index in range(count):
        offset = _consume_marker(raw, offset, item_marker)
        points[index, 0] = struct.unpack_from("<d", raw, offset)[0]
        offset += 8
        offset = _consume_marker(raw, offset, y_marker)
        points[index, 1] = struct.unpack_from("<d", raw, offset)[0]
        offset += 8
        offset = _consume_marker(raw, offset, z_marker)
        points[index, 2], offset = _read_bxml_number(raw, offset)
        if offset >= len(raw) or raw[offset] != 0x01:
            raise ValueError(f"Invalid Petrel trajectory record terminator at point {index}")
        offset += 1
    return float(first_md), points


def read_petrel_trajectory_point_count(data_path: str | Path, data_pk: int) -> int | None:
    try:
        raw = read_petrel_lz4(data_path, data_pk, max_bytes=64 * 1024 * 1024)
        names, body_offset = _read_bxml_dictionary(raw)
        records_tag = _tag(names.index("records")) + b"\x06\x08"
        records_offset = raw.find(records_tag, body_offset)
        if records_offset < 0:
            return None
        count, _offset = _read_bxml_integer(raw, records_offset + len(records_tag))
        return count
    except (EOFError, IndexError, OSError, ValueError):
        return None


def _read_first_md(raw: bytes, names: list[str], body_offset: int) -> float:
    marker = _tag(names.index("first_md"))
    marker_offset = raw.find(marker, body_offset)
    if marker_offset < 0:
        return 0.0
    value, _offset = _read_bxml_number(raw, marker_offset + len(marker))
    return float(value)


def _read_bxml_number(data: bytes, offset: int) -> tuple[float | int, int]:
    token = data[offset]
    offset += 1
    if token in {0x81, 0x83, 0x85, 0x87}:
        return (token - 0x81) // 2, offset
    formats = {
        0x88: "<B",
        0x89: "<b",
        0x8A: "<H",
        0x8B: "<h",
        0x8C: "<I",
        0x8D: "<i",
        0x91: "<f",
        0x93: "<d",
    }
    fmt = formats.get(token)
    if fmt is None:
        raise ValueError(f"Unsupported Petrel BXML number token: 0x{token:02x}")
    size = struct.calcsize(fmt)
    return struct.unpack_from(fmt, data, offset)[0], offset + size


def _read_bxml_integer(data: bytes, offset: int) -> tuple[int, int]:
    value, offset = _read_bxml_number(data, offset)
    integer = int(value)
    if integer != value:
        raise ValueError(f"Expected Petrel integer, got {value}")
    return integer, offset


def _consume_marker(data: bytes, offset: int, marker: bytes) -> int:
    for expected in marker:
        if offset >= len(data):
            raise EOFError("Petrel trajectory ended inside a record marker")
        if data[offset] != expected and data[offset] == 0xA0:
            _segment_size, offset = _read_varint(data, offset + 1)
        if offset >= len(data) or data[offset] != expected:
            raise ValueError(f"Invalid Petrel trajectory record marker at offset {offset}")
        offset += 1
    return offset


def _consume_terminator(data: bytes, offset: int, label: str) -> int:
    offset = _skip_segment_frames(data, offset)
    if offset >= len(data) or data[offset] != 0x01:
        raise ValueError(f"Invalid Petrel {label} terminator at offset {offset}")
    return offset + 1


def _skip_segment_frames(data: bytes, offset: int) -> int:
    while offset < len(data) and data[offset] == 0xA0:
        _segment_size, offset = _read_varint(data, offset + 1)
    return offset


def _join_bxml_pages(data: bytes, body_offset: int) -> bytes:
    cursor = body_offset - 1
    output = bytearray()
    while cursor < len(data):
        if data[cursor] == 0xA0:
            try:
                size, payload_start = _read_varint(data, cursor + 1)
            except (IndexError, ValueError):
                output.append(data[cursor])
                cursor += 1
                continue
            payload_end = payload_start + size
            if size > 0 and payload_end <= len(data):
                output.extend(data[payload_start:payload_end])
                cursor = payload_end
                continue
        if data[cursor] == 0xA1:
            extension_end = _dictionary_extension_end(data, cursor)
            if extension_end is not None:
                cursor = extension_end
                continue
        output.append(data[cursor])
        cursor += 1
    return bytes(output)


def _dictionary_extension_end(data: bytes, offset: int) -> int | None:
    cursor = offset
    count = 0
    while cursor + 2 <= len(data) and data[cursor] == 0xA1:
        size = data[cursor + 1]
        end = cursor + 2 + size
        if not size or end > len(data):
            return None
        name = data[cursor + 2 : end]
        if not all(0x20 <= value < 0x7F for value in name):
            return None
        cursor = end
        count += 1
    if not count or cursor >= len(data) or data[cursor] != 0xA0:
        return None
    return cursor

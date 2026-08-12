from __future__ import annotations

from pathlib import Path
import struct

import numpy as np

from core.petrel_lz4 import read_petrel_lz4
from core.petrel_property_reader import _read_bxml_dictionary, _read_varint, _tag


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

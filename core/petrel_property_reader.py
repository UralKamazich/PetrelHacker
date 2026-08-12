from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

import numpy as np

from core.petrel_lz4 import PetrelLz4Blob, read_first_petrel_lz4_block


@dataclass(frozen=True)
class PetrelPropertyLayout:
    data_pk: int
    property_type: str
    ni: int
    nj: int
    nk: int
    element_count: int
    value_offset: int
    page_capacity: int
    page_stride: int
    item_size: int

    @property
    def dtype(self) -> np.dtype:
        return np.dtype("<f4") if self.property_type == "FloatProperty" else np.dtype("u1")


class PetrelPropertyReader:
    def __init__(self, data_path: str | Path, data_pk: int, property_type: str) -> None:
        self.blob = PetrelLz4Blob(data_path, data_pk)
        self.layout = _parse_layout(self.blob, int(data_pk), property_type)

    def get_value(self, i: int, j: int, k: int):
        flat_index = self._flat_index(i, j, k)
        page_index, within_page = divmod(flat_index, self.layout.page_capacity)
        page_count = min(
            self.layout.page_capacity,
            self.layout.element_count - page_index * self.layout.page_capacity,
        )
        page = self._read_page(page_index, page_count)
        value = np.frombuffer(page, dtype=self.layout.dtype, count=page_count)[within_page]
        return _clean_value(value, self.layout.property_type)

    def get_column_values(self, i: int, j: int) -> np.ndarray:
        return self.get_columns_values({(i, j)})[(i, j)]

    def get_columns_values(self, columns: set[tuple[int, int]]) -> dict[tuple[int, int], np.ndarray]:
        ordered = sorted(columns)
        if not ordered:
            return {}
        for i, j in ordered:
            self._flat_index(i, j, 0)
        column_offsets = np.asarray([j * self.layout.ni + i for i, j in ordered], dtype=np.int64)
        output = np.empty((len(ordered), self.layout.nk), dtype=self.layout.dtype)

        stream = _DecompressedStream(self.blob)
        stream.skip(self.layout.value_offset)
        remaining = self.layout.element_count
        flat_start = 0
        page_index = 0
        while remaining:
            count = min(self.layout.page_capacity, remaining)
            framed_page = stream.read_exact(count * self.layout.item_size + 4)
            page_bytes = _strip_binary_segment_frame(framed_page, count * self.layout.item_size)
            page = np.frombuffer(
                page_bytes,
                dtype=self.layout.dtype,
                count=count,
            )
            flat_end = flat_start + count
            first_k = max(0, flat_start // (self.layout.ni * self.layout.nj) - 1)
            last_k = min(self.layout.nk, (flat_end // (self.layout.ni * self.layout.nj)) + 2)
            for column_index, offset in enumerate(column_offsets):
                for k in range(first_k, last_k):
                    flat_index = int(k * self.layout.ni * self.layout.nj + offset)
                    if flat_start <= flat_index < flat_end:
                        output[column_index, k] = page[flat_index - flat_start]
            remaining -= count
            flat_start = flat_end
            page_index += 1
            if remaining:
                stream.skip(self.layout.page_stride - len(framed_page))
        return {
            column: _clean_values(output[index], self.layout.property_type)
            for index, column in enumerate(ordered)
        }

    def _flat_index(self, i: int, j: int, k: int) -> int:
        if not (0 <= i < self.layout.ni and 0 <= j < self.layout.nj and 0 <= k < self.layout.nk):
            raise IndexError(
                f"Petrel cell index out of bounds: i={i}, j={j}, k={k}; "
                f"shape={self.layout.ni}/{self.layout.nj}/{self.layout.nk}"
            )
        return k * self.layout.nj * self.layout.ni + j * self.layout.ni + i

    def _read_page(self, page_index: int, count: int) -> bytes:
        offset = self.layout.value_offset + page_index * self.layout.page_stride
        raw_size = count * self.layout.item_size
        framed = self.blob.read_range(offset, raw_size + 4)
        return _strip_binary_segment_frame(framed, raw_size)


class _DecompressedStream:
    def __init__(self, blob: PetrelLz4Blob) -> None:
        self._blocks = iter(blob.iter_blocks())
        self._buffer = memoryview(b"")
        self._offset = 0

    def read_exact(self, size: int) -> bytes:
        chunks: list[bytes] = []
        pending = size
        while pending:
            self._ensure_data()
            count = min(pending, len(self._buffer) - self._offset)
            chunks.append(bytes(self._buffer[self._offset : self._offset + count]))
            self._offset += count
            pending -= count
        return b"".join(chunks)

    def skip(self, size: int) -> None:
        pending = size
        while pending:
            self._ensure_data()
            count = min(pending, len(self._buffer) - self._offset)
            self._offset += count
            pending -= count

    def _ensure_data(self) -> None:
        if self._offset < len(self._buffer):
            return
        self._buffer = memoryview(next(self._blocks))
        self._offset = 0


def _parse_layout(blob: PetrelLz4Blob, data_pk: int, property_type: str) -> PetrelPropertyLayout:
    first_block = blob.read_range(0, min(blob.uncompressed_size, 1024 * 1024))
    if property_type not in {"FloatProperty", "IntProperty"}:
        raise ValueError(f"Unsupported native Petrel property type: {property_type}")
    names, body_offset = _read_bxml_dictionary(first_block)
    ni, nj, nk = _parse_property_shape_data(first_block, names, body_offset)
    element_count = ni * nj * nk

    if property_type == "FloatProperty":
        try:
            primitive_tag = _tag(names.index("float"))
        except ValueError as exc:
            raise ValueError("Petrel FloatProperty has no float data tag") from exc
        marker = primitive_tag + b"\x01\x91"
        marker_pos = first_block.find(marker, body_offset)
        if marker_pos < 0:
            raise ValueError("Cannot locate Petrel float pages in BXML")
        page_capacity, value_offset = _read_varint(first_block, marker_pos + len(marker))
        page_stride = page_capacity * 4 + 22
        item_size = 4
    else:
        try:
            page_tag = _tag(names.index("page"))
        except ValueError as exc:
            raise ValueError("Petrel IntProperty has no page data tag") from exc
        marker_pos = first_block.find(page_tag, body_offset)
        if marker_pos < 0:
            raise ValueError("Cannot locate Petrel integer pages in BXML")
        page_capacity = 512 * 1024
        value_offset = marker_pos + 11
        page_stride = page_capacity + 19
        item_size = 1

    return PetrelPropertyLayout(
        data_pk=data_pk,
        property_type=property_type,
        ni=ni,
        nj=nj,
        nk=nk,
        element_count=element_count,
        value_offset=value_offset,
        page_capacity=page_capacity,
        page_stride=page_stride,
        item_size=item_size,
    )


def read_petrel_property_shape(data_path: str | Path, data_pk: int) -> tuple[int, int, int]:
    first_block = read_first_petrel_lz4_block(data_path, data_pk)
    names, body_offset = _read_bxml_dictionary(first_block)
    return _parse_property_shape_data(first_block, names, body_offset)


def _parse_property_shape_data(
    first_block: bytes,
    names: list[str],
    body_offset: int,
) -> tuple[int, int, int]:
    try:
        cell_size_tag = _tag(names.index("cell_size"))
        int_tag = _tag(names.index("int"))
    except ValueError as exc:
        raise ValueError("Petrel property has no readable cell_size metadata") from exc
    shape_marker = cell_size_tag + b"\x03" + int_tag + b"\x01\x8d\x03"
    shape_pos = first_block.find(shape_marker, body_offset)
    if shape_pos < 0:
        raise ValueError("Cannot locate Petrel property dimensions in BXML")
    ni, nj, nk = struct.unpack_from("<III", first_block, shape_pos + len(shape_marker))
    return ni, nj, nk


def _read_bxml_dictionary(data: bytes) -> tuple[list[str], int]:
    if not data.startswith(b"BXML\x01"):
        raise ValueError("Unsupported Petrel BXML header")
    names: list[str] = []
    offset = 5
    while offset < len(data) and data[offset] == 0xA1:
        size = data[offset + 1]
        start = offset + 2
        names.append(data[start : start + size].decode("utf-8"))
        offset = start + size
    if offset >= len(data) or data[offset] != 0xA0:
        raise ValueError("Invalid Petrel BXML name table")
    return names, offset + 1


def _tag(index: int) -> bytes:
    value = index * 2
    if value > 0xFF:
        raise ValueError("Large Petrel BXML name tables are not supported")
    return bytes((0x42, value))


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("Invalid Petrel BXML variable integer")


def _strip_binary_segment_frame(data: bytes, expected_size: int) -> bytes:
    if len(data) == expected_size:
        return data
    if len(data) != expected_size + 4:
        raise ValueError(
            f"Unexpected Petrel BXML binary segment size: {len(data)}; expected {expected_size + 4}"
        )
    marker_offset = data.find(b"\xa0")
    while marker_offset >= 0:
        try:
            remaining_size, payload_offset = _read_varint(data, marker_offset + 1)
        except (IndexError, ValueError):
            pass
        else:
            if payload_offset + remaining_size == len(data):
                output = data[:marker_offset] + data[payload_offset:]
                if len(output) == expected_size:
                    return output
        marker_offset = data.find(b"\xa0", marker_offset + 1)
    raise ValueError("Cannot locate Petrel BXML binary segment frame")


def _clean_value(value, property_type: str):
    if property_type == "FloatProperty":
        number = float(value)
        return number if np.isfinite(number) and abs(number) < 3.4e38 else ""
    integer = int(value)
    return "" if integer == 255 else integer


def _clean_values(values: np.ndarray, property_type: str) -> np.ndarray:
    if property_type == "FloatProperty":
        output = np.asarray(values, dtype=np.float32).copy()
        output[~np.isfinite(output) | (np.abs(output) >= 3.4e38)] = np.nan
        return output
    output = np.asarray(values, dtype=np.float64)
    output[output == 255] = np.nan
    return output

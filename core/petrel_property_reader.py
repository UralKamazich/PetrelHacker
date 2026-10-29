from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

import numpy as np

from core.petrel_lz4 import PetrelLz4Blob, read_first_petrel_lz4_block


_BYTE_POPCOUNT = np.asarray([value.bit_count() for value in range(256)], dtype=np.uint8)


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
    value_count: int
    defined_mask_offset: int | None = None
    defined_mask_size: int = 0
    defined_mask_storage_size: int = 0

    @property
    def dtype(self) -> np.dtype:
        return np.dtype("<f4") if self.property_type == "FloatProperty" else np.dtype("u1")


class PetrelPropertyReader:
    def __init__(self, data_path: str | Path, data_pk: int, property_type: str) -> None:
        self.blob = PetrelLz4Blob(data_path, data_pk)
        self.layout = _parse_layout(self.blob, int(data_pk), property_type)
        if self.layout.defined_mask_offset is not None:
            mask_storage = self.blob.read_range(
                self.layout.defined_mask_offset,
                self.layout.defined_mask_storage_size,
            )
            self._defined_mask = _strip_binary_segment_frame(
                mask_storage,
                self.layout.defined_mask_size,
            )
        else:
            self._defined_mask = None
        self._mask_block_size = 4096
        self._mask_block_prefix = self._build_mask_block_prefix()

    def get_value(self, i: int, j: int, k: int):
        flat_index = self._flat_index(i, j, k)
        value_index = self._stored_value_index(flat_index)
        if value_index is None:
            return ""
        page_index, within_page = divmod(value_index, self.layout.page_capacity)
        page_count = min(
            self.layout.page_capacity,
            self.layout.value_count - page_index * self.layout.page_capacity,
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

        if self._defined_mask is not None:
            output.fill(np.nan if self.layout.property_type == "FloatProperty" else 255)
            targets: dict[int, list[tuple[int, int]]] = {}
            layer_size = self.layout.ni * self.layout.nj
            for column_index, column_offset in enumerate(column_offsets):
                for k in range(self.layout.nk):
                    value_index = self._stored_value_index(int(k * layer_size + column_offset))
                    if value_index is not None:
                        targets.setdefault(value_index, []).append((column_index, k))
            self._read_sparse_targets(output, targets)
            return {
                column: _clean_values(output[index], self.layout.property_type)
                for index, column in enumerate(ordered)
            }

        stream = _DecompressedStream(self.blob)
        stream.skip(self.layout.value_offset)
        remaining = self.layout.value_count
        flat_start = 0
        page_index = 0
        while remaining:
            count = min(self.layout.page_capacity, remaining)
            framed_page = stream.read_exact(count * self.layout.item_size + 4)
            page_bytes = _strip_binary_segment_frame(
                framed_page,
                count * self.layout.item_size,
                pad_byte=255 if self.layout.property_type == "IntProperty" else None,
            )
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

    def _read_sparse_targets(
        self,
        output: np.ndarray,
        targets: dict[int, list[tuple[int, int]]],
    ) -> None:
        if not targets:
            return
        ordered_targets = sorted(targets)
        target_cursor = 0
        stream = _DecompressedStream(self.blob)
        stream.skip(self.layout.value_offset)
        remaining = self.layout.value_count
        value_start = 0
        while remaining and target_cursor < len(ordered_targets):
            count = min(self.layout.page_capacity, remaining)
            framed_page = stream.read_exact(count * self.layout.item_size + 4)
            page_bytes = _strip_binary_segment_frame(
                framed_page,
                count * self.layout.item_size,
                pad_byte=255 if self.layout.property_type == "IntProperty" else None,
            )
            page = np.frombuffer(page_bytes, dtype=self.layout.dtype, count=count)
            value_end = value_start + count
            while target_cursor < len(ordered_targets):
                value_index = ordered_targets[target_cursor]
                if value_index >= value_end:
                    break
                for column_index, k in targets[value_index]:
                    output[column_index, k] = page[value_index - value_start]
                target_cursor += 1
            remaining -= count
            value_start = value_end
            if remaining and target_cursor < len(ordered_targets):
                stream.skip(self.layout.page_stride - len(framed_page))

    def _build_mask_block_prefix(self) -> np.ndarray | None:
        if self._defined_mask is None:
            return None
        values = np.frombuffer(self._defined_mask, dtype=np.uint8)
        counts = _BYTE_POPCOUNT[values]
        starts = np.arange(0, len(counts), self._mask_block_size)
        block_totals = np.add.reduceat(counts, starts)
        return np.concatenate((np.asarray([0], dtype=np.int64), np.cumsum(block_totals)))

    def _stored_value_index(self, flat_index: int) -> int | None:
        if self._defined_mask is None:
            return flat_index
        byte_index, bit_index = divmod(flat_index, 8)
        byte_value = self._defined_mask[byte_index]
        if not byte_value & (1 << bit_index):
            return None
        block_index, within_block = divmod(byte_index, self._mask_block_size)
        block_start = byte_index - within_block
        rank = int(self._mask_block_prefix[block_index])
        if byte_index > block_start:
            block = np.frombuffer(self._defined_mask[block_start:byte_index], dtype=np.uint8)
            rank += int(_BYTE_POPCOUNT[block].sum())
        rank += (byte_value & ((1 << bit_index) - 1)).bit_count()
        return rank

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
        return _strip_binary_segment_frame(
            framed,
            raw_size,
            pad_byte=255 if self.layout.property_type == "IntProperty" else None,
        )


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
    header_size = min(
        blob.uncompressed_size,
        max(len(first_block), (element_count + 7) // 8 + 2 * 1024 * 1024),
    )
    if header_size > len(first_block):
        first_block = blob.read_range(0, header_size)

    value_count = element_count
    defined_mask_offset = None
    defined_mask_size = 0
    defined_mask_storage_size = 0
    needs_extension = (
        property_type == "FloatProperty" and "float" not in names
    ) or (
        property_type == "IntProperty" and "page" not in names
    )
    extension_names = _read_property_dictionary_extension(first_block, body_offset) if needs_extension else []
    names.extend(extension_names)
    if extension_names and "no_elements" in names and "bitmask" in names:
        no_elements_tag = _tag(names.index("no_elements"))
        no_elements_pos = first_block.find(no_elements_tag + b"\x8d", body_offset)
        if no_elements_pos >= 0:
            value_count = struct.unpack_from(
                "<I", first_block, no_elements_pos + len(no_elements_tag) + 1
            )[0]
        bitmask_tag = _tag(names.index("bitmask"))
        bitmask_marker = bitmask_tag + b"\x06\x08\x88\xff\xa2"
        bitmask_pos = first_block.find(bitmask_marker, body_offset)
        if bitmask_pos >= 0:
            size_offset = bitmask_pos + len(bitmask_marker)
            defined_mask_size = struct.unpack_from("<I", first_block, size_offset)[0]
            defined_mask_offset = size_offset + 4
            extension_offset = first_block.find(b"\xa1\x10is_undef_checked", defined_mask_offset)
            if extension_offset >= 0:
                defined_mask_storage_size = extension_offset - defined_mask_offset

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
        value_count=value_count,
        defined_mask_offset=defined_mask_offset,
        defined_mask_size=defined_mask_size,
        defined_mask_storage_size=defined_mask_storage_size,
    )


def _read_property_dictionary_extension(data: bytes, body_offset: int) -> list[str]:
    marker = b"\xa1\x10is_undef_checked"
    offset = data.find(marker, body_offset)
    if offset < 0:
        return []
    names: list[str] = []
    while offset + 2 <= len(data) and data[offset] == 0xA1:
        size = data[offset + 1]
        start = offset + 2
        end = start + size
        if size == 0 or end > len(data):
            return []
        try:
            names.append(data[start:end].decode("ascii"))
        except UnicodeDecodeError:
            return []
        offset = end
    return names if offset < len(data) and data[offset] == 0xA0 else []


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


def _strip_binary_segment_frame(
    data: bytes,
    expected_size: int,
    *,
    pad_byte: int | None = None,
) -> bytes:
    if len(data) == expected_size:
        return data
    if len(data) < expected_size or len(data) - expected_size > 10:
        raise ValueError(
            f"Unexpected Petrel BXML binary segment size: {len(data)}; expected {expected_size} "
            "plus a short page frame"
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
            payload_end = payload_offset + remaining_size
            if payload_end < len(data) and data[payload_end] == 0xA0:
                output = data[:marker_offset] + data[payload_offset:payload_end]
                missing = expected_size - len(output)
                if pad_byte is not None and 0 <= missing <= 16:
                    return output + bytes((pad_byte,)) * missing
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

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import struct

import lz4.block


PETREL_LZ4_MAGIC = b"LZ4\x01"
PETREL_LZ4_BLOCK_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True)
class PetrelLz4Block:
    compressed_offset: int
    compressed_size: int
    uncompressed_offset: int
    uncompressed_size: int


class PetrelLz4Blob:
    def __init__(self, data_path: str | Path, data_pk: int) -> None:
        self.data_path = Path(data_path)
        self.data_pk = int(data_pk)
        self._parts = _blob_part_locations(self.data_path, self.data_pk)
        self.blocks = self._index_blocks()
        self.uncompressed_size = sum(block.uncompressed_size for block in self.blocks)

    def iter_blocks(self) -> Iterator[bytes]:
        for block in self.blocks:
            yield self._decompress_block(block)

    def read_range(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > self.uncompressed_size:
            raise IndexError(
                f"Petrel decompressed range is out of bounds: offset={offset}, size={size}, "
                f"total={self.uncompressed_size}"
            )
        if size == 0:
            return b""
        block_offsets = [block.uncompressed_offset for block in self.blocks]
        first_index = bisect_right(block_offsets, offset) - 1
        last_index = bisect_right(block_offsets, offset + size - 1) - 1
        output = bytearray()
        for index in range(first_index, last_index + 1):
            block = self.blocks[index]
            raw = self._decompress_block(block)
            start = max(offset, block.uncompressed_offset) - block.uncompressed_offset
            end = min(offset + size, block.uncompressed_offset + len(raw)) - block.uncompressed_offset
            output.extend(raw[start:end])
        return bytes(output)

    def _index_blocks(self) -> list[PetrelLz4Block]:
        with sqlite3.connect(f"file:{self.data_path}?mode=ro", uri=True) as connection:
            reader = _MultipartBlobReader(connection, self._parts)
            magic = reader.read_exact(len(PETREL_LZ4_MAGIC))
            if magic != PETREL_LZ4_MAGIC:
                raise ValueError(f"Unsupported Petrel blob compression header: {magic!r}")
            blocks: list[PetrelLz4Block] = []
            uncompressed_offset = 0
            while reader.remaining:
                compressed_size, _checksum = struct.unpack("<II", reader.read_exact(8))
                if compressed_size <= 0 or compressed_size > reader.remaining:
                    raise ValueError(
                        f"Invalid Petrel LZ4 block size {compressed_size}; {reader.remaining} bytes remain"
                    )
                compressed_offset = reader.position
                compressed = reader.read_exact(compressed_size)
                raw = _decompress(compressed, self.data_pk)
                blocks.append(
                    PetrelLz4Block(
                        compressed_offset=compressed_offset,
                        compressed_size=compressed_size,
                        uncompressed_offset=uncompressed_offset,
                        uncompressed_size=len(raw),
                    )
                )
                uncompressed_offset += len(raw)
            reader.close()
            return blocks

    def _decompress_block(self, block: PetrelLz4Block) -> bytes:
        compressed = _read_blob_range(self.data_path, self._parts, block.compressed_offset, block.compressed_size)
        return _decompress(compressed, self.data_pk)


def iter_petrel_lz4_blocks(data_path: str | Path, data_pk: int) -> Iterator[bytes]:
    """Yield decompressed blocks from a Petrel Data.ptd object."""
    yield from PetrelLz4Blob(data_path, data_pk).iter_blocks()


def read_petrel_lz4(data_path: str | Path, data_pk: int, *, max_bytes: int | None = None) -> bytes:
    output = bytearray()
    for block in iter_petrel_lz4_blocks(data_path, data_pk):
        output.extend(block)
        if max_bytes is not None and len(output) > max_bytes:
            raise ValueError(f"Decompressed Petrel object exceeds the {max_bytes}-byte limit")
    return bytes(output)


class _MultipartBlobReader:
    def __init__(self, connection: sqlite3.Connection, rows: list[tuple[int, int]]) -> None:
        self._connection = connection
        self._rows = [(int(rowid), int(size)) for rowid, size in rows]
        self._row_index = 0
        self._blob: sqlite3.Blob | None = None
        self._part_remaining = 0
        self.remaining = sum(size for _rowid, size in self._rows)
        self.position = 0

    def read_exact(self, size: int) -> bytes:
        if size < 0 or size > self.remaining:
            raise EOFError(f"Requested {size} bytes with only {self.remaining} bytes remaining")
        chunks: list[bytes] = []
        pending = size
        while pending:
            self._open_next_part_if_needed()
            assert self._blob is not None
            chunk_size = min(pending, self._part_remaining)
            chunk = self._blob.read(chunk_size)
            if len(chunk) != chunk_size:
                raise EOFError("Unexpected end of Petrel blob part")
            chunks.append(chunk)
            pending -= chunk_size
            self._part_remaining -= chunk_size
            self.remaining -= chunk_size
            self.position += chunk_size
        return b"".join(chunks)

    def close(self) -> None:
        if self._blob is not None:
            self._blob.close()
            self._blob = None

    def _open_next_part_if_needed(self) -> None:
        if self._blob is not None and self._part_remaining:
            return
        if self._blob is not None:
            self._blob.close()
            self._blob = None
        if self._row_index >= len(self._rows):
            raise EOFError("No Petrel blob parts remain")
        rowid, size = self._rows[self._row_index]
        self._row_index += 1
        self._blob = self._connection.blobopen("blob_parts", "blob_data", rowid, readonly=True)
        self._part_remaining = size


def _blob_part_locations(data_path: Path, data_pk: int) -> list[tuple[int, int]]:
    with sqlite3.connect(f"file:{data_path}?mode=ro", uri=True) as connection:
        rows = [
            (int(rowid), int(size))
            for rowid, size in connection.execute(
                "select rowid, length(blob_data) from blob_parts where data_fk = ? order by part",
                (int(data_pk),),
            )
        ]
    if not rows:
        raise ValueError(f"Petrel object has no blob parts: data_pk={data_pk}")
    return rows


def _read_blob_range(
    data_path: Path,
    parts: list[tuple[int, int]],
    offset: int,
    size: int,
) -> bytes:
    output = bytearray()
    part_start = 0
    pending = size
    with sqlite3.connect(f"file:{data_path}?mode=ro", uri=True) as connection:
        for rowid, part_size in parts:
            part_end = part_start + part_size
            if offset < part_end and pending:
                local_offset = max(0, offset - part_start)
                read_size = min(pending, part_size - local_offset)
                with connection.blobopen("blob_parts", "blob_data", rowid, readonly=True) as blob:
                    blob.seek(local_offset)
                    output.extend(blob.read(read_size))
                offset += read_size
                pending -= read_size
            part_start = part_end
            if not pending:
                break
    if pending:
        raise EOFError(f"Petrel blob range ended with {pending} unread bytes")
    return bytes(output)


def _decompress(compressed: bytes, data_pk: int) -> bytes:
    try:
        return lz4.block.decompress(compressed, uncompressed_size=PETREL_LZ4_BLOCK_SIZE)
    except lz4.block.LZ4BlockError as exc:
        raise ValueError(f"Cannot decompress Petrel LZ4 block for data_pk={data_pk}") from exc

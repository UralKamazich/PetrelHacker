from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
import struct


LZ4_BLOCK_MAGIC = b"LZ4\x01"
BXML_MAGIC = b"BXML\x01"
UUID_PATTERN = re.compile(
    rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
ASCII_TEXT_PATTERN = re.compile(rb"[ -~]{4,}")


@dataclass(frozen=True)
class PetrelProjectPaths:
    source_path: Path
    project_file: Path | None
    project_folder: Path
    data_path: Path
    model_path: Path | None


@dataclass(frozen=True)
class PetrelStoredObject:
    data_pk: int
    droid: str
    name: str
    version: int
    blob_type: str
    time_stamp: str | None
    part_count: int
    stored_bytes: int

    @property
    def uuid(self) -> str | None:
        match = UUID_PATTERN.search(self.droid.encode("ascii", errors="ignore"))
        return match.group().decode("ascii").lower() if match else None

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["uuid"] = self.uuid
        return result


@dataclass(frozen=True)
class PetrelBxmlProfile:
    version: int | None
    symbols: tuple[str, ...]
    payload_offset: int | None
    text_values: tuple[str, ...]
    referenced_uuids: tuple[str, ...]
    decoded_prefix_bytes: int
    header_hex: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PetrelObjectDiagnostics:
    data_pk: int
    storage_encoding: str
    stored_bytes: int
    frame_count: int
    decoded_bytes: int
    stored_sha256: str
    raw_prefix_hex: str
    bxml: PetrelBxmlProfile | None

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["bxml"] = self.bxml.as_dict() if self.bxml else None
        return result


class PetrelProjectReader:
    """Read-only inspector for a native Petrel ``.pet``/``.ptd`` project.

    Petrel stores large project objects in ``Data.ptd``, an SQLite database.
    Each object is split into numbered BLOB parts and contains one or more
    custom LZ4 blocks. The decoded byte stream usually starts with Petrel BXML.

    This class deliberately does not register itself as a production model
    reader yet. It exposes the complete storage catalogue and lossless decoded
    object streams so type-specific decoders can be added without changing the
    working RESQML and Rescue paths.
    """

    def __init__(self, path: str | Path):
        self.paths = resolve_petrel_project_paths(path)
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> PetrelProjectReader:
        self.open()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def open(self) -> None:
        if self._connection is not None:
            return
        uri = self.paths.data_path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        _validate_store_schema(connection, self.paths.data_path)
        self._connection = connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def list_objects(self) -> list[PetrelStoredObject]:
        rows = self._db.execute(
            """
            SELECT d.data_pk, d.droid, d.name, d.version,
                   COALESCE(d.blob_type, '') AS blob_type, d.time_stamp,
                   COUNT(p.part) AS part_count,
                   COALESCE(SUM(LENGTH(p.blob_data)), 0) AS stored_bytes
            FROM data AS d
            LEFT JOIN blob_parts AS p ON p.data_fk = d.data_pk
            GROUP BY d.data_pk
            ORDER BY d.data_pk
            """
        )
        return [
            PetrelStoredObject(
                data_pk=int(row["data_pk"]),
                droid=str(row["droid"]),
                name=str(row["name"]),
                version=int(row["version"]),
                blob_type=str(row["blob_type"]),
                time_stamp=str(row["time_stamp"]) if row["time_stamp"] is not None else None,
                part_count=int(row["part_count"]),
                stored_bytes=int(row["stored_bytes"]),
            )
            for row in rows
        ]

    def object_type_counts(self) -> dict[str, int]:
        rows = self._db.execute(
            """
            SELECT COALESCE(blob_type, '') AS blob_type, COUNT(*) AS object_count
            FROM data
            GROUP BY blob_type
            ORDER BY object_count DESC, blob_type
            """
        )
        return {str(row["blob_type"]): int(row["object_count"]) for row in rows}

    def iter_stored_parts(self, data_pk: int) -> Iterator[bytes]:
        cursor = self._db.execute(
            "SELECT blob_data FROM blob_parts WHERE data_fk = ? ORDER BY part",
            (int(data_pk),),
        )
        found = False
        for row in cursor:
            found = True
            yield bytes(row[0])
        if not found:
            raise KeyError(f"Petrel object has no BLOB parts: {data_pk}")

    def read_stored_object(self, data_pk: int) -> bytes:
        return b"".join(self.iter_stored_parts(data_pk))

    def iter_decoded_blocks(self, data_pk: int) -> Iterator[bytes]:
        yield from iter_decoded_lz4_parts(
            self.iter_stored_parts(data_pk),
            source_name=f"object {data_pk}",
        )

    def read_decoded_prefix(self, data_pk: int, max_bytes: int = 1_048_576) -> bytes:
        if max_bytes <= 0:
            return b""
        result = bytearray()
        for block in self.iter_decoded_blocks(data_pk):
            remaining = max_bytes - len(result)
            result.extend(block[:remaining])
            if len(result) >= max_bytes:
                break
        return bytes(result)

    def write_decoded_object(self, data_pk: int, destination: str | Path) -> int:
        output_path = Path(destination)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with output_path.open("wb") as stream:
            for block in self.iter_decoded_blocks(data_pk):
                stream.write(block)
                written += len(block)
        return written

    def inspect_object(self, data_pk: int, *, bxml_prefix_bytes: int = 1_048_576) -> PetrelObjectDiagnostics:
        digest = sha256()
        stored_bytes = 0
        raw_prefix = bytearray()
        for part in self.iter_stored_parts(data_pk):
            digest.update(part)
            stored_bytes += len(part)
            if len(raw_prefix) < 256:
                raw_prefix.extend(part[: 256 - len(raw_prefix)])

        if not raw_prefix.startswith(LZ4_BLOCK_MAGIC):
            return PetrelObjectDiagnostics(
                data_pk=int(data_pk),
                storage_encoding="raw",
                stored_bytes=stored_bytes,
                frame_count=0,
                decoded_bytes=0,
                stored_sha256=digest.hexdigest(),
                raw_prefix_hex=bytes(raw_prefix).hex(),
                bxml=None,
            )

        frame_count = 0
        decoded_bytes = 0
        prefix = bytearray()
        for block in self.iter_decoded_blocks(data_pk):
            frame_count += 1
            decoded_bytes += len(block)
            if len(prefix) < bxml_prefix_bytes:
                prefix.extend(block[: bxml_prefix_bytes - len(prefix)])

        profile = profile_bxml(bytes(prefix)) if prefix.startswith(BXML_MAGIC) else None
        return PetrelObjectDiagnostics(
            data_pk=int(data_pk),
            storage_encoding="petrel-lz4-bxml" if profile else "petrel-lz4",
            stored_bytes=stored_bytes,
            frame_count=frame_count,
            decoded_bytes=decoded_bytes,
            stored_sha256=digest.hexdigest(),
            raw_prefix_hex=bytes(raw_prefix).hex(),
            bxml=profile,
        )

    @property
    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Petrel project reader is not open")
        return self._connection


def resolve_petrel_project_paths(path: str | Path) -> PetrelProjectPaths:
    source = Path(path).expanduser().resolve()
    project_file: Path | None = None

    if source.is_file() and source.suffix.lower() == ".pet":
        project_file = source
        project_folder = source.with_suffix(".ptd")
    elif source.is_dir() and source.suffix.lower() == ".ptd":
        project_folder = source
        sibling = source.with_suffix(".pet")
        project_file = sibling if sibling.is_file() else None
    elif source.is_file() and source.name.lower() == "data.ptd":
        project_folder = source.parent
        sibling = project_folder.with_suffix(".pet")
        project_file = sibling if sibling.is_file() else None
    elif source.is_dir():
        pet_files = sorted(source.glob("*.pet"))
        ptd_folders = sorted(item for item in source.glob("*.ptd") if item.is_dir())
        if len(pet_files) == 1:
            project_file = pet_files[0]
            project_folder = project_file.with_suffix(".ptd")
        elif len(ptd_folders) == 1:
            project_folder = ptd_folders[0]
            sibling = project_folder.with_suffix(".pet")
            project_file = sibling if sibling.is_file() else None
        else:
            raise ValueError(f"Expected one Petrel .pet project or .ptd folder in: {source}")
    else:
        raise FileNotFoundError(f"Petrel project path does not exist: {source}")

    data_path = project_folder / "Data.ptd"
    if not project_folder.is_dir():
        raise FileNotFoundError(f"Petrel project folder does not exist: {project_folder}")
    if not data_path.is_file():
        raise FileNotFoundError(f"Petrel Data.ptd was not found: {data_path}")
    model_path = project_folder / "Model.ptd"
    return PetrelProjectPaths(
        source_path=source,
        project_file=project_file,
        project_folder=project_folder,
        data_path=data_path,
        model_path=model_path if model_path.is_file() else None,
    )


def decompress_lz4_block(data: bytes) -> bytes:
    """Decode a raw LZ4 block without requiring an external package."""

    source = memoryview(data)
    source_pos = 0
    output = bytearray()
    while source_pos < len(source):
        token = source[source_pos]
        source_pos += 1

        literal_length = token >> 4
        if literal_length == 15:
            literal_length, source_pos = _read_lz4_extended_length(source, source_pos, literal_length)
        literal_end = source_pos + literal_length
        if literal_end > len(source):
            raise ValueError("LZ4 literal run exceeds compressed block")
        output.extend(source[source_pos:literal_end])
        source_pos = literal_end
        if source_pos == len(source):
            break

        if source_pos + 2 > len(source):
            raise ValueError("LZ4 match offset is truncated")
        match_offset = int(source[source_pos]) | (int(source[source_pos + 1]) << 8)
        source_pos += 2
        if match_offset <= 0 or match_offset > len(output):
            raise ValueError(f"Invalid LZ4 match offset: {match_offset}")

        match_length = token & 0x0F
        if match_length == 15:
            match_length, source_pos = _read_lz4_extended_length(source, source_pos, match_length)
        match_length += 4
        match_pos = len(output) - match_offset
        pattern = bytes(output[match_pos : match_pos + min(match_offset, match_length)])
        repeat_count = (match_length + len(pattern) - 1) // len(pattern)
        output.extend((pattern * repeat_count)[:match_length])
    return bytes(output)


def iter_decoded_lz4_file(path: str | Path) -> Iterator[bytes]:
    source_path = Path(path)

    def parts() -> Iterator[bytes]:
        with source_path.open("rb") as stream:
            prefix = stream.read(1_048_576)
            container_offset = prefix.find(LZ4_BLOCK_MAGIC)
            if container_offset < 0:
                raise ValueError(f"Petrel LZ4 container was not found in: {source_path}")
            stream.seek(container_offset)
            while True:
                part = stream.read(8 * 1024 * 1024)
                if not part:
                    break
                yield part

    yield from iter_decoded_lz4_parts(parts(), source_name=str(source_path))


def iter_decoded_lz4_parts(parts: Iterator[bytes], *, source_name: str = "stream") -> Iterator[bytes]:
    stream = _PartStream(parts)
    magic = stream.read_up_to(4)
    if magic != LZ4_BLOCK_MAGIC:
        raise ValueError(f"Invalid Petrel LZ4 magic in {source_name}: {magic!r}")
    frame_index = 0
    while True:
        header = stream.read_up_to(8)
        if not header:
            return
        if len(header) != 8:
            raise ValueError(f"Truncated Petrel LZ4 header in {source_name}, frame {frame_index}")
        compressed_size = struct.unpack_from("<I", header, 0)[0]
        payload = stream.read_exact(compressed_size)
        yield decompress_lz4_block(payload)
        frame_index += 1


def write_decoded_lz4_file(source: str | Path, destination: str | Path) -> int:
    output_path = Path(destination)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output_path.open("wb") as stream:
        for block in iter_decoded_lz4_file(source):
            stream.write(block)
            written += len(block)
    return written


def profile_bxml(data: bytes) -> PetrelBxmlProfile:
    symbols, payload_offset = _read_bxml_symbols(data)
    payload = data[payload_offset:] if payload_offset is not None else data
    text_values = []
    symbol_set = set(symbols)
    for match in ASCII_TEXT_PATTERN.finditer(payload):
        text = match.group().decode("utf-8", errors="replace")
        if text not in symbol_set and text not in text_values:
            text_values.append(text)
    referenced_uuids = sorted({match.group().decode("ascii").lower() for match in UUID_PATTERN.finditer(data)})
    return PetrelBxmlProfile(
        version=data[4] if data.startswith(b"BXML") and len(data) >= 5 else None,
        symbols=tuple(symbols),
        payload_offset=payload_offset,
        text_values=tuple(text_values),
        referenced_uuids=tuple(referenced_uuids),
        decoded_prefix_bytes=len(data),
        header_hex=data[:32].hex(),
    )


def _read_bxml_symbols(data: bytes) -> tuple[list[str], int | None]:
    if not data.startswith(BXML_MAGIC):
        return [], None
    position = len(BXML_MAGIC)
    symbols: list[str] = []
    while position < len(data):
        token = data[position]
        position += 1
        if token == 0xA0:
            return symbols, position
        if token < 0xA1 or token > 0xA4:
            return symbols, None
        length_width = token - 0xA0
        if position + length_width > len(data):
            return symbols, None
        length = int.from_bytes(data[position : position + length_width], "little")
        position += length_width
        if position + length > len(data):
            return symbols, None
        symbols.append(data[position : position + length].decode("utf-8", errors="replace"))
        position += length
    return symbols, None


def _read_lz4_extended_length(source: memoryview, position: int, initial: int) -> tuple[int, int]:
    length = initial
    while True:
        if position >= len(source):
            raise ValueError("LZ4 extended length is truncated")
        value = int(source[position])
        position += 1
        length += value
        if value != 255:
            return length, position


def _validate_store_schema(connection: sqlite3.Connection, data_path: Path) -> None:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing = {"data", "blob_parts"} - tables
    if missing:
        raise ValueError(f"Unsupported Petrel Data.ptd schema in {data_path}; missing: {sorted(missing)}")


class _PartStream:
    def __init__(self, parts: Iterator[bytes]):
        self._parts = iter(parts)
        self._buffer = memoryview(b"")
        self._position = 0
        self._finished = False

    def read_up_to(self, size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            if self._position >= len(self._buffer):
                if self._finished:
                    break
                try:
                    self._buffer = memoryview(next(self._parts))
                    self._position = 0
                except StopIteration:
                    self._finished = True
                    break
            count = min(size - len(result), len(self._buffer) - self._position)
            result.extend(self._buffer[self._position : self._position + count])
            self._position += count
        return bytes(result)

    def read_exact(self, size: int) -> bytes:
        result = self.read_up_to(size)
        if len(result) != size:
            raise ValueError(f"Petrel BLOB stream is truncated: expected {size}, got {len(result)} bytes")
        return result

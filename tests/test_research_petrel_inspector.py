from __future__ import annotations

from pathlib import Path
import sqlite3
import struct

from research.petrel.project_inspector import (
    BXML_MAGIC,
    PetrelProjectReader,
    decompress_lz4_block,
    profile_bxml,
    resolve_petrel_project_paths,
    write_decoded_lz4_file,
)


def test_decompress_lz4_literal_block() -> None:
    source = b"Petrel BXML data" * 40
    assert decompress_lz4_block(_lz4_literal(source)) == source


def test_profile_bxml_reads_symbol_dictionary() -> None:
    data = BXML_MAGIC + b"\xa1\x04Type\xa1\x05value\xa0payload 01234567-89ab-cdef-0123-456789abcdef"
    profile = profile_bxml(data)
    assert profile.version == 1
    assert profile.symbols == ("Type", "value")
    assert profile.referenced_uuids == ("01234567-89ab-cdef-0123-456789abcdef",)


def test_reader_catalogues_and_decodes_cross_part_object(tmp_path: Path) -> None:
    project = tmp_path / "Example.ptd"
    project.mkdir()
    data_path = project / "Data.ptd"
    connection = sqlite3.connect(data_path)
    connection.executescript(
        """
        CREATE TABLE data(
            data_pk INTEGER PRIMARY KEY,
            droid TEXT NOT NULL,
            name TEXT NOT NULL,
            version INTEGER NOT NULL,
            blob_type TEXT,
            time_stamp DATETIME
        );
        CREATE TABLE blob_parts(
            data_fk INTEGER NOT NULL,
            part INTEGER NOT NULL,
            blob_data BLOB NOT NULL,
            PRIMARY KEY(data_fk, part)
        );
        """
    )
    decoded_first = BXML_MAGIC + b"\xa1\x04Type\xa1\x04item\xa0" + b"payload" * 100
    decoded_second = b"second block" * 50
    decoded = decoded_first + decoded_second
    frame = _petrel_stream(decoded_first, decoded_second)
    split = 19
    connection.execute(
        "INSERT INTO data VALUES(1, ?, '', 1, 'Points3', '2026-01-01')",
        ("://Petrel/01234567-89ab-cdef-0123-456789abcdef",),
    )
    connection.executemany(
        "INSERT INTO blob_parts VALUES(1, ?, ?)",
        [(1, frame[:split]), (2, frame[split:])],
    )
    connection.execute(
        "INSERT INTO data VALUES(2, '://Petrel/LineGeometry', '', 1, '', '2026-01-01')"
    )
    connection.execute("INSERT INTO blob_parts VALUES(2, 1, ?)", (b"\x00" * 8,))
    connection.commit()
    connection.close()

    with PetrelProjectReader(project) as reader:
        objects = reader.list_objects()
        assert len(objects) == 2
        assert objects[0].uuid == "01234567-89ab-cdef-0123-456789abcdef"
        assert b"".join(reader.iter_decoded_blocks(1)) == decoded
        decoded_path = tmp_path / "decoded.bxml"
        assert reader.write_decoded_object(1, decoded_path) == len(decoded)
        assert decoded_path.read_bytes() == decoded
        diagnostics = reader.inspect_object(1)
        assert diagnostics.frame_count == 2
        assert diagnostics.decoded_bytes == len(decoded)
        assert diagnostics.bxml is not None
        assert diagnostics.bxml.symbols == ("Type", "item")
        assert diagnostics.storage_encoding == "petrel-lz4-bxml"

        raw_diagnostics = reader.inspect_object(2)
        assert raw_diagnostics.storage_encoding == "raw"
        assert raw_diagnostics.stored_bytes == 8
        assert raw_diagnostics.decoded_bytes == 0
        assert raw_diagnostics.bxml is None


def test_resolve_project_from_containing_folder(tmp_path: Path) -> None:
    project_file = tmp_path / "Example.pet"
    project_file.write_bytes(b"placeholder")
    project_folder = tmp_path / "Example.ptd"
    project_folder.mkdir()
    (project_folder / "Data.ptd").write_bytes(b"placeholder")
    paths = resolve_petrel_project_paths(tmp_path)
    assert paths.project_file == project_file
    assert paths.project_folder == project_folder


def test_write_decoded_lz4_file(tmp_path: Path) -> None:
    first = b"first" * 100
    second = b"second" * 100
    source = tmp_path / "Model.ptd"
    source.write_bytes(_petrel_stream(first, second))
    destination = tmp_path / "Model.bxml"
    assert write_decoded_lz4_file(source, destination) == len(first) + len(second)
    assert destination.read_bytes() == first + second


def _petrel_stream(*decoded_blocks: bytes) -> bytes:
    result = bytearray(b"LZ4\x01")
    for decoded in decoded_blocks:
        compressed = _lz4_literal(decoded)
        result.extend(struct.pack("<II", len(compressed), 0))
        result.extend(compressed)
    return bytes(result)


def _lz4_literal(data: bytes) -> bytes:
    result = bytearray()
    length = len(data)
    result.append(min(length, 15) << 4)
    if length >= 15:
        remaining = length - 15
        while remaining >= 255:
            result.append(255)
            remaining -= 255
        result.append(remaining)
    result.extend(data)
    return bytes(result)

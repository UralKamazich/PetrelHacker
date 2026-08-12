from __future__ import annotations

from pathlib import Path
from bisect import bisect_right
import uuid

from core.petrel_lz4 import read_petrel_lz4_file
from core.petrel_property_reader import _read_bxml_dictionary, _read_varint, _tag


PETREL_MODEL_DATA = "Model.ptd"


def read_petrel_object_names(ptd_path: str | Path, droids: list[str]) -> dict[str, str]:
    model_path = Path(ptd_path) / PETREL_MODEL_DATA
    if not model_path.is_file():
        return {}
    raw = read_petrel_lz4_file(model_path, max_bytes=256 * 1024 * 1024)
    return extract_petrel_object_names(raw, droids)


def read_petrel_parent_names(ptd_path: str | Path, droids: list[str]) -> dict[str, str]:
    model_path = Path(ptd_path) / PETREL_MODEL_DATA
    if not model_path.is_file():
        return {}
    raw = read_petrel_lz4_file(model_path, max_bytes=256 * 1024 * 1024)
    return extract_petrel_parent_names(raw, droids)


def extract_petrel_object_names(raw: bytes, droids: list[str]) -> dict[str, str]:
    names, _body_offset = _read_bxml_dictionary(raw)
    try:
        name_tag = _tag(names.index("name"))
    except ValueError:
        return {}

    result: dict[str, str] = {}
    for droid in droids:
        normalized = _plain_uuid(droid)
        if normalized is None:
            continue
        guid = uuid.UUID(normalized).bytes_le
        search_offset = 0
        candidates: list[str] = []
        while True:
            guid_offset = raw.find(guid, search_offset)
            if guid_offset < 0:
                break
            search_offset = guid_offset + 1
            if guid_offset == 0 or raw[guid_offset - 1] != 0xB1:
                continue
            name = _read_name_after_guid(raw, guid_offset + len(guid), name_tag)
            if name:
                candidates.append(name)
        if candidates:
            result[normalized] = candidates[-1]
    return result


def extract_petrel_parent_names(raw: bytes, droids: list[str]) -> dict[str, str]:
    names, _body_offset = _read_bxml_dictionary(raw)
    try:
        unique_tag = _tag(names.index("unique_tag")) + b"\xb1"
        name_tag = _tag(names.index("name")) + b"\x99"
    except ValueError:
        return {}
    segments = _object_segments(raw)
    segment_starts = [start for start, _end in segments]
    result: dict[str, str] = {}
    for droid in droids:
        normalized = _plain_uuid(droid)
        if normalized is None:
            continue
        guid = uuid.UUID(normalized).bytes_le
        occurrence = 0
        while True:
            guid_offset = raw.find(guid, occurrence)
            if guid_offset < 0:
                break
            occurrence = guid_offset + 1
            segment_index = bisect_right(segment_starts, guid_offset) - 1
            if segment_index < 0:
                continue
            start, end = segments[segment_index]
            if not (start <= guid_offset < end):
                continue
            segment = raw[start:end]
            own_uuid = _segment_uuid(segment, unique_tag)
            if own_uuid == normalized:
                continue
            name = _segment_name(segment, name_tag)
            if name:
                result[normalized] = name
                break
    return result


def _read_name_after_guid(raw: bytes, offset: int, name_tag: bytes) -> str | None:
    marker = name_tag + b"\x99"
    marker_offset = raw.find(marker, offset, min(len(raw), offset + 512))
    if marker_offset < 0:
        return None
    try:
        size, value_offset = _read_varint(raw, marker_offset + len(marker))
    except (IndexError, ValueError):
        return None
    if not size or size > 4096 or value_offset + size > len(raw):
        return None
    try:
        value = raw[value_offset : value_offset + size].decode("utf-8")
    except UnicodeDecodeError:
        return None
    return value.strip() or None


def _object_segments(raw: bytes) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    offset = 0
    while True:
        marker_offset = raw.find(b"\xa2\xa0", offset)
        if marker_offset < 0:
            return segments
        offset = marker_offset + 2
        try:
            size, start = _read_varint(raw, offset)
        except (IndexError, ValueError):
            continue
        end = start + size
        if size and end <= len(raw):
            segments.append((start, end))


def _segment_uuid(segment: bytes, unique_tag: bytes) -> str | None:
    offset = segment.find(unique_tag)
    if offset < 0 or offset + len(unique_tag) + 16 > len(segment):
        return None
    try:
        return str(uuid.UUID(bytes_le=segment[offset + len(unique_tag) : offset + len(unique_tag) + 16]))
    except ValueError:
        return None


def _segment_name(segment: bytes, name_tag: bytes) -> str | None:
    offset = segment.find(name_tag)
    if offset < 0:
        return None
    try:
        size, value_offset = _read_varint(segment, offset + len(name_tag))
    except (IndexError, ValueError):
        return None
    if not size or size > 4096 or value_offset + size > len(segment):
        return None
    try:
        return segment[value_offset : value_offset + size].decode("utf-8").strip() or None
    except UnicodeDecodeError:
        return None


def _plain_uuid(value: str) -> str | None:
    candidate = str(value).rsplit("/", 1)[-1]
    try:
        return str(uuid.UUID(candidate))
    except ValueError:
        return None

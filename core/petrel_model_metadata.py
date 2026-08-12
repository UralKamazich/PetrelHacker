from __future__ import annotations

from pathlib import Path
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


def _plain_uuid(value: str) -> str | None:
    candidate = str(value).rsplit("/", 1)[-1]
    try:
        return str(uuid.UUID(candidate))
    except ValueError:
        return None

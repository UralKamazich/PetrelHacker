from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import uuid

from core.petrel_lz4 import PETREL_LZ4_MAGIC, read_petrel_lz4_bytes, read_petrel_lz4_file
from core.petrel_property_reader import _read_bxml_dictionary, _read_varint
from core.petrel_trajectory_reader import _read_bxml_number


_CLASS_MARKER = b"\x42\x2a\x42\x2c\x99"
_PARENT_MARKER = b"\x42\x36\xb1"
_UUID_MARKER = b"\x42\x38\xb1"
_KID_INDEX_MARKER = b"\x42\x3a"
_NAME_MARKER = b"\x42\x3c\x99"
_TECHNICAL_HORIZON = re.compile(r"Horizon\s+\d+", flags=re.IGNORECASE)


@dataclass(frozen=True)
class PetrelNamedHorizon:
    uuid: str
    title: str
    grid_uuid: str
    k_index: int


@dataclass(frozen=True)
class _ProjectStub:
    parent_uuid: str
    uuid: str
    kid_index: int
    title: str


def read_petrel_named_horizons(project_path: str | Path) -> list[PetrelNamedHorizon]:
    path = Path(project_path)
    source = path.read_bytes()
    lz4_offset = source.find(PETREL_LZ4_MAGIC)
    if lz4_offset < 0:
        return []
    raw = read_petrel_lz4_bytes(source[lz4_offset:], max_bytes=64 * 1024 * 1024)
    folders = {item.uuid: item.parent_uuid for item in _read_class_stubs(raw, "HorizonFolder")}
    horizon_indices = _read_model_horizon_indices(path.with_suffix(".ptd") / "Model.ptd")
    result: list[PetrelNamedHorizon] = []
    for item in _read_class_stubs(raw, "HorizonSubject"):
        grid_uuid = folders.get(item.parent_uuid)
        k_index = horizon_indices.get(item.uuid)
        if grid_uuid is None or k_index is None or _TECHNICAL_HORIZON.fullmatch(item.title):
            continue
        result.append(
            PetrelNamedHorizon(
                uuid=item.uuid,
                title=item.title,
                grid_uuid=grid_uuid,
                k_index=k_index,
            )
        )
    return result


def _read_class_stubs(raw: bytes, class_name: str) -> list[_ProjectStub]:
    groups = _class_groups(raw)
    group_index = next((index for index, item in enumerate(groups) if item[1] == class_name), None)
    if group_index is None:
        return []
    start = groups[group_index][0]
    end = groups[group_index + 1][0] if group_index + 1 < len(groups) else len(raw)
    segment = raw[start:end]
    result: list[_ProjectStub] = []
    offset = 0
    while True:
        parent_offset = segment.find(_PARENT_MARKER, offset)
        if parent_offset < 0:
            break
        offset = parent_offset + 1
        try:
            parent_uuid = _uuid_after(segment, parent_offset + len(_PARENT_MARKER))
            uuid_offset = segment.find(
                _UUID_MARKER,
                parent_offset + len(_PARENT_MARKER) + 16,
                min(len(segment), parent_offset + 256),
            )
            if uuid_offset < 0:
                continue
            item_uuid = _uuid_after(segment, uuid_offset + len(_UUID_MARKER))
            kid_offset = segment.find(
                _KID_INDEX_MARKER,
                uuid_offset + len(_UUID_MARKER) + 16,
                min(len(segment), uuid_offset + 128),
            )
            if kid_offset < 0:
                continue
            kid_index, value_end = _read_bxml_number(
                segment, kid_offset + len(_KID_INDEX_MARKER)
            )
            name_offset = segment.find(
                _NAME_MARKER,
                value_end,
                min(len(segment), value_end + 160),
            )
            if name_offset < 0:
                continue
            size, value_offset = _read_varint(segment, name_offset + len(_NAME_MARKER))
            value_end = value_offset + size
            if not size or value_end > len(segment):
                continue
            title = segment[value_offset:value_end].decode("utf-8").strip()
            if title:
                result.append(_ProjectStub(parent_uuid, item_uuid, int(kid_index), title))
        except (IndexError, UnicodeDecodeError, ValueError):
            continue
    return result


def _class_groups(raw: bytes) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    offset = 0
    while True:
        marker_offset = raw.find(_CLASS_MARKER, offset)
        if marker_offset < 0:
            return result
        offset = marker_offset + 1
        try:
            size, value_offset = _read_varint(raw, marker_offset + len(_CLASS_MARKER))
            value_end = value_offset + size
            if not size or value_end > len(raw):
                continue
            name = raw[value_offset:value_end].decode("utf-8")
        except (IndexError, UnicodeDecodeError, ValueError):
            continue
        result.append((marker_offset, name))


def _uuid_after(data: bytes, offset: int) -> str:
    if offset + 16 > len(data):
        raise ValueError("Truncated Petrel project UUID")
    return str(uuid.UUID(bytes_le=data[offset : offset + 16]))


def _read_model_horizon_indices(model_path: Path) -> dict[str, int]:
    if not model_path.is_file():
        return {}
    raw = read_petrel_lz4_file(model_path, max_bytes=256 * 1024 * 1024)
    names, body_offset = _read_bxml_dictionary(raw)
    try:
        unique_marker = _large_tag(names.index("unique_tag")) + b"\xb1"
        horizon_index_marker = _large_tag(names.index("horizon_index"))
    except ValueError:
        return {}
    result: dict[str, int] = {}
    offset = body_offset
    while True:
        marker_offset = raw.find(unique_marker, offset)
        if marker_offset < 0:
            return result
        offset = marker_offset + 1
        uuid_offset = marker_offset + len(unique_marker)
        try:
            item_uuid = _uuid_after(raw, uuid_offset)
        except ValueError:
            continue
        index_offset = raw.find(
            horizon_index_marker,
            uuid_offset + 16,
            min(len(raw), uuid_offset + 768),
        )
        if index_offset < 0:
            continue
        try:
            value, _value_end = _read_bxml_number(
                raw, index_offset + len(horizon_index_marker)
            )
            k_index = int(value)
        except (IndexError, ValueError):
            continue
        if k_index == value and k_index >= 0:
            result[item_uuid] = k_index


def _large_tag(index: int) -> bytes:
    value = index * 2
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | (0x80 if value else 0))
        if not value:
            return b"\x42" + bytes(encoded)

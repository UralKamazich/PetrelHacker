from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from bisect import bisect_right
import uuid

from core.petrel_lz4 import PETREL_LZ4_MAGIC, read_petrel_lz4_bytes, read_petrel_lz4_file
from core.petrel_property_reader import _read_bxml_dictionary, _read_varint, _tag
from core.petrel_trajectory_reader import _join_bxml_pages


PETREL_MODEL_DATA = "Model.ptd"


@dataclass(frozen=True)
class PetrelProjectNode:
    uuid: str
    parent_uuid: str | None
    visual_name: str | None


@dataclass(frozen=True)
class PetrelPropertyPath:
    title: str | None
    grid_uuid: str | None
    folder_path: tuple[str, ...]


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


def read_petrel_property_paths(
    project_path: str | Path,
    property_droids: list[str],
    grid_droids: list[str],
) -> dict[str, PetrelPropertyPath]:
    path = Path(project_path)
    if not path.is_file():
        return {}
    source = path.read_bytes()
    lz4_offset = source.find(PETREL_LZ4_MAGIC)
    if lz4_offset < 0:
        return {}
    try:
        raw = read_petrel_lz4_bytes(source[lz4_offset:], max_bytes=64 * 1024 * 1024)
        nodes = extract_petrel_project_nodes(raw)
    except (EOFError, OSError, UnicodeDecodeError, ValueError):
        return {}
    return resolve_petrel_property_paths(nodes, property_droids, grid_droids)


def extract_petrel_project_nodes(raw: bytes) -> dict[str, PetrelProjectNode]:
    names, body_offset = _read_bxml_dictionary(raw)
    stream = _join_bxml_pages(raw, body_offset)
    try:
        unique_marker = _tag(names.index("uniqueTag")) + b"\xb1"
        parent_marker = _tag(names.index("parentTag"))
        visual_marker = _tag(names.index("visualName"))
    except ValueError:
        return {}

    nodes: dict[str, PetrelProjectNode] = {}
    offset = 0
    previous_end = 0
    while True:
        unique_offset = stream.find(unique_marker, offset)
        if unique_offset < 0:
            break
        uuid_offset = unique_offset + len(unique_marker)
        if uuid_offset + 16 > len(stream):
            break
        object_uuid = str(uuid.UUID(bytes_le=stream[uuid_offset : uuid_offset + 16])).lower()
        parent_uuid = _stub_parent_uuid(stream, parent_marker, previous_end, unique_offset)
        next_unique = stream.find(unique_marker, uuid_offset + 16)
        value_end = min(len(stream), next_unique if next_unique >= 0 else uuid_offset + 1024)
        visual_name = _stub_visual_name(stream, visual_marker, uuid_offset + 16, value_end)
        current = nodes.get(object_uuid)
        if current is None or visual_name:
            nodes[object_uuid] = PetrelProjectNode(object_uuid, parent_uuid, visual_name)
        previous_end = uuid_offset + 16
        offset = uuid_offset + 16
    return nodes


def resolve_petrel_property_paths(
    nodes: dict[str, PetrelProjectNode],
    property_droids: list[str],
    grid_droids: list[str],
) -> dict[str, PetrelPropertyPath]:
    grid_ids = {_plain_uuid(value) for value in grid_droids}
    grid_ids.discard(None)
    result: dict[str, PetrelPropertyPath] = {}
    for droid in property_droids:
        property_uuid = _plain_uuid(droid)
        if property_uuid is None or property_uuid not in nodes:
            continue
        leaf = nodes[property_uuid]
        folders: list[str] = []
        grid_uuid: str | None = None
        current_uuid = leaf.parent_uuid
        visited = {property_uuid}
        while current_uuid and current_uuid not in visited:
            visited.add(current_uuid)
            if current_uuid in grid_ids:
                grid_uuid = current_uuid
                break
            current = nodes.get(current_uuid)
            if current is None:
                break
            if current.visual_name and current.visual_name != "Properties":
                folders.append(current.visual_name)
            current_uuid = current.parent_uuid
        result[property_uuid] = PetrelPropertyPath(
            title=leaf.visual_name,
            grid_uuid=grid_uuid,
            folder_path=tuple(reversed(folders)),
        )
    return result


def _stub_parent_uuid(data: bytes, marker: bytes, start: int, end: int) -> str | None:
    offset = data.rfind(marker, max(start, end - 256), end)
    value_offset = offset + len(marker) if offset >= 0 else -1
    if value_offset < 0 or value_offset + 17 > len(data) or data[value_offset] != 0xB1:
        return None
    return str(uuid.UUID(bytes_le=data[value_offset + 1 : value_offset + 17])).lower()


def _stub_visual_name(data: bytes, marker: bytes, start: int, end: int) -> str | None:
    offset = data.find(marker, start, end)
    value_offset = offset + len(marker) if offset >= 0 else -1
    if value_offset < 0 or value_offset >= len(data) or data[value_offset] != 0x99:
        return None
    try:
        size, text_offset = _read_varint(data, value_offset + 1)
    except (IndexError, ValueError):
        return None
    text_end = text_offset + size
    if not size or text_end > len(data):
        return None
    try:
        return data[text_offset:text_end].decode("utf-8").strip() or None
    except UnicodeDecodeError:
        return None


def extract_petrel_object_names(raw: bytes, droids: list[str]) -> dict[str, str]:
    names, _body_offset = _read_bxml_dictionary(raw)
    try:
        name_tag = _tag(names.index("name"))
    except ValueError:
        return {}

    wanted: dict[bytes, str] = {}
    for droid in droids:
        normalized = _plain_uuid(droid)
        if normalized is not None:
            wanted[uuid.UUID(normalized).bytes_le] = normalized

    # One pass over GUID markers (0xB1 + 16 bytes) instead of a full scan per
    # droid; later occurrences win, as before.
    result: dict[str, str] = {}
    marker_offset = raw.find(b"\xb1")
    while marker_offset >= 0:
        guid_offset = marker_offset + 1
        normalized = wanted.get(raw[guid_offset : guid_offset + 16])
        if normalized is not None:
            name = _read_name_after_guid(raw, guid_offset + 16, name_tag)
            if name:
                result[normalized] = name
        marker_offset = raw.find(b"\xb1", guid_offset)
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

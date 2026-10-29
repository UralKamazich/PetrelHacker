from __future__ import annotations

from pathlib import Path
import json
from xml.etree import ElementTree as ET

from research.petrel.project_metadata import PetrelProjectStub


def resolve_well_stub(
    object_uuid: str | None,
    stubs: dict[str, PetrelProjectStub],
) -> PetrelProjectStub | None:
    current_uuid = object_uuid
    visited: set[str] = set()
    while current_uuid and current_uuid not in visited:
        visited.add(current_uuid)
        stub = stubs.get(current_uuid)
        if stub is None:
            return None
        if stub.class_name == "WellTraceSubject":
            return stub
        current_uuid = stub.parent_uuid
    return None


def read_well_shape_points(
    xml_path: str | Path,
    *,
    object_uuid: str,
    well_uuid: str | None,
    well_name: str | None,
) -> list[dict[str, object]]:
    root = ET.parse(xml_path).getroot()
    records = _descendant(root, "full_trajectory_polygon", "records")
    if records is None:
        return []
    result: list[dict[str, object]] = []
    for point_index, item in enumerate(_direct_children(records, "item")):
        vertex = _direct_child(item, "vertex")
        coordinates = [_float(_text(element)) for element in _direct_children(vertex, "double")]
        z = coordinates[2] if len(coordinates) > 2 else None
        result.append(
            {
                "object_uuid": object_uuid,
                "well_uuid": well_uuid,
                "well_name": well_name,
                "point_index": point_index,
                "md": _float(_child_text(item, "md")),
                "x": coordinates[0] if len(coordinates) > 0 else None,
                "y": coordinates[1] if len(coordinates) > 1 else None,
                "z": z,
                "tvd": -z if z is not None else None,
                "inclination": _float(_child_text(item, "inclination")),
                "azimuth": _float(_child_text(item, "azimuth")),
                "dx_tn": _float(_child_text(item, "dx_tn")),
                "dy_tn": _float(_child_text(item, "dy_tn")),
                "dls": _float(_child_text(item, "dls")),
            }
        )
    return result


def read_xyz_trajectory_points(
    xml_path: str | Path,
    *,
    object_uuid: str,
    well_uuid: str | None,
    well_name: str | None,
) -> list[dict[str, object]]:
    root = ET.parse(xml_path).getroot()
    settings = _direct_child(root, "settings")
    records = _direct_child(root, "records")
    if records is None:
        return []
    first_md = _float(_child_text(settings, "first_md")) if settings is not None else None
    algorithm = _child_text(settings, "calculation_algorithm") if settings is not None else None
    result: list[dict[str, object]] = []
    for point_index, item in enumerate(_direct_children(records, "item")):
        z = _float(_child_text(item, "z"))
        result.append(
            {
                "object_uuid": object_uuid,
                "well_uuid": well_uuid,
                "well_name": well_name,
                "point_index": point_index,
                "x": _float(_child_text(item, "x")),
                "y": _float(_child_text(item, "y")),
                "z": z,
                "tvd": -z if z is not None else None,
                "first_md": first_md,
                "calculation_algorithm": algorithm,
            }
        )
    return result


def read_points3(
    xml_path: str | Path,
    *,
    object_uuid: str,
    attribute_stubs: list[PetrelProjectStub],
) -> list[dict[str, object]]:
    root = ET.parse(xml_path).getroot()
    vertices = [_float(_text(item)) for item in _direct_children(_direct_child(root, "vertices"), "double")]
    point_count = len(vertices) // 3
    rows = [
        {
            "object_uuid": object_uuid,
            "point_index": index,
            "x": vertices[index * 3],
            "y": vertices[index * 3 + 1],
            "z": vertices[index * 3 + 2],
            "tvd": -vertices[index * 3 + 2] if vertices[index * 3 + 2] is not None else None,
        }
        for index in range(point_count)
    ]

    ordered_attributes = sorted(attribute_stubs, key=lambda stub: stub.kid_index if stub.kid_index is not None else 10**9)
    if ordered_attributes and ordered_attributes[0].visual_name == "Z":
        ordered_attributes = ordered_attributes[1:]
    vectors = _direct_children(_direct_child(root, "attributes"), "type_vector")
    for vector_index, vector in enumerate(vectors):
        stub = ordered_attributes[vector_index] if vector_index < len(ordered_attributes) else None
        column = _attribute_column_name(stub, vector_index)
        values = _type_vector_values(vector)
        for point_index, row in enumerate(rows):
            row[column] = values[point_index] if point_index < len(values) else None
    return rows


def _descendant(root: ET.Element, *names: str) -> ET.Element | None:
    current: ET.Element | None = root
    for name in names:
        current = _direct_child(current, name)
        if current is None:
            return None
    return current


def _direct_child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    return next((child for child in element if _local_name(child.tag) == name), None)


def _direct_children(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    return [child for child in element if _local_name(child.tag) == name]


def _child_text(element: ET.Element | None, name: str) -> str | None:
    return _text(_direct_child(element, name))


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _attribute_column_name(stub: PetrelProjectStub | None, vector_index: int) -> str:
    if stub is None:
        return f"attribute_{vector_index}"
    name = stub.visual_name or f"attribute_{vector_index}"
    return f"{name} [{stub.kid_index}]" if name == "Undef" else name


def _type_vector_values(vector: ET.Element) -> list[object]:
    ignored = {"type", "default"}
    container = next((child for child in vector if _local_name(child.tag) not in ignored), None)
    if container is None:
        return []
    container_name = _local_name(container.tag)
    values: list[object] = []
    for item in container:
        name = _local_name(item.tag)
        if container_name in {"doubles", "floats"}:
            values.append(_float(_text(item)))
        elif container_name in {"ints", "kidtags"}:
            values.append(_integer(_text(item)))
        elif container_name == "bools":
            values.append((_text(item) or "").lower() == "true")
        elif container_name in {"strings", "uniquetags"}:
            values.append(_text(item) or "")
        elif container_name == "update_infos":
            values.append(json.dumps({_local_name(child.tag): _text(child) for child in item}, ensure_ascii=False))
        else:
            values.append(_text(item))
    return values


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None

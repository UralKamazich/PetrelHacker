from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class PetrelProjectStub:
    class_name: str
    stub_type: str
    uuid: str | None
    parent_uuid: str | None
    kid_index: int | None
    visual_name: str | None
    has_visible_icon: bool | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def read_project_stubs(xml_path: str | Path) -> list[PetrelProjectStub]:
    root = ET.parse(xml_path).getroot()
    result: list[PetrelProjectStub] = []
    for entry in root.iter():
        if _local_name(entry.tag) != "entry":
            continue
        key = _direct_child(entry, "key")
        value = _direct_child(entry, "value")
        stubs = _direct_child(value, "stubs") if value is not None else None
        if key is None or stubs is None:
            continue
        class_name = _text(key) or ""
        for item in stubs:
            if _local_name(item.tag) != "item":
                continue
            result.append(
                PetrelProjectStub(
                    class_name=class_name,
                    stub_type=item.attrib.get("Type", ""),
                    uuid=_normalized_uuid(_child_text(item, "uniqueTag")),
                    parent_uuid=_normalized_uuid(_child_text(item, "parentTag")),
                    kid_index=_integer(_child_text(item, "kidIndex")),
                    visual_name=_child_text(item, "visualName"),
                    has_visible_icon=_boolean(_child_text(item, "hasVisibleIcon")),
                )
            )
    return result


def stubs_by_uuid(stubs: list[PetrelProjectStub]) -> dict[str, PetrelProjectStub]:
    result: dict[str, PetrelProjectStub] = {}
    for stub in stubs:
        if stub.uuid:
            result[stub.uuid] = stub
    return result


def _direct_child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    return next((child for child in element if _local_name(child.tag) == name), None)


def _child_text(element: ET.Element, name: str) -> str | None:
    return _text(_direct_child(element, name))


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalized_uuid(value: str | None) -> str | None:
    return value.lower() if value else None


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return None

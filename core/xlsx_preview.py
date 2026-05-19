from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class XlsxPreview:
    headers: list[str]
    rows: list[list[str]]


def read_xlsx_preview(path: str | Path, max_rows: int = 1000) -> XlsxPreview:
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as package:
        shared_strings = _read_shared_strings(package, ns)
        sheet = ET.fromstring(package.read("xl/worksheets/sheet1.xml"))

    parsed_rows: list[list[str]] = []
    for row in sheet.findall(".//x:sheetData/x:row", ns):
        values = [_cell_text(cell, ns, shared_strings) for cell in row.findall("x:c", ns)]
        parsed_rows.append(values)
        if len(parsed_rows) > max_rows:
            break

    if not parsed_rows:
        return XlsxPreview(headers=[], rows=[])
    return XlsxPreview(headers=parsed_rows[0], rows=parsed_rows[1:])


def _read_shared_strings(package: ZipFile, ns: dict[str, str]) -> list[str]:
    if "xl/sharedStrings.xml" not in package.namelist():
        return []
    root = ET.fromstring(package.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//x:t", ns)) for item in root.findall("x:si", ns)]


def _cell_text(cell: ET.Element, ns: dict[str, str], shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", ns))
    value = cell.find("x:v", ns)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        index = int(value.text)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    if cell_type == "b":
        return "TRUE" if value.text == "1" else "FALSE"
    return value.text

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pandas as pd


REQUIRED_COLUMNS = ("Well", "Port", "X", "Y")
COLUMN_ALIASES = {
    "sleeve_id": "Sleeve_ID",
    "sleeves_id": "Sleeve_ID",
    "sleeveid": "Sleeve_ID",
    "sleevesid": "Sleeve_ID",
    "id": "Sleeve_ID",
    "well": "Well",
    "well_name": "Well",
    "skv": "Well",
    "port": "Port",
    "stage": "Port",
    "port_id": "Port",
    "x": "X",
    "coord_x": "X",
    "coordinate_x": "X",
    "y": "Y",
    "coord_y": "Y",
    "coordinate_y": "Y",
}


def load_sleeves_table(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Sleeves table does not exist: {source}")

    suffix = source.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(source)
    elif suffix in {".xlsx", ".xlsm"}:
        df = _read_excel_with_fallback(source)
    elif suffix == ".xls":
        df = pd.read_excel(source)
    else:
        raise ValueError(f"Unsupported sleeves table format: {source.suffix}")

    df = normalize_sleeves_columns(df)
    return df.dropna(how="all").reset_index(drop=True)


def normalize_sleeves_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    used: set[str] = set()
    for column in df.columns:
        normalized = _normalize_name(str(column))
        target = COLUMN_ALIASES.get(normalized)
        if target and target not in used:
            rename[column] = target
            used.add(target)
    return df.rename(columns=rename)


def validate_sleeves_table(
    df: pd.DataFrame,
    well_col: str = "Well",
    port_col: str = "Port",
    x_col: str = "X",
    y_col: str = "Y",
) -> list[str]:
    warnings: list[str] = []
    has_well_port = well_col in df.columns and port_col in df.columns
    has_legacy_id = "Sleeve_ID" in df.columns
    identity_columns = (well_col, port_col) if has_well_port else ("Sleeve_ID",)
    missing_identity = [] if has_well_port or has_legacy_id else [
        column for column in (well_col, port_col) if column not in df.columns
    ]
    missing = missing_identity + [column for column in (x_col, y_col) if column not in df.columns]
    if missing:
        return [f"Missing required column: {column}" for column in missing]

    for column in identity_columns:
        if df[column].isna().any():
            warnings.append(f"Column {column} contains empty identifiers.")
    duplicated = df[list(identity_columns)].dropna().duplicated()
    if duplicated.any():
        warnings.append(f"Identity columns {', '.join(identity_columns)} contain {int(duplicated.sum())} duplicates.")

    for column in (x_col, y_col):
        numeric = pd.to_numeric(df[column], errors="coerce")
        bad_count = int(numeric.isna().sum())
        if bad_count:
            warnings.append(f"Column {column} contains {bad_count} non-numeric or empty values.")
        else:
            df[column] = numeric.astype(float)

    return warnings


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _read_excel_with_fallback(path: Path) -> pd.DataFrame:
    try:
        return pd.read_excel(path)
    except ImportError:
        return _read_simple_xlsx(path)
    except AttributeError as exc:
        if "numpy" not in str(exc).lower() and "np.float" not in str(exc):
            raise
        return _read_simple_xlsx(path)


def _read_simple_xlsx(path: Path) -> pd.DataFrame:
    """Read first worksheet values for simple XLSX files.

    This fallback intentionally supports plain cell values only. It is enough
    for coordinate tables and avoids a hard failure when openpyxl is missing or
    too old in the current interpreter.
    """
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as workbook:
        names = set(workbook.namelist())
        shared_strings = _read_shared_strings(workbook, ns) if "xl/sharedStrings.xml" in names else []
        sheet_name = _first_sheet_path(workbook)
        sheet = ET.fromstring(workbook.read(sheet_name))

    rows: list[list[object]] = []
    for row in sheet.findall(".//x:sheetData/x:row", ns):
        values: list[object] = []
        for cell in row.findall("x:c", ns):
            value_node = cell.find("x:v", ns)
            value = "" if value_node is None else value_node.text or ""
            if cell.attrib.get("t") == "s" and value != "":
                value = shared_strings[int(value)]
            values.append(_coerce_cell_value(value))
        if any(value != "" for value in values):
            rows.append(values)

    if not rows:
        return pd.DataFrame()
    header = [str(value) for value in rows[0]]
    width = len(header)
    data = [row + [""] * (width - len(row)) for row in rows[1:]]
    return pd.DataFrame(data, columns=header)


def _read_shared_strings(workbook: ZipFile, ns: dict[str, str]) -> list[str]:
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("x:si", ns):
        strings.append("".join(node.text or "" for node in item.findall(".//x:t", ns)))
    return strings


def _first_sheet_path(workbook: ZipFile) -> str:
    preferred = "xl/worksheets/sheet1.xml"
    if preferred in workbook.namelist():
        return preferred
    for name in workbook.namelist():
        if name.startswith("xl/worksheets/") and name.endswith(".xml"):
            return name
    raise ValueError("XLSX workbook does not contain worksheets.")


def _coerce_cell_value(value: str) -> object:
    text = value.strip()
    if text == "":
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return int(number)
    return number

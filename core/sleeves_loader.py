from __future__ import annotations

from pathlib import Path
import re
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
    "tvdss_port": "TVDSS_PORT",
    "tvd_port": "TVDSS_PORT",
    "md": "MD",
    "md_port": "MD",
    "port_md": "MD",
    "sleeve_md": "MD",
    "md_sleeve": "MD",
    "measured_depth": "MD",
    "measured_depth_port": "MD",
    "depth_md": "MD",
    "depth_port_md": "MD",
}
OPTIONAL_NUMERIC_COLUMNS = ("TVDSS_PORT", "MD")


def load_sleeves_table(path: str | Path, column_mapping: dict[str, str] | None = None) -> pd.DataFrame:
    df = read_sleeves_table_raw(path)
    if column_mapping:
        df = apply_sleeves_column_mapping(df, column_mapping)
    else:
        df = normalize_sleeves_columns(df)
    return df.dropna(how="all").reset_index(drop=True)


def read_sleeves_table_raw(path: str | Path) -> pd.DataFrame:
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
    return df.dropna(how="all").reset_index(drop=True)


def read_sleeves_table_headers(path: str | Path) -> list[str]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Sleeves table does not exist: {source}")

    suffix = source.suffix.lower()
    if suffix == ".csv":
        return [str(column) for column in pd.read_csv(source, nrows=0).columns]
    if suffix in {".xlsx", ".xlsm"}:
        try:
            return [str(column) for column in pd.read_excel(source, nrows=0).columns]
        except Exception:  # noqa: BLE001
            return [str(column) for column in _read_simple_xlsx(source).columns]
    if suffix == ".xls":
        return [str(column) for column in pd.read_excel(source, nrows=0).columns]
    raise ValueError(f"Unsupported sleeves table format: {source.suffix}")


def guess_sleeves_column_mapping(columns: list[object]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for column in columns:
        column_name = str(column)
        target = COLUMN_ALIASES.get(_normalize_name(column_name))
        if target and target not in used:
            mapping[target] = column_name
            used.add(target)
    return mapping


def apply_sleeves_column_mapping(df: pd.DataFrame, column_mapping: dict[str, str]) -> pd.DataFrame:
    out = normalize_sleeves_columns(df)
    for target, source in column_mapping.items():
        if not source or source not in df.columns:
            continue
        out[target] = df[source]
    return normalize_sleeves_columns(out)


def unique_well_values(df: pd.DataFrame, well_col: str = "Well") -> list[str]:
    if well_col not in df.columns:
        return []
    values: list[str] = []
    seen: set[str] = set()
    for value in df[well_col]:
        text = _normalize_well_value(value)
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
    return values


def well_value_counts(df: pd.DataFrame, well_col: str = "Well") -> dict[str, int]:
    counts: dict[str, int] = {}
    if well_col not in df.columns:
        return counts
    for value in df[well_col]:
        text = _normalize_well_value(value)
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def filter_sleeves_by_wells(
    df: pd.DataFrame,
    selected_wells: list[str] | tuple[str, ...] | set[str] | None,
    well_col: str = "Well",
) -> pd.DataFrame:
    if selected_wells is None:
        return df.copy().reset_index(drop=True)
    selected = {_normalize_well_value(value) for value in selected_wells}
    selected.discard("")
    if not selected:
        return df.iloc[0:0].copy().reset_index(drop=True)
    if well_col not in df.columns:
        raise ValueError("Cannot filter sleeves by wells: Well column is missing.")
    mask = df[well_col].map(_normalize_well_value).isin(selected)
    return df.loc[mask].copy().reset_index(drop=True)


def normalize_sleeves_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    canonical_names = set(COLUMN_ALIASES.values())
    used = {str(column) for column in df.columns if str(column) in canonical_names}
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

    for column in OPTIONAL_NUMERIC_COLUMNS:
        if column not in df.columns:
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        bad_count = int(numeric.isna().sum())
        if bad_count:
            warnings.append(f"Column {column} contains {bad_count} non-numeric or empty values.")
        else:
            df[column] = numeric.astype(float)

    return warnings


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_well_value(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        head = text[:-2]
        if head.isdigit():
            return head
    return text


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
            cell_index = _cell_column_index(cell.attrib.get("r", ""))
            value = _cell_value(cell, shared_strings, ns)
            if cell_index is None:
                values.append(_coerce_cell_value(value))
                continue
            while len(values) <= cell_index:
                values.append("")
            values[cell_index] = _coerce_cell_value(value)
        if any(value != "" for value in values):
            rows.append(values)

    if not rows:
        return pd.DataFrame()
    header = [str(value) for value in rows[0]]
    width = len(header)
    data = [(row + [""] * width)[:width] for row in rows[1:]]
    return pd.DataFrame(data, columns=header)


def _cell_value(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str:
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", ns))
    value_node = cell.find("x:v", ns)
    value = "" if value_node is None else value_node.text or ""
    if cell.attrib.get("t") == "s" and value != "":
        value = shared_strings[int(value)]
    return value


def _cell_column_index(cell_ref: str) -> int | None:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        return None
    index = 0
    for char in match.group(1):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


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

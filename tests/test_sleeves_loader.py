from __future__ import annotations

import pandas as pd
from zipfile import ZipFile

from core.sleeves_loader import _read_simple_xlsx, normalize_sleeves_columns, validate_sleeves_table


def test_normalize_well_port_aliases() -> None:
    df = pd.DataFrame({"well_name": ["A"], "stage": [1], "x": [1], "y": [2]})
    out = normalize_sleeves_columns(df)
    assert list(out.columns) == ["Well", "Port", "X", "Y"]


def test_validate_sleeves_table_coerces_xy() -> None:
    df = pd.DataFrame({"Well": ["A"], "Port": [1], "X": ["1.5"], "Y": ["2.5"]})
    warnings = validate_sleeves_table(df)
    assert warnings == []
    assert df.loc[0, "X"] == 1.5
    assert df.loc[0, "Y"] == 2.5


def test_validate_sleeves_table_reports_missing_columns() -> None:
    df = pd.DataFrame({"Well": ["A"], "X": [1]})
    warnings = validate_sleeves_table(df)
    assert warnings == ["Missing required column: Port", "Missing required column: Y"]


def test_validate_sleeves_table_supports_legacy_sleeve_id() -> None:
    df = pd.DataFrame({"Sleeve_ID": ["A"], "X": [1], "Y": [2]})
    warnings = validate_sleeves_table(df)
    assert warnings == []


def test_simple_xlsx_reader_preserves_blank_cells_by_reference(tmp_path) -> None:
    path = tmp_path / "sleeves.xlsx"
    with ZipFile(path, "w") as workbook:
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>Well</t></is></c>
      <c r="B1" t="inlineStr"><is><t>Port</t></is></c>
      <c r="C1" t="inlineStr"><is><t>X</t></is></c>
      <c r="D1" t="inlineStr"><is><t>Y</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>A</t></is></c>
      <c r="C2"><v>10</v></c>
      <c r="D2"><v>20</v></c>
      <c r="E2"><v>999</v></c>
    </row>
  </sheetData>
</worksheet>""",
        )

    df = _read_simple_xlsx(path)
    assert list(df.columns) == ["Well", "Port", "X", "Y"]
    assert df.loc[0, "Well"] == "A"
    assert df.loc[0, "Port"] == ""
    assert df.loc[0, "X"] == 10
    assert df.loc[0, "Y"] == 20

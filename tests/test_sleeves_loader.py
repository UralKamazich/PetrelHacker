from __future__ import annotations

import pandas as pd
from zipfile import ZipFile

from core.sleeves_loader import (
    _read_simple_xlsx,
    apply_sleeves_column_mapping,
    filter_sleeves_by_wells,
    guess_sleeves_column_mapping,
    normalize_sleeves_columns,
    unique_well_values,
    validate_sleeves_table,
    well_value_counts,
)


def test_normalize_well_port_aliases() -> None:
    df = pd.DataFrame({"well_name": ["A"], "stage": [1], "x": [1], "y": [2], "tvdss_port": [100.0]})
    out = normalize_sleeves_columns(df)
    assert list(out.columns) == ["Well", "Port", "X", "Y", "TVDSS_PORT"]


def test_validate_sleeves_table_coerces_xy() -> None:
    df = pd.DataFrame({"Well": ["A"], "Port": [1], "X": ["1.5"], "Y": ["2.5"], "TVDSS_PORT": ["100.5"]})
    warnings = validate_sleeves_table(df)
    assert warnings == []
    assert df.loc[0, "X"] == 1.5
    assert df.loc[0, "Y"] == 2.5
    assert df.loc[0, "TVDSS_PORT"] == 100.5


def test_validate_sleeves_table_reports_missing_columns() -> None:
    df = pd.DataFrame({"Well": ["A"], "X": [1]})
    warnings = validate_sleeves_table(df)
    assert warnings == ["Missing required column: Port", "Missing required column: Y"]


def test_validate_sleeves_table_supports_legacy_sleeve_id() -> None:
    df = pd.DataFrame({"Sleeve_ID": ["A"], "X": [1], "Y": [2]})
    warnings = validate_sleeves_table(df)
    assert warnings == []


def test_guess_sleeves_column_mapping_uses_aliases() -> None:
    mapping = guess_sleeves_column_mapping(["well_name", "stage", "coord_x", "coord_y", "tvdss_port"])
    assert mapping == {
        "Well": "well_name",
        "Port": "stage",
        "X": "coord_x",
        "Y": "coord_y",
        "TVDSS_PORT": "tvdss_port",
    }


def test_apply_sleeves_column_mapping_creates_canonical_columns() -> None:
    df = pd.DataFrame({"Скважина": ["A"], "Муфта": [1], "East": [10.0], "North": [20.0]})
    out = apply_sleeves_column_mapping(df, {"Well": "Скважина", "Port": "Муфта", "X": "East", "Y": "North"})
    assert out.loc[0, "Well"] == "A"
    assert out.loc[0, "Port"] == 1
    assert out.loc[0, "X"] == 10.0
    assert out.loc[0, "Y"] == 20.0


def test_apply_sleeves_column_mapping_does_not_duplicate_alias_columns() -> None:
    df = pd.DataFrame({"well_name": ["A"], "stage": [1], "coord_x": [10.0], "coord_y": [20.0]})
    out = apply_sleeves_column_mapping(
        df,
        {"Well": "well_name", "Port": "stage", "X": "coord_x", "Y": "coord_y"},
    )
    assert out.columns.tolist().count("Well") == 1
    assert out.columns.tolist().count("Port") == 1
    assert out.columns.tolist().count("X") == 1
    assert out.columns.tolist().count("Y") == 1


def test_unique_well_values_preserves_table_order() -> None:
    df = pd.DataFrame({"Well": ["A", "B", "A", "", None, "C"]})
    assert unique_well_values(df) == ["A", "B", "C"]


def test_well_value_counts_uses_normalized_well_values() -> None:
    df = pd.DataFrame({"Well": [1.0, "1", "2"]})
    assert well_value_counts(df) == {"1": 2, "2": 1}


def test_filter_sleeves_by_wells_keeps_selected_wells() -> None:
    df = pd.DataFrame({"Well": ["A", "B", "A", "C"], "Port": [1, 1, 2, 1]})
    out = filter_sleeves_by_wells(df, ["A", "C"])
    assert out[["Well", "Port"]].to_dict("records") == [
        {"Well": "A", "Port": 1},
        {"Well": "A", "Port": 2},
        {"Well": "C", "Port": 1},
    ]


def test_filter_sleeves_by_wells_empty_selection_returns_no_rows() -> None:
    df = pd.DataFrame({"Well": ["A"], "Port": [1]})
    assert filter_sleeves_by_wells(df, []).empty


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

from __future__ import annotations

import math
import pandas as pd

from zipfile import ZipFile

from core.exporter import StreamingCsvExporter, StreamingXlsxExporter, default_extraction_output_path, export_csv
from core.xlsx_preview import read_xlsx_preview


def test_export_csv_creates_file(tmp_path) -> None:
    path = tmp_path / "out.csv"
    export_csv(pd.DataFrame({"A": [1]}), path)
    assert path.exists()
    assert "A" in path.read_text(encoding="utf-8-sig")


def test_streaming_csv_exporter_writes_rows(tmp_path) -> None:
    path = tmp_path / "stream.csv"
    with StreamingCsvExporter(path, ["A", "B"]) as exporter:
        exporter.write_row({"A": 1, "B": 2})
        exporter.write_rows([{"A": 3, "B": 4}])
    text = path.read_text(encoding="utf-8-sig")
    assert "A,B" in text
    assert "1,2" in text
    assert "3,4" in text


def test_streaming_xlsx_exporter_writes_xml_package(tmp_path) -> None:
    path = tmp_path / "stream.xlsx"
    with StreamingXlsxExporter(path, ["A", "B"]) as exporter:
        exporter.write_row({"A": "x", "B": 2})
    with ZipFile(path) as package:
        names = set(package.namelist())
        sheet = package.read("xl/worksheets/sheet1.xml").decode("utf-8")
        shared = package.read("xl/sharedStrings.xml").decode("utf-8")
    assert "[Content_Types].xml" in names
    assert "xl/workbook.xml" in names
    assert "xl/worksheets/sheet1.xml" in names
    assert "<t>x</t>" in shared
    assert "<v>2</v>" in sheet
    assert '<col min="1" max="2" width="14" customWidth="1"/>' in sheet
    assert '<row r="1" ht="45" customHeight="1">' in sheet
    assert '<c r="A1" s="1" t="s">' in sheet
    preview = read_xlsx_preview(path)
    assert preview.headers == ["A", "B"]
    assert preview.rows == [["x", "2"]]


def test_streaming_xlsx_exporter_header_style_wraps_and_centers(tmp_path) -> None:
    path = tmp_path / "styled.xlsx"
    with StreamingXlsxExporter(path, ["Long Header"]) as exporter:
        exporter.write_row({"Long Header": 1})
    with ZipFile(path) as package:
        styles = package.read("xl/styles.xml").decode("utf-8")
    assert '<cellXfs count="2">' in styles
    assert '<alignment horizontal="center" vertical="center" wrapText="1"/>' in styles


def test_default_extraction_output_path_next_to_sleeves() -> None:
    assert str(default_extraction_output_path("C:/data/Sleeves_coord.xlsx")).endswith("Sleeves_coord_extracted.xlsx")


def test_streaming_xlsx_exporter_writes_nan_as_blank_cell(tmp_path) -> None:
    path = tmp_path / "nan.xlsx"
    with StreamingXlsxExporter(path, ["A"]) as exporter:
        exporter.write_row({"A": math.nan})
    with ZipFile(path) as package:
        sheet = package.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert ">nan<" not in sheet
    assert '<c r="A2"/>' in sheet


def test_streaming_xlsx_exporter_writes_int_nodata_as_blank_cell(tmp_path) -> None:
    path = tmp_path / "nodata.xlsx"
    with StreamingXlsxExporter(path, ["A", "B"]) as exporter:
        exporter.write_row({"A": 2147483647.0, "B": -2147483648})
    with ZipFile(path) as package:
        sheet = package.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "2147483647" not in sheet
    assert "-2147483648" not in sheet
    assert '<c r="A2"/>' in sheet
    assert '<c r="B2"/>' in sheet


def test_streaming_csv_exporter_writes_int_nodata_as_blank(tmp_path) -> None:
    path = tmp_path / "nodata.csv"
    with StreamingCsvExporter(path, ["A", "B", "C"]) as exporter:
        exporter.write_row({"A": 2147483647, "B": -2147483648, "C": 7})
    text = path.read_text(encoding="utf-8-sig")
    assert "2147483647" not in text
    assert "-2147483648" not in text
    assert ",,7" in text

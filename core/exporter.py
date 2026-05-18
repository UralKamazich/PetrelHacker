from __future__ import annotations

import csv
from datetime import date, datetime
from html import escape
from pathlib import Path
import tempfile
from typing import Iterable
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd


EXCEL_ROW_LIMIT = 1_048_576


def export_csv(df: pd.DataFrame, path: str | Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")


def export_xlsx(df: pd.DataFrame, path: str | Path) -> None:
    if len(df) > EXCEL_ROW_LIMIT:
        raise ValueError(f"DataFrame has {len(df)} rows, exceeding Excel limit {EXCEL_ROW_LIMIT}.")
    with StreamingXlsxExporter(path, list(df.columns)) as exporter:
        exporter.write_rows(df.to_dict(orient="records"))


def export_parquet(df: pd.DataFrame, path: str | Path) -> None:
    df.to_parquet(path, index=False)


class StreamingCsvExporter:
    def __init__(self, path: str | Path, columns: list[str]) -> None:
        self.path = Path(path)
        self.columns = columns
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(self._file, fieldnames=self.columns, extrasaction="ignore")
        self._writer.writeheader()
        self.rows_written = 0

    def write_rows(self, rows: Iterable[dict]) -> None:
        for row in rows:
            self._writer.writerow(row)
            self.rows_written += 1

    def write_row(self, row: dict) -> None:
        self._writer.writerow(row)
        self.rows_written += 1

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "StreamingCsvExporter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class StreamingXlsxExporter:
    """Minimal streaming XLSX writer based on XML parts in a ZIP package."""

    def __init__(self, path: str | Path, columns: list[str], sheet_name: str = "Extraction") -> None:
        self.path = Path(path)
        self.columns = columns
        self.sheet_name = sheet_name[:31] or "Sheet1"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", newline="", suffix=".xml")
        self._sheet_temp_path = Path(temp.name)
        self._sheet = temp
        self._row_index = 0
        self.rows_written = 0
        self._closed = False
        self._write_sheet_start()
        self._write_row({column: column for column in self.columns}, is_header=True)

    def write_rows(self, rows: Iterable[dict]) -> None:
        for row in rows:
            self.write_row(row)

    def write_row(self, row: dict) -> None:
        self._write_row(row, is_header=False)
        self.rows_written += 1

    def close(self) -> None:
        if self._closed:
            return
        self._sheet.write("</sheetData></worksheet>")
        self._sheet.close()
        self._write_package()
        self._sheet_temp_path.unlink(missing_ok=True)
        self._closed = True

    def __enter__(self) -> "StreamingXlsxExporter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _write_sheet_start(self) -> None:
        self._sheet.write(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheetData>"
        )

    def _write_row(self, row: dict, *, is_header: bool) -> None:
        self._row_index += 1
        if self._row_index > EXCEL_ROW_LIMIT:
            raise ValueError(f"XLSX row limit exceeded: {EXCEL_ROW_LIMIT}")
        self._sheet.write(f'<row r="{self._row_index}">')
        for col_index, column in enumerate(self.columns, start=1):
            value = column if is_header else row.get(column, "")
            self._sheet.write(_cell_xml(self._row_index, col_index, value))
        self._sheet.write("</row>")

    def _write_package(self) -> None:
        with ZipFile(self.path, "w", compression=ZIP_DEFLATED) as package:
            package.writestr("[Content_Types].xml", _content_types_xml())
            package.writestr("_rels/.rels", _root_rels_xml())
            package.writestr("xl/workbook.xml", _workbook_xml(self.sheet_name))
            package.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
            package.writestr("xl/styles.xml", _styles_xml())
            package.write(self._sheet_temp_path, "xl/worksheets/sheet1.xml")


def default_extraction_output_path(sleeves_path: str | Path) -> Path:
    source = Path(sleeves_path)
    return source.with_name(f"{source.stem}_extracted.xlsx")


def _cell_xml(row: int, col: int, value: object) -> str:
    ref = f"{_excel_column_name(col)}{row}"
    if value is None or value == "":
        return f'<c r="{ref}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    text = escape(str(value), quote=False)
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _excel_column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheet_name: str) -> str:
    safe_name = escape(sheet_name, quote=True)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        f'<sheet name="{safe_name}" sheetId="1" r:id="rId1"/>'
        "</sheets>"
        "</workbook>"
    )


def _workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        "</styleSheet>"
    )

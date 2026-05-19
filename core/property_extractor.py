from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from core.exporter import StreamingCsvExporter, StreamingXlsxExporter
from core.grid_indexer import FastGridIndexer
from core.resqml_reader import PropertyInfo, ResqmlReader


ProgressCallback = Callable[[int, int], None]
LogCallback = Callable[[str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class ExtractionSettings:
    sampling_mode: str = "fast"
    skip_inactive: bool = True
    batch_size: int = 500
    selected_property_uuids: list[str] = field(default_factory=list)
    well_col: str = "Well"
    port_col: str = "Port"
    x_col: str = "X"
    y_col: str = "Y"


@dataclass
class ExtractionStats:
    sleeves_total: int = 0
    sleeves_inside_grid: int = 0
    sleeves_outside_grid: int = 0
    extracted_rows: int = 0
    skipped_inactive_cells: int = 0
    warnings: list[str] = field(default_factory=list)
    started: datetime | None = None
    finished: datetime | None = None


class PropertyExtractor:
    def __init__(
        self,
        reader: ResqmlReader,
        indexer: FastGridIndexer,
        settings: ExtractionSettings,
    ) -> None:
        self.reader = reader
        self.indexer = indexer
        self.settings = settings

    def extract_to_csv(
        self,
        sleeves_df: pd.DataFrame,
        output_path: str | Path,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        cancel_callback: CancelCallback | None = None,
    ) -> ExtractionStats:
        return self._extract(
            sleeves_df=sleeves_df,
            output_path=output_path,
            exporter_cls=StreamingCsvExporter,
            output_label="CSV",
            progress_callback=progress_callback,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )

    def extract_to_xlsx(
        self,
        sleeves_df: pd.DataFrame,
        output_path: str | Path,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        cancel_callback: CancelCallback | None = None,
    ) -> ExtractionStats:
        return self._extract(
            sleeves_df=sleeves_df,
            output_path=output_path,
            exporter_cls=StreamingXlsxExporter,
            output_label="XLSX",
            progress_callback=progress_callback,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )

    def _extract(
        self,
        sleeves_df: pd.DataFrame,
        output_path: str | Path,
        exporter_cls,
        output_label: str,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        cancel_callback: CancelCallback | None = None,
    ) -> ExtractionStats:
        stats = ExtractionStats(sleeves_total=len(sleeves_df), started=datetime.now())
        selected_properties = self._selected_properties()
        columns = self._output_columns(selected_properties)

        if self.settings.sampling_mode != "fast":
            raise NotImplementedError("Only fast sampling mode is implemented in MVP.")

        self._log(log_callback, f"Selected properties: {', '.join(prop.title for prop in selected_properties)}")
        self._log(log_callback, f"Writing {output_label}: {output_path}")

        with exporter_cls(output_path, columns) as exporter:
            for sleeve_index, sleeve in enumerate(sleeves_df.itertuples(index=False), start=1):
                if cancel_callback and cancel_callback():
                    stats.warnings.append("Extraction cancelled by user.")
                    break

                well = self._row_value(sleeve, self.settings.well_col)
                port = self._row_value(sleeve, self.settings.port_col)
                legacy_id = self._row_value(sleeve, "Sleeve_ID")
                display_id = f"{well}_{port}" if well != "" or port != "" else str(legacy_id)
                x = float(getattr(sleeve, self.settings.x_col))
                y = float(getattr(sleeve, self.settings.y_col))
                match = self.indexer.find_column(x, y)
                if match is None:
                    stats.sleeves_outside_grid += 1
                    stats.warnings.append(f"Sleeve {display_id} is outside grid footprint.")
                    self._log(log_callback, f"Sleeve outside grid: {display_id}")
                    self._progress(progress_callback, sleeve_index, stats.sleeves_total)
                    continue

                stats.sleeves_inside_grid += 1
                property_columns = {
                    prop.title: self.reader.get_property_column_values(prop.uuid, match.i, match.j)
                    for prop in selected_properties
                }
                active_column = self.reader.get_cell_active_column(match.i, match.j)
                geometry_column = self.reader.get_cell_geometry_column(match.i, match.j)
                rows = []
                for i, j, k in self.indexer.vertical_cells(x, y):
                    is_active = True if active_column is None else bool(active_column[k])
                    if self.settings.skip_inactive and not is_active:
                        stats.skipped_inactive_cells += 1
                        continue

                    row = {
                        "Well": well,
                        "Port": port,
                        "X": x,
                        "Y": y,
                        "I": i + 1,
                        "J": j + 1,
                        "K": k + 1,
                        "IsActive": is_active,
                        "TVD_top": geometry_column["TVD_top"][k],
                        "TVD_base": geometry_column["TVD_base"][k],
                        "CellHeight": geometry_column["CellHeight"][k],
                        "CellSizeI": geometry_column["CellSizeI"][k],
                        "CellSizeJ": geometry_column["CellSizeJ"][k],
                        "CellAreaXY": geometry_column["CellAreaXY"][k],
                    }
                    for prop in selected_properties:
                        value = property_columns[prop.title][k]
                        row[prop.title] = value.item() if hasattr(value, "item") else value
                    rows.append(row)

                exporter.write_rows(rows)
                stats.extracted_rows += len(rows)
                self._log(log_callback, f"{display_id}: wrote {len(rows)} rows")
                self._progress(progress_callback, sleeve_index, stats.sleeves_total)

        stats.finished = datetime.now()
        return stats

    def _selected_properties(self) -> list[PropertyInfo]:
        selected = set(self.settings.selected_property_uuids)
        properties = [prop for prop in self.reader.list_properties() if prop.uuid in selected]
        if not properties:
            raise ValueError("No selected properties found.")
        return properties

    @staticmethod
    def _output_columns(properties: list[PropertyInfo]) -> list[str]:
        return [
            "Well",
            "Port",
            "X",
            "Y",
            "I",
            "J",
            "K",
            "IsActive",
            "TVD_top",
            "TVD_base",
            "CellHeight",
            "CellSizeI",
            "CellSizeJ",
            "CellAreaXY",
        ] + [prop.title for prop in properties]

    @staticmethod
    def _row_value(row, field: str):
        return getattr(row, field, "")

    @staticmethod
    def _log(callback: LogCallback | None, message: str) -> None:
        if callback:
            callback(message)

    @staticmethod
    def _progress(callback: ProgressCallback | None, current: int, total: int) -> None:
        if callback:
            callback(current, total)


def write_extraction_log(
    path: str | Path,
    *,
    epc_path: str | Path,
    h5_path: str | Path | None,
    grid_title: str,
    grid_uuid: str,
    grid_shape: tuple[int | None, int | None, int | None],
    selected_properties: list[str],
    sleeves_path: str | Path,
    output_path: str | Path,
    settings: ExtractionSettings,
    stats: ExtractionStats,
) -> None:
    lines = [
        f"EPC path: {epc_path}",
        f"H5 path: {h5_path or ''}",
        f"Grid title: {grid_title}",
        f"Grid UUID: {grid_uuid}",
        f"Grid shape NI/NJ/NK: {grid_shape[0]}/{grid_shape[1]}/{grid_shape[2]}",
        f"Selected properties: {', '.join(selected_properties)}",
        f"Input sleeves file: {sleeves_path}",
        f"Well column: {settings.well_col}",
        f"Port column: {settings.port_col}",
        f"X column: {settings.x_col}",
        f"Y column: {settings.y_col}",
        f"Sampling mode: {settings.sampling_mode}",
        f"Skip inactive: {settings.skip_inactive}",
        f"Output file: {output_path}",
        f"Started: {stats.started}",
        f"Finished: {stats.finished}",
        f"Number of sleeves: {stats.sleeves_total}",
        f"Sleeves inside grid: {stats.sleeves_inside_grid}",
        f"Sleeves outside grid: {stats.sleeves_outside_grid}",
        f"Extracted rows: {stats.extracted_rows}",
        f"Skipped inactive cells: {stats.skipped_inactive_cells}",
        "Warnings:",
    ]
    lines.extend(f"- {warning}" for warning in stats.warnings)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

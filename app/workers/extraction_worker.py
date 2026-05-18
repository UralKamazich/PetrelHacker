from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib.util
import sys
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from core.grid_indexer import FastGridIndexer
from core.property_extractor import ExtractionSettings, ExtractionStats, PropertyExtractor, write_extraction_log
from core.resqml_reader import ResqmlReader
from core.sleeves_loader import load_sleeves_table, validate_sleeves_table


@dataclass(frozen=True)
class ExtractionRequest:
    epc_path: str
    sleeves_path: str
    output_path: str
    selected_property_uuids: list[str]
    skip_inactive: bool


@dataclass(frozen=True)
class ExtractionResult:
    output_path: str
    log_path: str
    stats: ExtractionStats


class ExtractionWorker(QObject):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str, str)

    def __init__(self, request: ExtractionRequest) -> None:
        super().__init__()
        self.request = request
        self._cancel_requested = False

    @Slot()
    def run(self) -> None:
        try:
            self._check_runtime_dependencies()
            reader = ResqmlReader(self.request.epc_path)
            self.log.emit("Opening RESQML model...")
            reader.open()
            grids = reader.list_grids()
            if not grids:
                raise ValueError("No grids found in EPC.")
            grid = grids[0]
            reader.select_grid(grid.uuid)

            self.log.emit("Loading sleeves table...")
            sleeves = load_sleeves_table(self.request.sleeves_path)
            warnings = validate_sleeves_table(sleeves)
            for warning in warnings:
                self.log.emit(f"Warning: {warning}")

            self.log.emit("Building fast grid index...")
            indexer = FastGridIndexer(reader, grid)
            indexer.build_column_index()

            settings = ExtractionSettings(
                sampling_mode="fast",
                skip_inactive=self.request.skip_inactive,
                selected_property_uuids=self.request.selected_property_uuids,
            )
            extractor = PropertyExtractor(reader, indexer, settings)

            def progress_callback(current: int, total: int) -> None:
                value = int((current / total) * 100) if total else 0
                self.progress.emit(value)

            stats = extractor.extract_to_xlsx(
                sleeves,
                output_path=self.request.output_path,
                progress_callback=progress_callback,
                log_callback=self.log.emit,
                cancel_callback=lambda: self._cancel_requested,
            )
            selected_titles = [
                prop.title
                for prop in reader.list_properties()
                if prop.uuid in set(self.request.selected_property_uuids)
            ]
            log_path = Path(self.request.output_path).with_name("extraction_log.txt")
            write_extraction_log(
                log_path,
                epc_path=self.request.epc_path,
                h5_path=reader.h5_path,
                grid_title=grid.title,
                grid_uuid=grid.uuid,
                grid_shape=reader.get_grid_shape(),
                selected_properties=selected_titles,
                sleeves_path=self.request.sleeves_path,
                output_path=self.request.output_path,
                settings=settings,
                stats=stats,
            )
            self.finished.emit(ExtractionResult(str(self.request.output_path), str(log_path), stats))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc), traceback.format_exc())

    @Slot()
    def cancel(self) -> None:
        self._cancel_requested = True

    def _check_runtime_dependencies(self) -> None:
        self.log.emit(f"Python: {sys.executable}")
        missing = [name for name in ("h5py", "numpy", "pandas") if importlib.util.find_spec(name) is None]
        if missing:
            raise RuntimeError(
                "Missing Python package(s): "
                + ", ".join(missing)
                + ". Install them for this interpreter with: "
                + f'"{sys.executable}" -m pip install -r requirements.txt'
            )

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib.util
import errno
import sys
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from core.grid_indexer import FastGridIndexer
from core.model_reader import open_model_reader
from core.multi_model_extractor import ExtractionModelSpec, MultiModelPropertyExtractor
from core.output_planner import choose_output_plan
from core.property_extractor import ExtractionSettings, ExtractionStats, PropertyExtractor, write_extraction_log
from core.sleeves_loader import load_sleeves_table, validate_sleeves_table


@dataclass(frozen=True)
class ExtractionRequest:
    epc_path: str
    sleeves_path: str
    output_path: str
    selected_property_uuids: list[str]
    skip_inactive: bool
    model_specs: list[ExtractionModelSpec] | None = None


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
            if self._use_multi_model_extractor():
                self._run_multi_model()
            else:
                self._run_single_model()
        except PermissionError as exc:
            self.failed.emit(_permission_error_message(exc), traceback.format_exc())
        except OSError as exc:
            if exc.errno == errno.EACCES:
                self.failed.emit(_permission_error_message(exc), traceback.format_exc())
                return
            self.failed.emit(str(exc), traceback.format_exc())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc), traceback.format_exc())

    def _run_single_model(self) -> None:
        self.log.emit("Opening model...")
        reader = open_model_reader(self.request.epc_path)
        grids = reader.list_grids()
        if not grids:
            raise ValueError("No grids found in model.")
        grid = grids[0]
        reader.select_grid(grid.uuid)
        if getattr(reader, "backend", "") == "rescue":
            self.log.emit(
                "Warning: Rescue support decodes compact property streams and uses regular XY indexing; "
                "TVD cell geometry is approximated from decoded per-column Rescue Z centers."
            )

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
        output_plan = choose_output_plan(
            self.request.output_path,
            sleeve_count=len(sleeves),
            nk=reader.get_grid_shape()[2],
        )
        if output_plan.warning:
            self.log.emit(f"Warning: {output_plan.warning}")

        def progress_callback(current: int, total: int) -> None:
            value = int((current / total) * 100) if total else 0
            self.progress.emit(value)

        extract = extractor.extract_to_csv if output_plan.format == "CSV" else extractor.extract_to_xlsx
        stats = extract(
            sleeves,
            output_path=output_plan.path,
            progress_callback=progress_callback,
            log_callback=self.log.emit,
            cancel_callback=lambda: self._cancel_requested,
        )
        if output_plan.warning:
            stats.warnings.append(output_plan.warning)
        selected_titles = [
            prop.title
            for prop in reader.list_properties()
            if prop.uuid in set(self.request.selected_property_uuids)
        ]
        log_path = output_plan.path.with_name("extraction_log.txt")
        write_extraction_log(
            log_path,
            epc_path=self.request.epc_path,
            h5_path=reader.h5_path,
            grid_title=grid.title,
            grid_uuid=grid.uuid,
            grid_shape=reader.get_grid_shape(),
            selected_properties=selected_titles,
            sleeves_path=self.request.sleeves_path,
            output_path=output_plan.path,
            settings=settings,
            stats=stats,
        )
        self.finished.emit(ExtractionResult(str(output_plan.path), str(log_path), stats))

    def _run_multi_model(self) -> None:
        self.log.emit("Loading sleeves table...")
        sleeves = load_sleeves_table(self.request.sleeves_path)
        warnings = validate_sleeves_table(sleeves)
        for warning in warnings:
            self.log.emit(f"Warning: {warning}")

        specs = self.request.model_specs or [
            ExtractionModelSpec(path=self.request.epc_path, selected_property_uuids=self.request.selected_property_uuids)
        ]
        extractor = MultiModelPropertyExtractor(specs, skip_inactive=self.request.skip_inactive)
        extractor.open(log_callback=self.log.emit)
        metadata = extractor.metadata
        if metadata is None:
            raise ValueError("Model metadata was not initialized.")

        output_plan = choose_output_plan(
            self.request.output_path,
            sleeve_count=len(sleeves),
            nk=metadata.primary_grid_shape[2],
        )
        if output_plan.warning:
            self.log.emit(f"Warning: {output_plan.warning}")

        def progress_callback(current: int, total: int) -> None:
            value = int((current / total) * 100) if total else 0
            self.progress.emit(value)

        extract = extractor.extract_to_csv if output_plan.format == "CSV" else extractor.extract_to_xlsx
        stats = extract(
            sleeves,
            output_path=output_plan.path,
            progress_callback=progress_callback,
            log_callback=self.log.emit,
            cancel_callback=lambda: self._cancel_requested,
        )
        if output_plan.warning:
            stats.warnings.append(output_plan.warning)

        settings = ExtractionSettings(
            sampling_mode="fast",
            skip_inactive=self.request.skip_inactive,
            selected_property_uuids=self.request.selected_property_uuids,
        )
        log_path = output_plan.path.with_name("extraction_log.txt")
        write_extraction_log(
            log_path,
            epc_path="; ".join(spec.path for spec in specs),
            h5_path=metadata.primary_h5_path,
            grid_title=metadata.primary_grid_title,
            grid_uuid=metadata.primary_grid_uuid,
            grid_shape=metadata.primary_grid_shape,
            selected_properties=metadata.selected_property_titles,
            sleeves_path=self.request.sleeves_path,
            output_path=output_plan.path,
            settings=settings,
            stats=stats,
        )
        self.finished.emit(ExtractionResult(str(output_plan.path), str(log_path), stats))

    def _use_multi_model_extractor(self) -> bool:
        specs = self.request.model_specs or []
        if len(specs) > 1:
            return True
        return any(abs(spec.depth_offset) > 0 for spec in specs)

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


def _permission_error_message(exc: OSError) -> str:
    path = getattr(exc, "filename", None)
    if path:
        return f"Cannot write output file. Close it in Excel or choose another path: {path}"
    return "Cannot write output file. Close it in Excel or choose another output path."

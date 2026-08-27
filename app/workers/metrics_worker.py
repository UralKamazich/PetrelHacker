from __future__ import annotations

from dataclasses import dataclass
import errno
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from core.interval_metrics import (
    IntervalMetricSettings,
    calculate_interval_metrics,
    write_interval_metrics_description,
    write_interval_metrics_xlsx,
)
from core.table_io import read_table


@dataclass(frozen=True)
class MetricsRequest:
    extracted_path: str
    intervals_path: str
    output_path: str
    ntg_column: str | None
    poro_column: str | None
    perm_column: str | None
    lithology_column: str | None
    reservoir_values: list[str]
    property_columns: list[str]
    metric_keys: list[str]


@dataclass(frozen=True)
class MetricsResult:
    output_path: str
    description_path: str
    rows_written: int
    warnings: list[str]


class MetricsWorker(QObject):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str, str)

    def __init__(self, request: MetricsRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit(5)
            self.log.emit("Loading extracted cell table...")
            extracted = read_table(self.request.extracted_path)
            self.progress.emit(35)
            self.log.emit("Loading interval table...")
            intervals = read_table(self.request.intervals_path)
            self.progress.emit(55)

            settings = IntervalMetricSettings(
                ntg_column=self.request.ntg_column,
                poro_column=self.request.poro_column,
                perm_column=self.request.perm_column,
                lithology_column=self.request.lithology_column,
                reservoir_values={_normalize_value(value) for value in self.request.reservoir_values},
                property_columns=self.request.property_columns,
                metric_keys=self.request.metric_keys,
            )
            self.log.emit("Calculating interval metrics...")
            def metrics_progress(current: int, total: int) -> None:
                value = 55 + int((current / total) * 25) if total else 80
                self.progress.emit(min(80, max(55, value)))

            result = calculate_interval_metrics(extracted, intervals, settings, progress_callback=metrics_progress)
            for warning in result.warnings:
                self.log.emit(f"Warning: {warning}")
            self.progress.emit(80)
            self.log.emit(f"Writing metrics XLSX: {self.request.output_path}")
            write_interval_metrics_xlsx(result, self.request.output_path)
            description_path = write_interval_metrics_description(
                result,
                self.request.output_path,
                settings,
                extracted_path=self.request.extracted_path,
                intervals_path=self.request.intervals_path,
            )
            self.log.emit(f"Writing metrics description: {description_path}")
            self.progress.emit(100)
            self.finished.emit(
                MetricsResult(
                    output_path=self.request.output_path,
                    description_path=str(description_path),
                    rows_written=len(result.rows),
                    warnings=result.warnings,
                )
            )
        except PermissionError as exc:
            self.failed.emit(_permission_error_message(exc), traceback.format_exc())
        except OSError as exc:
            if exc.errno == errno.EACCES:
                self.failed.emit(_permission_error_message(exc), traceback.format_exc())
                return
            self.failed.emit(str(exc), traceback.format_exc())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc), traceback.format_exc())


def _normalize_value(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        return text[:-2]
    return text


def _permission_error_message(exc: OSError) -> str:
    path = getattr(exc, "filename", None)
    if path:
        return f"Cannot write metrics file. Close it in Excel or choose another path: {path}"
    return "Cannot write metrics file. Close it in Excel or choose another output path."

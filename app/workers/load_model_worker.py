from __future__ import annotations

from dataclasses import dataclass
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from core.model_reader import open_model_reader
from core.resqml_reader import GridInfo, PropertyInfo


@dataclass(frozen=True)
class ModelLoadResult:
    epc_path: str
    h5_path: str | None
    backend: str
    grids: list[GridInfo]
    properties: list[PropertyInfo]


class LoadModelWorker(QObject):
    finished = Signal(object)
    failed = Signal(str, str)
    log = Signal(str)

    def __init__(self, epc_path: str) -> None:
        super().__init__()
        self.epc_path = epc_path

    @Slot()
    def run(self) -> None:
        try:
            self.log.emit(f"Opening model: {self.epc_path}")
            reader = open_model_reader(self.epc_path)
            grids = reader.list_grids()
            self.log.emit(f"Found grids: {len(grids)}")
            if grids:
                reader.select_grid(grids[0].uuid)
            properties = reader.list_properties()
            self.log.emit(f"Found properties for selected grid: {len(properties)}")
            result = ModelLoadResult(
                epc_path=str(reader.epc_path),
                h5_path=str(reader.h5_path) if reader.h5_path else None,
                backend=reader.backend,
                grids=grids,
                properties=properties,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc), traceback.format_exc())

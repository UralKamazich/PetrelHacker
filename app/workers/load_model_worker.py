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
    model_index: int = 0
    label: str = "M1"
    depth_offset: float = 0.0


class LoadModelWorker(QObject):
    finished = Signal(object)
    failed = Signal(str, str)
    log = Signal(str)

    def __init__(self, epc_path: str | list[str], depth_offsets: list[float] | None = None) -> None:
        super().__init__()
        self.epc_paths = [epc_path] if isinstance(epc_path, str) else list(epc_path)
        self.depth_offsets = depth_offsets or [0.0] * len(self.epc_paths)

    @Slot()
    def run(self) -> None:
        try:
            results: list[ModelLoadResult] = []
            for index, epc_path in enumerate(self.epc_paths):
                label = f"M{index + 1}"
                self.log.emit(f"Opening model {label}: {epc_path}")
                reader = open_model_reader(epc_path)
                grids = reader.list_grids()
                self.log.emit(f"{label}: found grids: {len(grids)}")
                if grids:
                    reader.select_grid(grids[0].uuid)
                properties = reader.list_properties()
                self.log.emit(f"{label}: found properties for selected grid: {len(properties)}")
                results.append(
                    ModelLoadResult(
                        epc_path=str(reader.epc_path),
                        h5_path=str(reader.h5_path) if reader.h5_path else None,
                        backend=reader.backend,
                        grids=grids,
                        properties=properties,
                        model_index=index,
                        label=label,
                        depth_offset=self.depth_offsets[index] if index < len(self.depth_offsets) else 0.0,
                    )
                )
            self.finished.emit(results[0] if len(results) == 1 else results)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc), traceback.format_exc())

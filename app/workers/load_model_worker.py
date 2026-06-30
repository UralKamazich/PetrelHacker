from __future__ import annotations

from dataclasses import dataclass
import math
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
    summary: str = ""


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
                summary = _model_summary(label, reader, grids, properties)
                for line in summary.splitlines():
                    self.log.emit(line)
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
                        summary=summary,
                    )
                )
            self.finished.emit(results[0] if len(results) == 1 else results)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc), traceback.format_exc())


def _model_summary(label: str, reader: object, grids: list[GridInfo], properties: list[PropertyInfo]) -> str:
    lines = [f"{label}: model summary"]
    backend = getattr(reader, "backend", "")
    if backend:
        lines.append(f"  Backend: {backend}")
    for grid in grids:
        cell_count = _cell_count(grid)
        shape = f"{_fmt_int(grid.ni)} x {_fmt_int(grid.nj)} x {_fmt_int(grid.nk)}"
        cells = f", cells={cell_count:,}" if cell_count is not None else ""
        lines.append(f"  Grid: {grid.title} ({grid.grid_type or 'unknown'}), shape={shape}{cells}")
    if grids:
        size_summary = _cell_size_summary(reader, grids[0])
        if size_summary:
            lines.append(f"  Cell sizes: {size_summary}")
    datums = _safe_list_md_datums(reader)
    if datums:
        wells = sorted({getattr(datum, "well_name", "") for datum in datums if getattr(datum, "well_name", "")})
        sample = ", ".join(wells[:8])
        suffix = "..." if len(wells) > 8 else ""
        lines.append(f"  Well datums: {len(datums)} objects, {len(wells)} unique aliases ({sample}{suffix})")
    else:
        lines.append("  Well datums: not found in this model")
    lines.append(f"  Property cubes: {len(properties)}")
    for prop in properties:
        details = []
        if prop.property_kind:
            details.append(f"kind={prop.property_kind}")
        if prop.uom:
            details.append(f"uom={prop.uom}")
        if prop.shape:
            details.append("shape=" + "x".join(str(value) for value in prop.shape))
        if prop.dtype:
            details.append(f"dtype={prop.dtype}")
        tail = f" ({', '.join(details)})" if details else ""
        lines.append(f"    - {prop.title}{tail}")
    return "\n".join(lines)


def _cell_count(grid: GridInfo) -> int | None:
    if grid.ni is None or grid.nj is None or grid.nk is None:
        return None
    return int(grid.ni) * int(grid.nj) * int(grid.nk)


def _fmt_int(value: int | None) -> str:
    return "?" if value is None else str(value)


def _cell_size_summary(reader: object, grid: GridInfo) -> str:
    if grid.ni is None or grid.nj is None:
        return ""
    try:
        geometry = reader.get_cell_geometry_column(max(0, int(grid.ni) // 2), max(0, int(grid.nj) // 2))
    except Exception:
        return ""
    size_i = _first_finite(geometry.get("CellSizeI", []))
    size_j = _first_finite(geometry.get("CellSizeJ", []))
    heights = [float(value) for value in geometry.get("CellHeight", []) if _is_finite_number(value)]
    parts = []
    if size_i is not None:
        parts.append(f"I~{size_i:g} m")
    if size_j is not None:
        parts.append(f"J~{size_j:g} m")
    if heights:
        heights_sorted = sorted(heights)
        median = heights_sorted[len(heights_sorted) // 2]
        parts.append(f"K median~{median:g} m")
        parts.append(f"K min/max~{min(heights):g}/{max(heights):g} m")
    return ", ".join(parts)


def _safe_list_md_datums(reader: object) -> list[object]:
    try:
        list_md_datums = getattr(reader, "list_md_datums")
    except Exception:
        return []
    try:
        return list(list_md_datums())
    except Exception:
        return []


def _first_finite(values: object) -> float | None:
    if not isinstance(values, list):
        return None
    for value in values:
        if _is_finite_number(value):
            return float(value)
    return None


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from typing import Callable

import pandas as pd

from core.exporter import StreamingCsvExporter, StreamingXlsxExporter
from core.grid_indexer import FastGridIndexer
from core.model_reader import open_model_reader
from core.property_extractor import (
    CancelCallback,
    ExtractionStats,
    LogCallback,
    ProgressCallback,
    _cell_center as _depth_cell_center,
    _is_blank_property_value,
    _numeric_or_blank,
    _relative_depth as _depth_relative_depth,
    transform_property_value,
)
from core.resqml_reader import PropertyInfo


PORT_DEPTH_COLUMN = "TVDSS_PORT"


@dataclass(frozen=True)
class ExtractionModelSpec:
    path: str
    selected_property_uuids: list[str] = field(default_factory=list)
    depth_offset: float = 0.0
    label: str = ""


@dataclass
class MultiModelMetadata:
    primary_path: str
    primary_h5_path: str | None
    primary_grid_title: str
    primary_grid_uuid: str
    primary_grid_shape: tuple[int | None, int | None, int | None]
    selected_property_titles: list[str]


@dataclass
class ModelContext:
    spec: ExtractionModelSpec
    label: str
    reader: object
    indexer: FastGridIndexer
    properties: list[PropertyInfo]
    output_names: dict[str, str]


class MultiModelPropertyExtractor:
    def __init__(self, specs: list[ExtractionModelSpec], *, skip_inactive: bool = True) -> None:
        self.specs = [spec for spec in specs if spec.path.strip()]
        self.skip_inactive = skip_inactive
        self.contexts: list[ModelContext] = []
        self.metadata: MultiModelMetadata | None = None
        self.well_depth_datums: dict[str, float] = {}

    def open(self, log_callback: LogCallback | None = None) -> None:
        if not self.specs:
            raise ValueError("No model paths configured.")
        if not any(spec.selected_property_uuids for spec in self.specs):
            raise ValueError("Select at least one property in one model.")

        raw_contexts: list[tuple[ExtractionModelSpec, object, FastGridIndexer, list[PropertyInfo]]] = []
        well_depth_datums: dict[str, float] = {}
        selected_titles: list[str] = []
        for model_index, spec in enumerate(self.specs, start=1):
            _log(log_callback, f"Opening model {model_index}: {spec.path}")
            reader = open_model_reader(spec.path)
            grids = reader.list_grids()
            if not grids:
                raise ValueError(f"No grids found in model {model_index}: {spec.path}")
            grid = grids[0]
            reader.select_grid(grid.uuid)
            if getattr(reader, "backend", "") == "rescue":
                _log(
                    log_callback,
                    "Warning: Rescue support decodes compact property streams and uses regular XY indexing; "
                    "TVD cell geometry is approximated from decoded per-column Rescue Z centers.",
                )
            _log(log_callback, f"Building XY index for model {model_index}...")
            indexer = FastGridIndexer(reader, grid)
            indexer.build_column_index()
            selected = _selected_properties(reader.list_properties(), spec.selected_property_uuids)
            well_depth_datums.update(_well_depth_datums_from_reader(reader))
            raw_contexts.append((spec, reader, indexer, selected))
            selected_titles.extend(prop.title for prop in selected)

        title_counts: dict[str, int] = {}
        for title in selected_titles:
            title_counts[title] = title_counts.get(title, 0) + 1

        output_names_seen: set[str] = set()
        contexts: list[ModelContext] = []
        for model_index, (spec, reader, indexer, properties) in enumerate(raw_contexts, start=1):
            label = spec.label.strip() or f"M{model_index}"
            output_names: dict[str, str] = {}
            for prop in properties:
                base_name = prop.title if title_counts.get(prop.title, 0) == 1 else f"{label}_{prop.title}"
                output_names[prop.uuid] = _unique_name(base_name, output_names_seen)
            contexts.append(
                ModelContext(
                    spec=spec,
                    label=label,
                    reader=reader,
                    indexer=indexer,
                    properties=properties,
                    output_names=output_names,
                )
            )
        self.contexts = contexts
        self.well_depth_datums = well_depth_datums
        if well_depth_datums:
            _log(log_callback, f"Loaded well depth datums: {len(well_depth_datums)} aliases")

        primary_reader = contexts[0].reader
        primary_grid = primary_reader.list_grids()[0]
        primary_shape = primary_reader.get_grid_shape()
        self.metadata = MultiModelMetadata(
            primary_path=str(primary_reader.epc_path),
            primary_h5_path=str(primary_reader.h5_path) if primary_reader.h5_path else None,
            primary_grid_title=primary_grid.title,
            primary_grid_uuid=primary_grid.uuid,
            primary_grid_shape=(primary_shape[0], primary_shape[1], _max_nk(contexts)),
            selected_property_titles=[name for context in contexts for name in context.output_names.values()],
        )

    def extract_to_csv(
        self,
        sleeves_df: pd.DataFrame,
        output_path: str | Path,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        cancel_callback: CancelCallback | None = None,
    ) -> ExtractionStats:
        return self._extract(sleeves_df, output_path, StreamingCsvExporter, progress_callback, log_callback, cancel_callback)

    def extract_to_xlsx(
        self,
        sleeves_df: pd.DataFrame,
        output_path: str | Path,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        cancel_callback: CancelCallback | None = None,
    ) -> ExtractionStats:
        return self._extract(sleeves_df, output_path, StreamingXlsxExporter, progress_callback, log_callback, cancel_callback)

    def output_columns(self) -> list[str]:
        property_columns = [column for context in self.contexts for column in _property_output_columns(context)]
        return [
            "Well",
            "Port",
            "X",
            "Y",
            PORT_DEPTH_COLUMN,
            "Datum_Z",
            "Depth_KB_PORT",
            "I",
            "J",
            "K",
            "IsActive",
            "TVDSS_top",
            "TVDSS_base",
            "TVDSS_center",
            "TVD_top",
            "TVD_base",
            "TVD_center",
            "Depth_KB_top",
            "Depth_KB_base",
            "Depth_KB_center",
            "Rel_TVD_top",
            "Rel_TVD_base",
            "Rel_TVD_center",
            "CellHeight",
            "CellSizeI",
            "CellSizeJ",
            "CellAreaXY",
        ] + property_columns

    def _extract(
        self,
        sleeves_df: pd.DataFrame,
        output_path: str | Path,
        exporter_cls,
        progress_callback: ProgressCallback | None,
        log_callback: LogCallback | None,
        cancel_callback: CancelCallback | None,
    ) -> ExtractionStats:
        if not self.contexts:
            self.open(log_callback)
        stats = ExtractionStats(sleeves_total=len(sleeves_df), started=datetime.now())
        property_columns = [name for context in self.contexts for name in context.output_names.values()]
        _log(log_callback, f"Selected properties: {', '.join(property_columns)}")
        _log(log_callback, f"Writing output: {output_path}")

        with exporter_cls(output_path, self.output_columns()) as exporter:
            for sleeve_index, sleeve in enumerate(sleeves_df.itertuples(index=False), start=1):
                if cancel_callback and cancel_callback():
                    stats.warnings.append("Extraction cancelled by user.")
                    break

                well = _row_value(sleeve, "Well")
                port = _row_value(sleeve, "Port")
                legacy_id = _row_value(sleeve, "Sleeve_ID")
                display_id = f"{well}_{port}" if well != "" or port != "" else str(legacy_id)
                x = float(getattr(sleeve, "X"))
                y = float(getattr(sleeve, "Y"))
                port_tvd = _numeric_or_blank(getattr(sleeve, PORT_DEPTH_COLUMN, ""))
                datum_z = _datum_for_well(self.well_depth_datums, well)
                model_columns = [_load_model_column(context, x, y) for context in self.contexts]
                if not any(model_columns):
                    stats.sleeves_outside_grid += 1
                    stats.warnings.append(f"Sleeve {display_id} is outside all model grid footprints.")
                    _log(log_callback, f"Sleeve outside all model grids: {display_id}")
                    _progress(progress_callback, sleeve_index, stats.sleeves_total)
                    continue

                stats.sleeves_inside_grid += 1
                rows = []
                depth_segments = _union_depth_segments([column for column in model_columns if column is not None])
                for segment_index, (target_top, target_base) in enumerate(depth_segments, start=1):
                    geometry_source = _geometry_source_for_segment(model_columns, target_top, target_base)
                    active_values = [
                        _is_active(column, k, _blank_values(context))
                        for context, column in zip(self.contexts, model_columns, strict=False)
                        if column is not None
                        for k in [_find_depth_k(column.geometry, (target_top + target_base) / 2.0)]
                        if k is not None
                    ]
                    is_active = any(active_values)
                    row = {
                        "Well": well,
                        "Port": port,
                        "X": x,
                        "Y": y,
                        PORT_DEPTH_COLUMN: port_tvd,
                        "Datum_Z": datum_z,
                        "Depth_KB_PORT": _depth_kb(port_tvd, datum_z),
                        "I": "" if geometry_source is None else geometry_source[0].i + 1,
                        "J": "" if geometry_source is None else geometry_source[0].j + 1,
                        "K": segment_index,
                        "IsActive": is_active,
                        "TVDSS_top": target_top,
                        "TVDSS_base": target_base,
                        "TVDSS_center": _depth_cell_center(target_top, target_base),
                        "TVD_top": target_top,
                        "TVD_base": target_base,
                        "TVD_center": _depth_cell_center(target_top, target_base),
                        "Depth_KB_top": _depth_kb(target_top, datum_z),
                        "Depth_KB_base": _depth_kb(target_base, datum_z),
                        "Depth_KB_center": _depth_kb(_depth_cell_center(target_top, target_base), datum_z),
                        "Rel_TVD_top": _depth_relative_depth(target_top, port_tvd),
                        "Rel_TVD_base": _depth_relative_depth(target_base, port_tvd),
                        "Rel_TVD_center": _depth_relative_depth(_depth_cell_center(target_top, target_base), port_tvd),
                        "CellHeight": abs(target_base - target_top),
                        "CellSizeI": "" if geometry_source is None else geometry_source[1].get("CellSizeI", ""),
                        "CellSizeJ": "" if geometry_source is None else geometry_source[1].get("CellSizeJ", ""),
                        "CellAreaXY": "" if geometry_source is None else geometry_source[1].get("CellAreaXY", ""),
                    }

                    any_property_value = False
                    for context, column in zip(self.contexts, model_columns, strict=False):
                        secondary_values = _blank_values_with_diagnostics(context)
                        if column is not None:
                            secondary_values = _property_values_for_interval(
                                context,
                                column,
                                target_top,
                                target_base,
                                skip_inactive=self.skip_inactive,
                                datum_z=datum_z,
                                allow_nearest=False,
                            )
                        property_value_names = set(context.output_names.values())
                        any_property_value = any_property_value or any(
                            not _is_blank_property_value(secondary_values.get(name, ""))
                            for name in property_value_names
                        )
                        row.update(secondary_values)

                    if self.skip_inactive and not is_active and not any_property_value:
                        stats.skipped_inactive_cells += 1
                        continue
                    rows.append(row)

                exporter.write_rows(rows)
                stats.extracted_rows += len(rows)
                _log(log_callback, f"{display_id}: wrote {len(rows)} rows")
                _progress(progress_callback, sleeve_index, stats.sleeves_total)

        stats.finished = datetime.now()
        return stats


@dataclass
class LoadedColumn:
    i: int
    j: int
    geometry: dict[str, list[float]]
    active: object | None
    property_columns: dict[str, object]


def _load_model_column(context: ModelContext, x: float, y: float) -> LoadedColumn | None:
    match = context.indexer.find_column(x, y)
    if match is None:
        return None
    geometry = context.reader.get_cell_geometry_column(match.i, match.j)
    if context.spec.depth_offset:
        geometry = _offset_geometry(geometry, context.spec.depth_offset)
    return LoadedColumn(
        i=match.i,
        j=match.j,
        geometry=geometry,
        active=context.reader.get_cell_active_column(match.i, match.j),
        property_columns={
            prop.uuid: context.reader.get_property_column_values(prop.uuid, match.i, match.j)
            for prop in context.properties
        },
    )


def _property_values_for_k(context: ModelContext, column: LoadedColumn, k: int) -> dict[str, object]:
    values: dict[str, object] = {}
    for prop in context.properties:
        raw_value = column.property_columns[prop.uuid][k]
        raw_value = raw_value.item() if hasattr(raw_value, "item") else raw_value
        values[context.output_names[prop.uuid]] = transform_property_value(prop, raw_value)
    return values


def _property_values_for_interval(
    context: ModelContext,
    column: LoadedColumn,
    target_top: float,
    target_base: float,
    *,
    skip_inactive: bool,
    datum_z: float | str = "",
    allow_nearest: bool = True,
) -> dict[str, object]:
    samples: dict[str, list[tuple[object, float, int]]] = {prop.uuid: [] for prop in context.properties}
    for k, weight in _overlapping_cells(column.geometry, target_top, target_base):
        values = _property_values_for_k(context, column, k)
        if skip_inactive and not _is_active(column, k, values):
            continue
        for prop in context.properties:
            output_name = context.output_names[prop.uuid]
            value = values.get(output_name, "")
            if not _is_blank_property_value(value):
                samples[prop.uuid].append((value, weight, k))

    if not any(samples.values()):
        if not allow_nearest:
            return _blank_values_with_diagnostics(context)
        nearest_k = _find_depth_k(column.geometry, (min(target_top, target_base) + max(target_top, target_base)) / 2.0)
        if nearest_k is None:
            return _blank_values_with_diagnostics(context)
        values = _property_values_for_k(context, column, nearest_k)
        if skip_inactive and not _is_active(column, nearest_k, values):
            return _blank_values_with_diagnostics(context)
        values.update(_property_diagnostics_for_k(context, column, nearest_k, values, datum_z))
        return values

    result: dict[str, object] = {}
    for prop in context.properties:
        output_name = context.output_names[prop.uuid]
        prop_samples = samples[prop.uuid]
        result[output_name] = _aggregate_property_samples(
            prop,
            [(value, weight) for value, weight, _k in prop_samples],
        )
        result.update(_property_diagnostics_for_samples(context, column, prop, prop_samples, datum_z))
    return result


def _aggregate_property_samples(prop: PropertyInfo, samples: list[tuple[object, float]]) -> object:
    if not samples:
        return ""
    if _is_discrete_property(prop):
        return _dominant_value(samples)
    numeric_values: list[tuple[float, float]] = []
    for value, weight in samples:
        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if not pd.isna(numeric):
            numeric_values.append((float(numeric), float(weight)))
    if numeric_values:
        total_weight = sum(weight for _value, weight in numeric_values)
        if total_weight > 0.0:
            return sum(value * weight for value, weight in numeric_values) / total_weight
    return _dominant_value(samples)


def _dominant_value(samples: list[tuple[object, float]]) -> object:
    weights: dict[object, float] = {}
    first_seen: dict[object, int] = {}
    for index, (value, weight) in enumerate(samples):
        weights[value] = weights.get(value, 0.0) + float(weight)
        first_seen.setdefault(value, index)
    return max(weights, key=lambda value: (weights[value], -first_seen[value]))


def _is_discrete_property(prop: PropertyInfo) -> bool:
    text = " ".join(
        str(value or "").lower()
        for value in (prop.property_type, prop.property_kind, prop.uom, prop.title)
    )
    return "discrete" in text or "categorical" in text or "lith" in text or "facies" in text


def _blank_values(context: ModelContext) -> dict[str, str]:
    return {name: "" for name in context.output_names.values()}


def _blank_values_with_diagnostics(context: ModelContext) -> dict[str, str]:
    values = _blank_values(context)
    values.update(_blank_property_diagnostics(context))
    return values


def _blank_property_diagnostics(context: ModelContext) -> dict[str, str]:
    blanks: dict[str, str] = {}
    for output_name in context.output_names.values():
        blanks.update(_blank_property_diagnostics_for_name(output_name))
    return blanks


def _blank_property_diagnostics_for_name(output_name: str) -> dict[str, str]:
    return {
        f"{output_name}_Model": "",
        f"{output_name}_I": "",
        f"{output_name}_J": "",
        f"{output_name}_K": "",
        f"{output_name}_TVD_center": "",
        f"{output_name}_Depth_KB": "",
    }


def _property_output_columns(context: ModelContext) -> list[str]:
    columns: list[str] = []
    for output_name in context.output_names.values():
        columns.extend(
            [
                output_name,
                f"{output_name}_Model",
                f"{output_name}_I",
                f"{output_name}_J",
                f"{output_name}_K",
                f"{output_name}_TVD_center",
                f"{output_name}_Depth_KB",
            ]
        )
    return columns


def _property_diagnostics_for_samples(
    context: ModelContext,
    column: LoadedColumn,
    prop: PropertyInfo,
    samples: list[tuple[object, float, int]],
    datum_z: float | str = "",
) -> dict[str, object]:
    output_name = context.output_names[prop.uuid]
    if not samples:
        return _blank_property_diagnostics_for_name(output_name)
    _index, (_value, _weight, k) = max(
        enumerate(samples),
        key=lambda indexed_sample: (float(indexed_sample[1][1]), -indexed_sample[0]),
    )
    return _property_diagnostics_for_property(context, column, output_name, k, _value, datum_z)


def _property_diagnostics_for_k(
    context: ModelContext,
    column: LoadedColumn,
    k: int,
    values: dict[str, object],
    datum_z: float | str = "",
) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for prop in context.properties:
        output_name = context.output_names[prop.uuid]
        diagnostics.update(
            _property_diagnostics_for_property(context, column, output_name, k, values.get(output_name, ""), datum_z)
        )
    return diagnostics


def _property_diagnostics_for_property(
    context: ModelContext,
    column: LoadedColumn,
    output_name: str,
    k: int,
    value: object,
    datum_z: float | str = "",
) -> dict[str, object]:
    if _is_blank_property_value(value):
        return _blank_property_diagnostics_for_name(output_name)
    return {
        f"{output_name}_Model": context.label,
        f"{output_name}_I": column.i + 1,
        f"{output_name}_J": column.j + 1,
        f"{output_name}_K": k + 1,
        f"{output_name}_TVD_center": _cell_center(column.geometry, k),
        f"{output_name}_Depth_KB": _depth_kb(_cell_center(column.geometry, k), datum_z),
    }


def _is_active(column: LoadedColumn, k: int, values: dict[str, object]) -> bool:
    if column.active is None:
        return any(not _is_blank_property_value(value) for value in values.values())
    return bool(column.active[k])


def _find_depth_k(geometry: dict[str, list[float]], target_center: float) -> int | None:
    containing: list[tuple[float, int]] = []
    nearest: tuple[float, int] | None = None
    for k, (top, base) in enumerate(zip(geometry["TVD_top"], geometry["TVD_base"], strict=False)):
        low = min(float(top), float(base))
        high = max(float(top), float(base))
        center = (low + high) / 2.0
        distance = abs(center - target_center)
        if low <= target_center <= high:
            containing.append((distance, k))
        if nearest is None or distance < nearest[0]:
            nearest = (distance, k)
    if containing:
        return min(containing)[1]
    if nearest is None:
        return None
    median_height = _median_cell_height(geometry)
    return nearest[1] if nearest[0] <= median_height / 2.0 else None


def _overlapping_cells(geometry: dict[str, list[float]], target_top: float, target_base: float) -> list[tuple[int, float]]:
    target_low = min(float(target_top), float(target_base))
    target_high = max(float(target_top), float(target_base))
    if target_high <= target_low:
        return []
    overlaps: list[tuple[int, float]] = []
    for k, (top, base) in enumerate(zip(geometry["TVD_top"], geometry["TVD_base"], strict=False)):
        low = min(float(top), float(base))
        high = max(float(top), float(base))
        overlap = max(0.0, min(target_high, high) - max(target_low, low))
        if overlap > 0.0:
            overlaps.append((k, overlap))
    return overlaps


def _union_depth_segments(columns: list[LoadedColumn]) -> list[tuple[float, float]]:
    boundaries: list[float] = []
    for column in columns:
        boundaries.extend(float(value) for value in column.geometry["TVD_top"])
        boundaries.extend(float(value) for value in column.geometry["TVD_base"])
    unique_boundaries = sorted(set(round(value, 6) for value in boundaries))
    return [
        (float(top), float(base))
        for top, base in zip(unique_boundaries, unique_boundaries[1:], strict=False)
        if base > top
    ]


def _geometry_source_for_segment(
    columns: list[LoadedColumn | None],
    target_top: float,
    target_base: float,
) -> tuple[LoadedColumn, dict[str, float | str]] | None:
    center = (min(target_top, target_base) + max(target_top, target_base)) / 2.0
    for column in columns:
        if column is None:
            continue
        k = _find_depth_k(column.geometry, center)
        if k is None:
            continue
        return (
            column,
            {
                "CellSizeI": _geometry_value(column.geometry, "CellSizeI", k),
                "CellSizeJ": _geometry_value(column.geometry, "CellSizeJ", k),
                "CellAreaXY": _geometry_value(column.geometry, "CellAreaXY", k),
            },
        )
    return None


def _geometry_value(geometry: dict[str, list[float]], key: str, k: int) -> float | str:
    values = geometry.get(key, [])
    return values[k] if k < len(values) else ""


def _median_cell_height(geometry: dict[str, list[float]]) -> float:
    values = pd.to_numeric(pd.Series(geometry.get("CellHeight", [])), errors="coerce").dropna()
    if len(values):
        return float(values.median())
    return 0.0


def _cell_center(geometry: dict[str, list[float]], k: int) -> float:
    top = float(geometry["TVD_top"][k])
    base = float(geometry["TVD_base"][k])
    return (min(top, base) + max(top, base)) / 2.0


def _cell_interval(geometry: dict[str, list[float]], k: int) -> tuple[float, float]:
    return float(geometry["TVD_top"][k]), float(geometry["TVD_base"][k])


def _offset_geometry(geometry: dict[str, list[float]], offset: float) -> dict[str, list[float]]:
    shifted = {key: list(values) for key, values in geometry.items()}
    shifted["TVD_top"] = [float(value) + offset for value in shifted["TVD_top"]]
    shifted["TVD_base"] = [float(value) + offset for value in shifted["TVD_base"]]
    return shifted


def _selected_properties(properties: list[PropertyInfo], selected_uuids: list[str]) -> list[PropertyInfo]:
    selected = {uuid.lower() for uuid in selected_uuids}
    return [prop for prop in properties if prop.uuid in selected]


def _well_depth_datums_from_reader(reader: object) -> dict[str, float]:
    list_md_datums = getattr(reader, "list_md_datums", None)
    if not callable(list_md_datums):
        return {}
    datums: dict[str, float] = {}
    try:
        md_datums = list_md_datums()
    except Exception:
        return {}
    for datum in md_datums:
        z = getattr(datum, "z", None)
        if z is None:
            continue
        try:
            value = float(z)
        except (TypeError, ValueError):
            continue
        for candidate in _well_key_candidates(getattr(datum, "well_name", "")):
            datums.setdefault(candidate, value)
    return datums


def _datum_for_well(datums: dict[str, float], well: object) -> float | str:
    for candidate in _well_key_candidates(str(well)):
        if candidate in datums:
            return datums[candidate]
    return ""


def _well_key_candidates(value: object) -> list[str]:
    text = _normalize_well_text(str(value))
    tokens = re.findall(r"[0-9A-Z]+", text)
    candidates: list[str] = []
    for token in tokens:
        _append_unique(candidates, token)
        match = re.search(r"\d+[A-Z]+\d+", token)
        if match:
            _append_unique(candidates, match.group(0))
    return candidates


def _normalize_well_text(value: str) -> str:
    translation = str.maketrans(
        {
            "А": "A",
            "В": "B",
            "Е": "E",
            "К": "K",
            "М": "M",
            "Н": "H",
            "О": "O",
            "Р": "P",
            "С": "C",
            "Т": "T",
            "У": "Y",
            "Х": "X",
            "а": "A",
            "в": "B",
            "е": "E",
            "к": "K",
            "м": "M",
            "н": "H",
            "о": "O",
            "р": "P",
            "с": "C",
            "т": "T",
            "у": "Y",
            "х": "X",
        }
    )
    return value.translate(translation).upper()


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _depth_kb(depth: object, datum_z: object) -> float | str:
    if _is_blank_property_value(depth) or _is_blank_property_value(datum_z):
        return ""
    try:
        return float(depth) + float(datum_z)
    except (TypeError, ValueError):
        return ""


def _max_nk(contexts: list[ModelContext]) -> int | None:
    values = [context.reader.get_grid_shape()[2] for context in contexts]
    nk_values = [int(value) for value in values if value is not None]
    return max(nk_values) if nk_values else None


def _unique_name(base_name: str, seen: set[str]) -> str:
    candidate = base_name
    suffix = 2
    while candidate in seen:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _row_value(row, field: str):
    return getattr(row, field, "")


def _log(callback: Callable[[str], None] | None, message: str) -> None:
    if callback:
        callback(message)


def _progress(callback: Callable[[int, int], None] | None, current: int, total: int) -> None:
    if callback:
        callback(current, total)

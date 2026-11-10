from __future__ import annotations

import argparse
import gzip
import hashlib
from datetime import date, datetime
from dataclasses import fields, is_dataclass
import errno
import json
import math
import os
from pathlib import Path
import shutil
import sys
import traceback
from typing import Any, Callable

import pandas as pd

from core.exporter import default_extraction_output_path
from core.interval_metrics import (
    DEFAULT_METRIC_KEYS,
    INTERVAL_BUFFER_METERS,
    IntervalMetricSettings,
    analyze_lithology_codes,
    calculate_interval_metrics,
    write_interval_metrics_description,
    write_interval_metrics_xlsx,
)
from core.model_section import extract_well_section
from core.model_reader import open_model_reader, resolve_model_path
from core.multi_model_extractor import ExtractionModelSpec, MultiModelPropertyExtractor
from core.output_planner import choose_output_plan
from core.petrel_project_reader import PetrelProjectReader, describe_petrel_project, is_petrel_project_path
from core.property_extractor import INTERVAL_BOUNDARY_COLUMNS, ExtractionSettings, write_extraction_log
from core.resqml_reader import ResqmlReader
from core.sleeves_loader import (
    apply_sleeves_column_mapping,
    filter_sleeves_by_wells,
    guess_sleeves_column_mapping,
    load_sleeves_table,
    read_sleeves_table_headers,
    read_sleeves_table_raw,
    unique_well_values,
    validate_sleeves_table,
    well_value_counts,
)
from core.section_workspace import (
    extract_workspace,
    load_section as load_workspace_section,
    save_section,
    workspace_info,
    workspace_path_for,
)
from core.table_io import read_table, read_table_headers
from core.table_merge import MergeInput, file_labels, merge_tables, write_merged_table
from core.trajectory_analysis import analyze_trajectory, interpolate_trajectory_xy


JsonDict = dict[str, Any]
CURVE_CACHE_WELL_KEY = "__petrelhacker_well_key"
CURVE_CACHE_PORT_KEY = "__petrelhacker_port_key"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PetrelHacker Electron backend bridge")
    parser.add_argument(
        "command",
        choices=(
            "load-models",
            "model-source-info",
            "preview-sleeves",
            "suggest-output",
            "extract",
            "model-coverage",
            "table-info",
            "metrics",
            "merge-tables",
            "lithology-codes",
            "curve-data",
            "curve-data-batch",
            "well-trajectories",
            "trajectory-analysis",
            "calculate-sleeve-coordinates",
            "model-section",
            "sleeve-markers",
            "load-section-boundaries",
            "save-section-boundaries",
            "save-section-cache",
            "save-section-workspace",
            "section-workspace-info",
            "load-section-workspace",
            "extract-section-workspace",
            "clear-section-cache",
        ),
    )
    args = parser.parse_args(argv)

    try:
        payload = _read_payload()
        handlers: dict[str, Callable[[JsonDict], None]] = {
            "load-models": load_models,
            "model-source-info": model_source_info,
            "preview-sleeves": preview_sleeves,
            "suggest-output": suggest_output,
            "extract": extract,
            "model-coverage": model_coverage,
            "table-info": table_info,
            "metrics": metrics,
            "merge-tables": merge_tables_command,
            "lithology-codes": lithology_codes,
            "curve-data": curve_data,
            "curve-data-batch": curve_data_batch,
            "well-trajectories": well_trajectories,
            "trajectory-analysis": trajectory_analysis,
            "calculate-sleeve-coordinates": calculate_sleeve_coordinates,
            "model-section": model_section,
            "sleeve-markers": sleeve_markers,
            "load-section-boundaries": load_section_boundaries,
            "save-section-boundaries": save_section_boundaries,
            "save-section-cache": save_section_cache,
            "save-section-workspace": save_section_workspace,
            "section-workspace-info": section_workspace_info,
            "load-section-workspace": load_section_workspace,
            "extract-section-workspace": extract_section_workspace,
            "clear-section-cache": clear_section_cache,
        }
        handlers[args.command](payload)
        return 0
    except PermissionError as exc:
        _emit("error", message=_permission_error_message(exc), details=traceback.format_exc())
        return 2
    except OSError as exc:
        if exc.errno == errno.EACCES:
            _emit("error", message=_permission_error_message(exc), details=traceback.format_exc())
            return 2
        _emit("error", message=str(exc), details=traceback.format_exc())
        return 1
    except Exception as exc:  # noqa: BLE001
        _emit("error", message=str(exc), details=traceback.format_exc())
        return 1


class _ProgressReporter:
    """Emit progress for completed work units, skipping redundant updates."""

    def __init__(self) -> None:
        self._last: tuple[int, str] | None = None

    def __call__(self, value: float, message: str) -> None:
        key = (int(max(0.0, min(100.0, value)) * 2), message)
        if key == self._last:
            return
        self._last = key
        _emit("progress", value=round(max(0.0, min(100.0, value)), 1), message=message)


# Share of one model's progress span taken by each loading stage.
_LOAD_OPEN_SPAN = (0.0, 0.6)
_LOAD_TRAJECTORY_SPAN = (0.65, 0.98)


def load_models(payload: JsonDict) -> None:
    results = []
    models = [
        (index, model)
        for index, model in enumerate(_models(payload), start=1)
        if str(model.get("path", "")).strip()
    ]
    report = _ProgressReporter()
    for model_number, (index, model) in enumerate(models):
        path = str(model.get("path", "")).strip()
        label = str(model.get("label") or f"M{index}")
        depth_offset = _to_float(model.get("depthOffset"), 0.0)
        span = 100.0 / len(models)
        base = model_number * span

        def at(fraction: float, message: str, label: str = label, base: float = base, span: float = span) -> None:
            report(base + span * fraction, f"{label} · {message}")

        def open_progress(step: str, done: int, total: int) -> None:
            start, end = _LOAD_OPEN_SPAN
            at(start + (end - start) * done / max(total, 1), f"{step} ({done}/{total})")

        def trajectory_progress(done: int, total: int) -> None:
            if done != total and done % max(1, total // 100):
                return
            start, end = _LOAD_TRAJECTORY_SPAN
            at(start + (end - start) * done / max(total, 1), f"Well trajectories {done}/{total}")

        _emit("log", message=f"Opening model {label}: {path}")
        at(0.0, "Opening model")
        reader = open_model_reader(path, progress=open_progress)
        grids = reader.list_grids()
        selected_grid_uuid = ""
        if grids:
            selected_grid_uuid = str(model.get("gridUuid") or "").strip()
            grid = _select_grid(grids, selected_grid_uuid, label, getattr(reader, "backend", ""))
            reader.select_grid(grid.uuid)
            selected_grid_uuid = grid.uuid
            grids = reader.list_grids()
        at(_LOAD_OPEN_SPAN[1], "Selected model")
        properties = reader.list_properties()
        list_horizons = getattr(reader, "list_named_horizons", None)
        try:
            named_horizons = list_horizons() if callable(list_horizons) else []
        except Exception as exc:  # noqa: BLE001
            named_horizons = []
            _emit("log", message=f"Warning: cannot read named surfaces from {label}: {exc}")
        list_trajectories = getattr(reader, "list_well_trajectories", None)
        at(_LOAD_TRAJECTORY_SPAN[0], "Well trajectories")
        try:
            if isinstance(reader, PetrelProjectReader):
                trajectories = reader.list_well_trajectories(progress=trajectory_progress)
            else:
                trajectories = list_trajectories() if callable(list_trajectories) else []
        except Exception as exc:  # noqa: BLE001
            trajectories = []
            _emit("log", message=f"Warning: cannot read well trajectories from {label}: {exc}")
        at(_LOAD_TRAJECTORY_SPAN[1], "Summary")
        summary = _model_summary(label, reader, grids, properties, trajectories, named_horizons)
        _emit("log", message=summary)
        grid_to_dict = getattr(reader, "grid_to_dict", None)
        grid_payloads = [
            grid_to_dict(grid) if callable(grid_to_dict) else _dataclass_dict(grid)
            for grid in grids
        ]
        results.append(
            {
                "path": str(reader.epc_path),
                "h5Path": str(reader.h5_path) if reader.h5_path else None,
                "backend": getattr(reader, "backend", ""),
                "label": label,
                "depthOffset": depth_offset,
                "gridUuid": selected_grid_uuid,
                "summary": summary,
                "grids": grid_payloads,
                "propertyCount": len(getattr(reader, "_properties", properties)),
                "properties": [_dataclass_dict(prop) for prop in properties],
                "trajectories": [_dataclass_dict(trajectory) for trajectory in trajectories],
                "namedHorizons": [_dataclass_dict(horizon) for horizon in named_horizons],
            }
        )
        at(1.0, "Loaded")
    if not results:
        raise ValueError("Select at least one model path.")
    _emit("result", models=results)


def model_source_info(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise ValueError("Model path is empty.")
    model_path = resolve_model_path(path)
    if is_petrel_project_path(model_path):
        _emit("result", **describe_petrel_project(model_path))
        return
    reader = open_model_reader(model_path)
    _emit(
        "result",
        kind=getattr(reader, "backend", "model"),
        path=str(reader.epc_path),
        h5Path=str(reader.h5_path) if reader.h5_path else None,
        grids=[_dataclass_dict(grid) for grid in reader.list_grids()],
        propertyCount=len(reader.list_properties()),
    )


def preview_sleeves(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise ValueError("Sleeves path is empty.")
    if bool(payload.get("headersOnly", False)):
        columns = read_sleeves_table_headers(path)
        guessed_mapping = guess_sleeves_column_mapping(columns)
        _emit(
            "result",
            columns=columns,
            guessedMapping=guessed_mapping,
            columnMapping=payload.get("columnMapping") or guessed_mapping,
            warnings=[],
            rows=0,
            wells=[],
            preview=[],
            coordinateStats=None,
            headersOnly=True,
        )
        return
    raw = read_sleeves_table_raw(path)
    guessed_mapping = guess_sleeves_column_mapping(list(raw.columns))
    requested_mapping = payload.get("columnMapping") or guessed_mapping
    normalized = apply_sleeves_column_mapping(raw, requested_mapping)
    warnings = validate_sleeves_table(normalized)
    wells = unique_well_values(normalized)
    counts = well_value_counts(normalized)
    x_values = pd.to_numeric(normalized["X"], errors="coerce") if "X" in normalized.columns else pd.Series(index=normalized.index, dtype=float)
    y_values = pd.to_numeric(normalized["Y"], errors="coerce") if "Y" in normalized.columns else pd.Series(index=normalized.index, dtype=float)
    md_values = pd.to_numeric(normalized["MD"], errors="coerce") if "MD" in normalized.columns else pd.Series(index=normalized.index, dtype=float)
    valid_xy = x_values.notna() & y_values.notna()
    normalized_well_keys = normalized["Well"].map(_normalize_text) if "Well" in normalized.columns else pd.Series(index=normalized.index, dtype=str)
    well_summaries = []
    for well in wells:
        mask = normalized_well_keys == _normalize_text(well)
        well_summaries.append(
            {
                "name": well,
                "count": counts.get(well, 0),
                "validXY": int((valid_xy & mask).sum()),
                "missingXY": int((~valid_xy & mask).sum()),
                "validMD": int((md_values.notna() & mask).sum()),
            }
        )
    _emit(
        "result",
        columns=[str(column) for column in raw.columns],
        guessedMapping=guessed_mapping,
        columnMapping=requested_mapping,
        warnings=warnings,
        rows=len(normalized),
        wells=well_summaries,
        preview=_records(normalized.head(100)),
        coordinateStats={
            "validXY": int(valid_xy.sum()),
            "missingXY": int(len(normalized) - valid_xy.sum()),
            "validMD": int(md_values.notna().sum()),
        },
    )


def suggest_output(payload: JsonDict) -> None:
    sleeves_path = str(payload.get("sleevesPath", "")).strip()
    if not sleeves_path:
        _emit("result", outputPath="")
        return
    _emit("result", outputPath=str(default_extraction_output_path(sleeves_path)))


def _extraction_sleeves(payload: JsonDict) -> pd.DataFrame:
    sleeves_path = str(payload.get("sleevesPath", "")).strip()
    if not sleeves_path:
        raise ValueError("Sleeves path is empty.")
    sleeves = load_sleeves_table(sleeves_path, payload.get("columnMapping") or None)
    original_count = len(sleeves)
    selected_wells = payload.get("selectedWells")
    if selected_wells is not None:
        sleeves = filter_sleeves_by_wells(sleeves, [str(value) for value in selected_wells])
        _emit("log", message=f"Well filter: sleeves {len(sleeves)} of {original_count}.")
        if sleeves.empty:
            raise ValueError("Well filter removed all sleeves.")
    sleeve_warnings = validate_sleeves_table(sleeves)
    for warning in sleeve_warnings:
        _emit("log", message=f"Warning: {warning}")
    missing_xy = [warning for warning in sleeve_warnings if warning in {"Missing required column: X", "Missing required column: Y"}]
    if missing_xy:
        raise ValueError(
            "Sleeves table has no X/Y coordinates. Generate them on the Sections page and use the saved *_boundaries.xlsx file."
        )
    return sleeves


def _extraction_specs(payload: JsonDict) -> list[ExtractionModelSpec]:
    specs = []
    for index, model in enumerate(_models(payload), start=1):
        path = str(model.get("path", "")).strip()
        if not path:
            continue
        selected = [str(value) for value in model.get("selectedPropertyUuids") or []]
        specs.append(
            ExtractionModelSpec(
                path=path,
                selected_property_uuids=selected,
                depth_offset=_to_float(model.get("depthOffset"), 0.0),
                label=str(model.get("label") or f"M{index}"),
                grid_uuid=str(model.get("gridUuid") or "").strip() or None,
            )
        )
    if not specs:
        raise ValueError("Select at least one model.")
    return specs


def _coverage_warnings(coverage: list[JsonDict]) -> list[str]:
    warnings = []
    for item in coverage:
        if item["inside"] < item["total"]:
            properties = ", ".join(item["properties"]) or "no properties"
            warnings.append(
                f"{item['label']} ({item['gridTitle']}): {item['total'] - item['inside']} of {item['total']} "
                f"sleeves are outside the model; {properties} will be empty for them."
            )
    return warnings


def _log_coverage(coverage: list[JsonDict]) -> None:
    for item in coverage:
        _emit(
            "log",
            message=f"Coverage {item['label']} ({item['gridTitle']}): {item['inside']} of {item['total']} sleeves inside.",
        )
    for warning in _coverage_warnings(coverage):
        _emit("log", message=f"Warning: {warning}")


def model_coverage(payload: JsonDict) -> None:
    sleeves = _extraction_sleeves(payload)
    extractor = MultiModelPropertyExtractor(_extraction_specs(payload))
    extractor.open(log_callback=lambda message: _emit("log", message=message))
    coverage = extractor.model_coverage(sleeves)
    _log_coverage(coverage)
    _emit("result", coverage=coverage)


def extract(payload: JsonDict) -> None:
    sleeves_path = str(payload.get("sleevesPath", "")).strip()
    output_path = str(payload.get("outputPath", "")).strip()
    if not sleeves_path:
        raise ValueError("Sleeves path is empty.")
    if not output_path:
        raise ValueError("Output path is empty.")

    sleeves = _extraction_sleeves(payload)
    specs = _extraction_specs(payload)

    extractor = MultiModelPropertyExtractor(
        specs,
        skip_inactive=bool(payload.get("skipInactive", True)),
        write_diagnostics=bool(payload.get("writeDiagnostics", True)),
        parallel_workers=max(1, int(payload.get("parallelWorkers") or 1)),
    )
    extractor.open(log_callback=lambda message: _emit("log", message=message))
    metadata = extractor.metadata
    if metadata is None:
        raise ValueError("Model metadata was not initialized.")
    coverage = extractor.model_coverage(sleeves)
    _log_coverage(coverage)

    output_plan = choose_output_plan(
        output_path,
        sleeve_count=len(sleeves),
        nk=metadata.primary_grid_shape[2],
    )
    if output_plan.warning:
        _emit("log", message=f"Warning: {output_plan.warning}")

    def progress(current: int, total: int) -> None:
        value = int((current / total) * 100) if total else 0
        _emit("progress", value=value, current=current, total=total)

    writer = extractor.extract_to_csv if output_plan.format == "CSV" else extractor.extract_to_xlsx
    stats = writer(
        sleeves,
        output_path=output_plan.path,
        progress_callback=progress,
        log_callback=lambda message: _emit("log", message=message),
    )
    if output_plan.warning:
        stats.warnings.append(output_plan.warning)
    stats.warnings[:0] = _coverage_warnings(coverage)

    settings = ExtractionSettings(
        sampling_mode="fast",
        skip_inactive=bool(payload.get("skipInactive", True)),
        selected_property_uuids=[uuid for spec in specs for uuid in spec.selected_property_uuids],
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
        sleeves_path=sleeves_path,
        output_path=output_plan.path,
        settings=settings,
        stats=stats,
    )
    _emit(
        "result",
        outputPath=str(output_plan.path),
        logPath=str(log_path),
        stats=_dataclass_dict(stats),
        coverage=coverage,
    )


def table_info(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise ValueError("Table path is empty.")
    if bool(payload.get("headersOnly", False)):
        cached = _valid_curve_table_cache(path)
        columns = cached[1]["columns"] if cached else read_table_headers(path)
        _emit("result", columns=columns, rows=cached[1]["rows"] if cached else None, headersOnly=True)
        return
    if bool(payload.get("prepareCurveCache", False)):
        _cache_path, metadata = _ensure_curve_table_cache(path)
    else:
        df = _deduplicate_columns(read_table(path))
        metadata = {
            "columns": [str(column) for column in df.columns],
            "rows": int(len(df)),
            "wells": _unique_strings(df.get("Well")) if "Well" in df else [],
            "ports": _unique_strings(df.get("Port")) if "Port" in df else [],
            "portsByWell": _ports_by_well(df),
            "preview": _records(df.head(100)),
        }
    _emit(
        "result",
        columns=metadata["columns"],
        rows=metadata["rows"],
        wells=metadata["wells"],
        ports=metadata["ports"],
        portsByWell=metadata["portsByWell"],
        preview=metadata["preview"],
        curveCacheReady=bool(payload.get("prepareCurveCache", False)),
    )


def metrics(payload: JsonDict) -> None:
    extracted_path = str(payload.get("extractedPath", "")).strip()
    intervals_path = str(payload.get("intervalsPath", "")).strip()
    output_path = str(payload.get("outputPath", "")).strip()
    if not extracted_path or not intervals_path or not output_path:
        raise ValueError("Metrics paths are incomplete.")
    _emit("progress", value=5)
    _emit("log", message="Loading extracted cell table...")
    extracted = _read_table_via_cache(extracted_path)
    _emit("progress", value=35)
    _emit("log", message="Loading interval table...")
    intervals = read_table(intervals_path)
    _emit("progress", value=55)
    settings = IntervalMetricSettings(
        ntg_column=_empty_to_none(payload.get("ntgColumn")),
        poro_column=_empty_to_none(payload.get("poroColumn")),
        perm_column=_empty_to_none(payload.get("permColumn")),
        lithology_column=_empty_to_none(payload.get("lithologyColumn")),
        density_column=_empty_to_none(payload.get("densityColumn")),
        shmin_column=_empty_to_none(payload.get("shminColumn")),
        reservoir_values={_normalize_value(value) for value in payload.get("reservoirValues") or []},
        property_columns=[str(value) for value in payload.get("propertyColumns") or []],
        metric_keys=[str(value) for value in payload.get("metricKeys") or DEFAULT_METRIC_KEYS],
        clay_window_m=_window_meters(payload.get("clayWindow"), "Clay window"),
        barrier_window_m=_window_meters(payload.get("barrierWindow"), "Barrier window"),
    )

    def metrics_progress(current: int, total: int) -> None:
        value = 55 + int((current / total) * 25) if total else 80
        _emit("progress", value=min(80, max(55, value)), current=current, total=total)

    _emit("log", message="Calculating interval metrics...")
    result = calculate_interval_metrics(extracted, intervals, settings, progress_callback=metrics_progress)
    for warning in result.warnings:
        _emit("log", message=f"Warning: {warning}")
    if not result.rows:
        details = "; ".join(result.warnings) or "The interval table contains no rows."
        raise ValueError(f"Metrics were not calculated. {details}")
    _emit("progress", value=80)
    _emit("log", message=f"Writing metrics XLSX: {output_path}")
    write_interval_metrics_xlsx(result, output_path)
    description_path = write_interval_metrics_description(
        result,
        output_path,
        settings,
        extracted_path=extracted_path,
        intervals_path=intervals_path,
    )
    _emit("log", message=f"Writing metrics description: {description_path}")
    _emit("progress", value=100)
    _emit(
        "result",
        outputPath=output_path,
        descriptionPath=str(description_path),
        rowsWritten=len(result.rows),
        warnings=result.warnings,
        barrierNotices=result.barrier_notices,
        netWarnings=result.net_warnings,
    )


def _window_meters(value: object, label: str) -> float:
    """Metres from the Metrics page; empty means the default window."""
    if value is None or str(value).strip() == "":
        return INTERVAL_BUFFER_METERS
    try:
        number = float(str(value).replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{label} must be a positive number of metres.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a positive number of metres.")
    return number


def lithology_codes(payload: JsonDict) -> None:
    """Statistics of lithology codes against PORO and the recommended reservoir codes."""
    path = str(payload.get("path", "")).strip()
    lithology_column = str(payload.get("lithologyColumn") or "").strip()
    if not path or not lithology_column:
        raise ValueError("Select extracted table and lithology column.")
    poro_column = _empty_to_none(payload.get("poroColumn"))
    ntg_column = _empty_to_none(payload.get("ntgColumn"))
    wanted = [lithology_column, poro_column, ntg_column, "CellHeight", "TVD_top", "TVD_base", "TVDSS_TOP_TOTAL", "TVDSS_BOT_TOTAL"]
    cells = _read_table_columns_via_cache(path, [column for column in wanted if column])
    _emit("result", **analyze_lithology_codes(cells, lithology_column, poro_column, ntg_column))


def _read_table_columns_via_cache(path: str | Path, columns: list[str]) -> pd.DataFrame:
    """Read only the given columns (those that exist) through the parquet cache."""
    try:
        cache_path, metadata = _ensure_curve_table_cache(path)
        available = set(metadata.get("columns") or [])
        selected = [column for column in dict.fromkeys(columns) if column in available]
        return pd.read_parquet(cache_path, columns=selected)
    except Exception:  # noqa: BLE001
        df = read_table(path)
        return df[[column for column in dict.fromkeys(columns) if column in df.columns]]


def merge_tables_command(payload: JsonDict) -> None:
    paths = [str(value).strip() for value in payload.get("paths") or [] if str(value).strip()]
    key_columns = [str(value).strip() for value in payload.get("keyColumns") or [] if str(value).strip()]
    output_path = str(payload.get("outputPath", "")).strip()
    if len(paths) < 2:
        raise ValueError("Select at least two files to merge.")
    if not output_path:
        raise ValueError("Enter output file name.")
    resolved_output = Path(output_path).resolve()
    if any(Path(path).resolve() == resolved_output for path in paths):
        raise ValueError("Output file must differ from the input files.")
    labels = file_labels(paths)
    inputs: list[MergeInput] = []
    for index, (label, path) in enumerate(zip(labels, paths, strict=True), start=1):
        _emit("log", message=f"Reading {Path(path).name} ({label})...")
        inputs.append(MergeInput(label=label, frame=_deduplicate_columns(read_table(path))))
        _emit("progress", value=int(60 * index / len(paths)))
    _emit("log", message=f"Merging {len(paths)} files by {', '.join(key_columns)}...")
    result = merge_tables(inputs, key_columns, add_source_column=bool(payload.get("addSourceColumn", True)))
    _emit("progress", value=80)
    for warning in result.warnings:
        _emit("log", message=f"Warning: {warning}")
    _emit("log", message=f"Writing merged table: {output_path}")
    write_merged_table(result, output_path)
    _emit("progress", value=100)
    _emit(
        "result",
        outputPath=output_path,
        rowsWritten=int(len(result.frame)),
        columnsWritten=int(len(result.frame.columns)),
        conflicts=result.conflicts,
        files=[{**stats, "path": path} for stats, path in zip(result.file_stats, paths, strict=True)],
        warnings=result.warnings,
    )


def curve_data(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise ValueError("Curve table path is empty.")
    cache_path, metadata = _ensure_curve_table_cache(path)
    result = _curve_stage_rows(
        path,
        cache_path,
        metadata,
        well=_empty_to_none(payload.get("well")),
        port=_empty_to_none(payload.get("port")),
        depth_mode=str(payload.get("depthMode") or "individual"),
        requested_columns=payload.get("columns") or [],
        limit=int(payload.get("limit") or 20000),
    )
    _emit("result", **result)


def curve_data_batch(payload: JsonDict) -> None:
    """Return curve rows for several well/port stages in one backend call."""
    path = str(payload.get("path", "")).strip()
    if not path:
        raise ValueError("Curve table path is empty.")
    cache_path, metadata = _ensure_curve_table_cache(path)
    stages = []
    for stage in payload.get("stages") or []:
        well = _empty_to_none(stage.get("well"))
        port = _empty_to_none(stage.get("port"))
        result = _curve_stage_rows(
            path,
            cache_path,
            metadata,
            well=well,
            port=port,
            depth_mode=str(payload.get("depthMode") or "individual"),
            requested_columns=payload.get("columns") or [],
            limit=int(payload.get("limit") or 20000),
        )
        stages.append({"well": stage.get("well"), "port": stage.get("port"), **result})
    _emit("result", stages=stages)


def _curve_stage_rows(
    path: str,
    cache_path: Path,
    metadata: JsonDict,
    *,
    well: str | None,
    port: str | None,
    depth_mode: str,
    requested_columns: list,
    limit: int,
) -> JsonDict:
    available_columns = [str(value) for value in metadata["columns"]]
    columns = [str(value) for value in requested_columns if str(value) in available_columns]
    depth_col = next(
        (name for name in ("TVD_top", "TVD_center", "TVDSS_top", "TVDSS_center") if name in available_columns),
        None,
    )
    if depth_col is None:
        raise ValueError("Curve table has no supported depth column.")
    channel_depth_columns: dict[str, str] = {}
    for column in columns:
        diagnostic_depth = f"{column}_TVD_center"
        if depth_mode != "common" and diagnostic_depth in available_columns:
            channel_depth_columns[column] = diagnostic_depth
        else:
            channel_depth_columns[column] = depth_col
    keep = _unique_list(
        [
            column
            for column in [
                "Well",
                "Port",
                "TVDSS_PORT",
                "Depth_KB_PORT",
                *INTERVAL_BOUNDARY_COLUMNS,
                depth_col,
                *channel_depth_columns.values(),
                *columns,
            ]
            if column in available_columns
        ]
    )
    filters = []
    if well is not None and "Well" in available_columns:
        filters.append((CURVE_CACHE_WELL_KEY, "==", _normalize_value(well)))
    if port is not None and "Port" in available_columns:
        filters.append((CURVE_CACHE_PORT_KEY, "==", _normalize_value(port)))
    cache_columns = _unique_list(
        keep
        + ([CURVE_CACHE_WELL_KEY] if "Well" in available_columns else [])
        + ([CURVE_CACHE_PORT_KEY] if "Port" in available_columns else [])
    )
    try:
        df = pd.read_parquet(cache_path, columns=cache_columns, filters=filters or None)
    except Exception:  # noqa: BLE001
        cache_path, _metadata = _ensure_curve_table_cache(path, force=True)
        df = pd.read_parquet(cache_path, columns=cache_columns, filters=filters or None)
    df = df.drop(columns=[CURVE_CACHE_WELL_KEY, CURVE_CACHE_PORT_KEY], errors="ignore")
    boundaries = {}
    for column in INTERVAL_BOUNDARY_COLUMNS:
        if column not in df:
            continue
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if not values.empty:
            boundaries[column] = float(values.iloc[0])
    df = df.drop(columns=list(INTERVAL_BOUNDARY_COLUMNS), errors="ignore")
    if depth_col in df:
        df = df.sort_values(depth_col)
    return {
        "depthColumn": depth_col,
        "channelDepthColumns": channel_depth_columns,
        "columns": columns,
        "boundaries": boundaries,
        "rows": _records(df.head(limit)),
    }


def _ensure_curve_table_cache(
    path: str | Path,
    *,
    force: bool = False,
) -> tuple[Path, JsonDict]:
    source, cache_path, metadata_path, signature = _curve_table_cache_location(path)
    if not force:
        cached = _valid_curve_table_cache(path)
        if cached:
            return cached
    _curve_cache_directory().mkdir(parents=True, exist_ok=True)

    df = _deduplicate_columns(read_table(source))
    columns = [str(column) for column in df.columns]
    wells = _unique_strings(df.get("Well")) if "Well" in df else []
    ports = _unique_strings(df.get("Port")) if "Port" in df else []
    ports_by_well = _ports_by_well(df)
    if "Well" in df:
        df[CURVE_CACHE_WELL_KEY] = df["Well"].map(_normalize_value)
    if "Port" in df:
        df[CURVE_CACHE_PORT_KEY] = df["Port"].map(_normalize_value)

    metadata: JsonDict = {
        **signature,
        "columns": columns,
        "rows": int(len(df)),
        "wells": wells,
        "ports": ports,
        "portsByWell": ports_by_well,
        "preview": _records(df[columns].head(100)),
    }
    temporary_cache = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    temporary_metadata = metadata_path.with_name(f"{metadata_path.name}.{os.getpid()}.tmp")
    try:
        df.to_parquet(temporary_cache, index=False, compression="snappy")
        temporary_metadata.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary_cache, cache_path)
        os.replace(temporary_metadata, metadata_path)
    finally:
        temporary_cache.unlink(missing_ok=True)
        temporary_metadata.unlink(missing_ok=True)
    return cache_path, metadata


def _curve_table_cache_location(path: str | Path) -> tuple[Path, Path, Path, JsonDict]:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    cache_dir = _curve_cache_directory()
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:24]
    source_stat = source.stat()
    signature = {
        "sourcePath": str(source),
        "sourceSize": int(source_stat.st_size),
        "sourceMtimeNs": int(source_stat.st_mtime_ns),
    }
    return source, cache_dir / f"{digest}.parquet", cache_dir / f"{digest}.json", signature


def _valid_curve_table_cache(path: str | Path) -> tuple[Path, JsonDict] | None:
    """Return the parquet cache of a table if it matches the current file."""
    _source, cache_path, metadata_path, signature = _curve_table_cache_location(path)
    if not cache_path.exists() or not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if all(metadata.get(key) == value for key, value in signature.items()):
        return cache_path, metadata
    return None


def _read_table_via_cache(path: str | Path) -> pd.DataFrame:
    """Read a large table through its parquet cache (built on first use)."""
    try:
        cache_path, _metadata = _ensure_curve_table_cache(path)
        df = pd.read_parquet(cache_path)
    except Exception:  # noqa: BLE001
        return read_table(path)
    return df.drop(columns=[CURVE_CACHE_WELL_KEY, CURVE_CACHE_PORT_KEY], errors="ignore")


def _curve_cache_directory() -> Path:
    override = os.environ.get("PETRELHACKER_CURVE_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "PetrelHacker" / "curve-cache"
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "PetrelHacker" / "curve-cache"
    return Path.home() / ".cache" / "PetrelHacker" / "curve-cache"


def _ports_by_well(df: pd.DataFrame) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if "Well" not in df or "Port" not in df:
        return result
    for raw_well, raw_port in zip(df["Well"], df["Port"], strict=False):
        well_key = _normalize_value(raw_well)
        port_key = _normalize_value(raw_port)
        if not well_key or not port_key:
            continue
        ports = result.setdefault(well_key, [])
        if port_key not in ports:
            ports.append(port_key)
    return result


def well_trajectories(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    include_points = bool(payload.get("includePoints", False))
    point_limit = int(payload.get("pointLimit") or 100_000)
    if not path:
        raise ValueError("Model path is empty.")

    model_path = resolve_model_path(path)
    if Path(model_path).suffix.lower() == ".epc":
        reader = ResqmlReader(model_path)
        reader.open(include_properties=False, validate_with_resqpy=False)
    else:
        reader = open_model_reader(model_path)
    if not hasattr(reader, "list_well_trajectories"):
        _emit("result", trajectories=[], points=[])
        return

    trajectories = reader.list_well_trajectories()
    points = []
    if include_points:
        for trajectory in trajectories:
            if len(points) >= point_limit:
                break
            try:
                trajectory_points = reader.get_well_trajectory_points(trajectory.uuid)
            except Exception as exc:  # noqa: BLE001
                _emit("log", message=f"Warning: cannot read trajectory points for {trajectory.title}: {exc}")
                continue
            remaining = point_limit - len(points)
            points.extend(_dataclass_dict(point) for point in trajectory_points[:remaining])

    _emit(
        "result",
        backend=getattr(reader, "backend", ""),
        trajectories=[_dataclass_dict(trajectory) for trajectory in trajectories],
        points=points,
    )


def trajectory_analysis(payload: JsonDict) -> None:
    assignments = payload.get("assignments") or []
    if not isinstance(assignments, list):
        raise ValueError("Trajectory assignments must be a list.")
    readers: dict[str, object] = {}
    trajectories_by_path: dict[str, dict[str, object]] = {}
    results: list[JsonDict] = []
    report = _ProgressReporter()
    total = len(assignments)
    for assignment_number, assignment in enumerate(assignments):
        report(100.0 * assignment_number / max(total, 1), f"Well {assignment_number + 1}/{total}")
        if not isinstance(assignment, dict):
            continue
        path = str(assignment.get("path", "")).strip()
        trajectory_uuid = str(assignment.get("trajectoryUuid", "")).strip()
        if not path or not trajectory_uuid:
            continue
        try:
            reader = readers.get(path)
            if reader is None:
                report(100.0 * assignment_number / max(total, 1), f"Opening model {Path(path).name}")
                reader = _open_trajectory_reader(path)
                readers[path] = reader
                trajectories_by_path[path] = {
                    str(item.uuid).lower(): item for item in reader.list_well_trajectories()
                }
            trajectory = trajectories_by_path[path].get(trajectory_uuid.lower())
            if trajectory is None:
                raise ValueError("Trajectory was not found in the selected model.")
            points = reader.get_well_trajectory_points(trajectory_uuid)
            altitude = _trajectory_altitude(reader, trajectory, points)
            results.append(
                {
                    "key": assignment.get("key"),
                    "trajectoryUuid": trajectory_uuid,
                    **analyze_trajectory(points, altitude=altitude),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append({"key": assignment.get("key"), "trajectoryUuid": trajectory_uuid, "error": str(exc)})
    report(100.0, f"Well {total}/{total}")
    _emit("result", analyses=results)


def calculate_sleeve_coordinates(payload: JsonDict) -> None:
    source_path = str(payload.get("path", "")).strip()
    output_path = str(payload.get("outputPath") or source_path).strip()
    frac_well = str(payload.get("wellName", "")).strip()
    model_path = str(payload.get("modelPath", "")).strip()
    trajectory_uuid = str(payload.get("trajectoryUuid", "")).strip()
    overwrite_existing = bool(payload.get("overwriteExisting", False))
    if not source_path:
        raise ValueError("Frac-list path is required.")
    if not frac_well or not model_path or not trajectory_uuid:
        raise ValueError("Select a model and trajectory for the well first.")

    raw = read_sleeves_table_raw(source_path)
    mapping = payload.get("columnMapping") or guess_sleeves_column_mapping(list(raw.columns))
    normalized = apply_sleeves_column_mapping(raw, mapping)
    if "Well" not in normalized.columns or "MD" not in normalized.columns:
        raise ValueError("Frac-list must contain mapped Well and MD columns to calculate X/Y.")

    reader = _open_trajectory_reader(model_path)
    points = reader.get_well_trajectory_points(trajectory_uuid)
    well_rows = normalized[normalized["Well"].map(_normalize_text) == _normalize_text(frac_well)]
    if well_rows.empty:
        raise ValueError(f"Well was not found in frac-list: {frac_well}")

    coordinates: dict[int, tuple[float | None, float | None]] = {}
    outside: list[JsonDict] = []
    existing_skipped = 0
    for index in well_rows.index:
        current_x = _to_float(normalized.at[index, "X"], math.nan) if "X" in normalized.columns else math.nan
        current_y = _to_float(normalized.at[index, "Y"], math.nan) if "Y" in normalized.columns else math.nan
        write_x = overwrite_existing or not math.isfinite(current_x)
        write_y = overwrite_existing or not math.isfinite(current_y)
        if not write_x and not write_y:
            existing_skipped += 1
            continue
        md = _to_float(normalized.at[index, "MD"], math.nan)
        xy = interpolate_trajectory_xy(points, md)
        if xy is None:
            outside.append({"row": int(index) + 2, "md": _json_value(normalized.at[index, "MD"])})
            continue
        coordinates[int(index)] = (xy[0] if write_x else None, xy[1] if write_y else None)
    if not coordinates:
        if existing_skipped:
            _emit(
                "result",
                outputPath=output_path,
                wellName=frac_well,
                rowsUpdated=0,
                rowsExistingSkipped=existing_skipped,
                rowsOutsideTrajectory=len(outside),
                outside=outside[:20],
            )
            return
        raise ValueError("No sleeve coordinates could be calculated. Check MD values and trajectory range.")

    _write_sleeve_coordinates(source_path, output_path, raw, mapping, coordinates)
    _emit(
        "result",
        outputPath=output_path,
        wellName=frac_well,
        rowsUpdated=len(coordinates),
        rowsExistingSkipped=existing_skipped,
        rowsOutsideTrajectory=len(outside),
        outside=outside[:20],
    )


def _trajectory_altitude(reader: object, trajectory: object, points: list[object]) -> float | None:
    well_key = _normalize_text(getattr(trajectory, "well_name", ""))
    try:
        datums = reader.list_md_datums()
    except Exception:  # noqa: BLE001
        datums = []
    for datum in datums or []:
        if _normalize_text(getattr(datum, "well_name", "")) != well_key:
            continue
        value = _to_float(getattr(datum, "z", None), math.nan)
        if math.isfinite(value):
            return value
    if points:
        value = _to_float(getattr(points[0], "z", None), math.nan)
        return value if math.isfinite(value) else None
    return None


def _open_trajectory_reader(path: str) -> object:
    model_path = resolve_model_path(path)
    if Path(model_path).suffix.lower() == ".epc":
        reader = ResqmlReader(model_path)
        reader.open(include_properties=False, validate_with_resqpy=False)
        return reader
    return open_model_reader(model_path)


def _write_sleeve_coordinates(
    source_path: str,
    output_path: str,
    raw: pd.DataFrame,
    mapping: dict[str, str],
    coordinates: dict[int, tuple[float | None, float | None]],
) -> None:
    x_column = str(mapping.get("X") or "X")
    y_column = str(mapping.get("Y") or "Y")
    source_suffix = Path(source_path).suffix.lower()
    output_suffix = Path(output_path).suffix.lower()
    if source_suffix in {".xlsx", ".xlsm"} and output_suffix in {".xlsx", ".xlsm"}:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("openpyxl is required to save calculated coordinates.") from exc
        workbook = load_workbook(source_path)
        sheet = workbook.worksheets[0]
        headers = [str(cell.value) if cell.value is not None else "" for cell in sheet[1]]
        column_indices = {header: index + 1 for index, header in enumerate(headers) if header}
        for column in (x_column, y_column):
            if column not in column_indices:
                column_indices[column] = sheet.max_column + 1
                sheet.cell(row=1, column=column_indices[column], value=column)
        for index, (x, y) in coordinates.items():
            if x is not None:
                sheet.cell(row=index + 2, column=column_indices[x_column], value=x)
            if y is not None:
                sheet.cell(row=index + 2, column=column_indices[y_column], value=y)
        workbook.save(output_path)
        return

    out = raw.copy()
    if x_column not in out.columns:
        out[x_column] = None
    if y_column not in out.columns:
        out[y_column] = None
    for index, (x, y) in coordinates.items():
        if x is not None:
            out.at[index, x_column] = x
        if y is not None:
            out.at[index, y_column] = y
    if output_suffix == ".csv":
        out.to_csv(output_path, index=False)
    else:
        out.to_excel(output_path, index=False)


def model_section(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    property_uuid = str(payload.get("propertyUuid", "")).strip()
    if not path:
        raise ValueError("Model path is empty.")
    if not property_uuid:
        raise ValueError("Property is not selected.")

    def progress(current: int, total: int) -> None:
        value = int((current / total) * 100) if total else 0
        _emit("progress", value=value, current=current, total=total)

    cache_key = _section_cache_key(payload)
    cached = _load_section_cache(cache_key)
    if cached is not None:
        _emit("log", message="Loaded section from cache.")
        _emit("progress", value=100)
        _emit("result", cacheKey=cache_key, **_clean_section_cache_result(cached))
        return
    if bool(payload.get("cacheOnly", False)):
        raise ValueError("Cached section was not found. Use Draw section to build it.")

    _emit("log", message="Building section along well trajectory...")
    result = extract_well_section(
        path,
        property_uuid,
        grid_uuid=_empty_to_none(payload.get("gridUuid")),
        trajectory_model_path=_empty_to_none(payload.get("trajectoryPath")),
        well_name=_empty_to_none(payload.get("wellName")),
        trajectory_uuid=_empty_to_none(payload.get("trajectoryUuid")),
        sample_step=_to_float(payload.get("sampleStep"), 25.0),
        depth_offset=_to_float(payload.get("depthOffset"), 0.0),
        skip_inactive=bool(payload.get("skipInactive", True)),
        extra_md_values=_float_list(payload.get("extraMds")),
        horizon_sources=[item for item in payload.get("horizonSources") or [] if isinstance(item, dict)],
        progress_callback=progress,
    )
    result_payload = _section_result_payload(result)
    if bool(payload.get("saveCache", False)):
        _save_section_cache(cache_key, result_payload)
    _emit("progress", value=100)
    _emit("result", **result_payload)


def sleeve_markers(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    well_name = str(payload.get("wellName", "")).strip()
    if not path:
        _emit("result", markers=[])
        return
    if not well_name:
        _emit("result", markers=[])
        return
    sleeves = load_sleeves_table(path, payload.get("columnMapping") or None)
    if "MD" not in sleeves.columns:
        md_column = _find_md_column(sleeves.columns)
        if md_column:
            sleeves["MD"] = sleeves[md_column]
        else:
            _emit(
                "result",
                markers=[],
                warning=f"MD column is not mapped in the Extraction sleeves table. Columns: {', '.join(map(str, sleeves.columns[:12]))}",
            )
            return
    if "Well" not in sleeves.columns or "Port" not in sleeves.columns:
        _emit("result", markers=[], warning="Well or Port column is not mapped in the Extraction sleeves table.")
        return
    well_key = _normalize_text(well_name)
    well_keys = sleeves["Well"].map(_normalize_text)
    filtered = sleeves[well_keys == well_key].copy()
    if filtered.empty:
        loose_mask = well_keys.map(lambda value: bool(value) and (value in well_key or well_key in value))
        filtered = sleeves[loose_mask].copy()
    if filtered.empty:
        available_all = sorted({str(value) for value in sleeves["Well"] if not pd.isna(value)})
        available = sorted({value for value in well_keys if value})[:10]
        _emit(
            "result",
            markers=[],
            availableWells=available_all,
            warning=f"No sleeves found for well '{well_name}' in Extraction table. Available examples: {', '.join(available)}",
        )
        return
    filtered["MD"] = pd.to_numeric(filtered["MD"], errors="coerce")
    filtered = filtered[pd.notna(filtered["MD"])].copy()
    if filtered.empty:
        _emit("result", markers=[], warning=f"Sleeves for well '{well_name}' have no numeric MD values.")
        return
    filtered = filtered.sort_values("MD")
    markers = [
        {
            "well": str(row["Well"]),
            "port": _json_value(row["Port"]),
            "md": float(row["MD"]),
        }
        for _, row in filtered.iterrows()
    ]
    _emit("result", markers=markers)


def save_section_boundaries(payload: JsonDict) -> None:
    input_path = str(payload.get("path", "")).strip()
    output_path = str(payload.get("outputPath", "")).strip()
    records = payload.get("records") or []
    if not input_path:
        raise ValueError("Frac-list path is empty.")
    if not output_path:
        raise ValueError("Output path is empty.")
    if not isinstance(records, list) or not records:
        raise ValueError("No boundary records to save.")

    source_path = output_path if Path(output_path).exists() else input_path
    raw = read_sleeves_table_raw(source_path)
    mapping = payload.get("columnMapping") or guess_sleeves_column_mapping(list(raw.columns))
    normalized = apply_sleeves_column_mapping(raw, mapping)
    column_targets = _boundary_output_columns(raw, mapping)
    updated = 0
    skipped: list[JsonDict] = []

    if Path(source_path).suffix.lower() in {".xlsx", ".xlsm"} and Path(output_path).suffix.lower() in {".xlsx", ".xlsm"}:
        updated, skipped = _save_boundaries_openpyxl(source_path, output_path, normalized, column_targets, records)
    else:
        out = raw.copy()
        for column in column_targets.values():
            if column not in out.columns:
                out[column] = None
        for record in records:
            if not isinstance(record, dict):
                continue
            index = _find_boundary_row(normalized, record)
            if index is None:
                skipped.append(_boundary_record_label(record))
                continue
            for key, column in column_targets.items():
                if key in record:
                    out.at[index, column] = _json_value(record.get(key))
            updated += 1
        if Path(output_path).suffix.lower() == ".csv":
            out.to_csv(output_path, index=False)
        else:
            out.to_excel(output_path, index=False)

    if skipped:
        _emit("log", message=f"Warning: boundary rows were not matched and were skipped: {len(skipped)}.")
    missing_global_bounds = _verify_saved_global_bounds(output_path, records, mapping)
    if missing_global_bounds:
        _emit(
            "log",
            message=(
                "Warning: TVDSS_TOP_TOTAL/TVDSS_BOT_TOTAL are missing after saving for "
                f"{len(missing_global_bounds)} sleeve row(s)."
            ),
        )
    _emit(
        "result",
        outputPath=output_path,
        rowsUpdated=updated,
        rowsRequested=len(records),
        rowsSkipped=len(skipped),
        skipped=skipped[:20],
        missingGlobalBoundsCount=len(missing_global_bounds),
        missingGlobalBounds=missing_global_bounds[:100],
    )


def load_section_boundaries(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    well_name = str(payload.get("wellName", "")).strip()
    if not path or not Path(path).exists():
        _emit("result", records=[])
        return
    raw = read_sleeves_table_raw(path)
    mapping = payload.get("columnMapping") or guess_sleeves_column_mapping(list(raw.columns))
    normalized = apply_sleeves_column_mapping(raw, mapping)
    if "Well" not in normalized.columns:
        _emit("result", records=[])
        return
    well_key = _normalize_text(well_name)
    rows = normalized[normalized["Well"].map(_normalize_text) == well_key] if well_key else normalized
    column_targets = _boundary_output_columns(raw, mapping)
    records: list[JsonDict] = []
    for index in rows.index:
        record: JsonDict = {
            "well": _json_value(normalized.at[index, "Well"]) if "Well" in normalized.columns else None,
            "port": _json_value(normalized.at[index, "Port"]) if "Port" in normalized.columns else None,
            "md": _json_value(normalized.at[index, "MD"]) if "MD" in normalized.columns else None,
            "X": _json_value(normalized.at[index, "X"]) if "X" in normalized.columns else None,
            "Y": _json_value(normalized.at[index, "Y"]) if "Y" in normalized.columns else None,
            "TVDSS_PORT": _json_value(normalized.at[index, "TVDSS_PORT"]) if "TVDSS_PORT" in normalized.columns else None,
        }
        has_boundary = False
        for key, column in column_targets.items():
            if column not in raw.columns:
                continue
            value = _json_value(raw.at[index, column])
            record[key] = value
            if key.startswith("TVDSS_") and key != "TVDSS_PORT" and math.isfinite(_to_float(value, math.nan)):
                has_boundary = True
        if has_boundary:
            records.append(record)
    _emit("result", records=records)


def save_section_workspace(payload: JsonDict) -> None:
    boundary_path = str(payload.get("boundaryPath", "")).strip()
    section_payload = payload.get("sectionPayload")
    result = payload.get("result")
    if not boundary_path:
        raise ValueError("Boundary file path is required for the section workspace.")
    if not isinstance(section_payload, dict) or not isinstance(result, dict):
        raise ValueError("Current section data is missing.")
    scene_settings = payload.get("sceneSettings")
    boundary_records = payload.get("boundaryRecords")
    column_mapping = payload.get("columnMapping")
    saved = save_section(
        boundary_path,
        section_payload,
        _clean_section_cache_result(result),
        scene_settings=scene_settings if isinstance(scene_settings, dict) else None,
        boundary_records=boundary_records if isinstance(boundary_records, list) else None,
        column_mapping=column_mapping if isinstance(column_mapping, dict) else None,
    )
    _emit("result", **saved)


def section_workspace_info(payload: JsonDict) -> None:
    path = str(payload.get("workspacePath") or payload.get("boundaryPath") or payload.get("sleevesPath") or "").strip()
    if not path:
        _emit("result", exists=False, sectionCount=0, wellCount=0, propertyCount=0, sizeBytes=0)
        return
    _emit("result", **workspace_info(path))


def load_section_workspace(payload: JsonDict) -> None:
    path = str(payload.get("workspacePath") or "").strip()
    section_id = str(payload.get("sectionId") or "").strip()
    if not path or not section_id:
        raise ValueError("Select a section workspace and saved section.")
    _emit("result", **load_workspace_section(path, section_id))


def extract_section_workspace(payload: JsonDict) -> None:
    sleeves_path = str(payload.get("sleevesPath", "")).strip()
    output_path = str(payload.get("outputPath", "")).strip()
    workspace_path = str(payload.get("workspacePath", "")).strip()
    if not sleeves_path:
        raise ValueError("Sleeves path is empty.")
    if not output_path:
        raise ValueError("Output path is empty.")
    if not workspace_path:
        workspace_path = str(workspace_path_for(sleeves_path))

    sleeves = load_sleeves_table(sleeves_path, payload.get("columnMapping") or None)
    original_count = len(sleeves)
    selected_wells = payload.get("selectedWells")
    if selected_wells is not None:
        sleeves = filter_sleeves_by_wells(sleeves, [str(value) for value in selected_wells])
        _emit("log", message=f"Well filter: sleeves {len(sleeves)} of {original_count}.")
    if sleeves.empty:
        raise ValueError("Well filter removed all sleeves.")
    if "MD" not in sleeves.columns or pd.to_numeric(sleeves["MD"], errors="coerce").isna().all():
        raise ValueError("Section workspace extraction requires sleeve MD values.")

    selected_properties = {
        str(model.get("label") or f"M{index}"): [str(value) for value in model.get("selectedPropertyUuids") or []]
        for index, model in enumerate(_models(payload), start=1)
        if model.get("selectedPropertyUuids")
    }
    info = workspace_info(workspace_path)
    output_plan = choose_output_plan(
        output_path,
        sleeve_count=len(sleeves),
        nk=max(1, int(info.get("maxCellsPerStation") or 1)),
    )
    if output_plan.warning:
        _emit("log", message=f"Warning: {output_plan.warning}")

    def progress(current: int, total: int) -> None:
        value = int((current / total) * 100) if total else 0
        _emit("progress", value=value, current=current, total=total)

    stats = extract_workspace(
        workspace_path,
        sleeves,
        output_plan.path,
        selected_properties=selected_properties,
        skip_inactive=bool(payload.get("skipInactive", True)),
        write_diagnostics=bool(payload.get("writeDiagnostics", True)),
        progress_callback=progress,
        log_callback=lambda message: _emit("log", message=message),
    )
    if output_plan.warning:
        stats.warnings.append(output_plan.warning)
    _emit("result", outputPath=str(output_plan.path), workspacePath=workspace_path, stats=_dataclass_dict(stats))


def clear_section_cache(_payload: JsonDict) -> None:
    cache_dir = _section_cache_dir()
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    _emit("result", cachePath=str(cache_dir), cleared=True)


def save_section_cache(payload: JsonDict) -> None:
    section_payload = payload.get("sectionPayload")
    result = payload.get("result")
    if not isinstance(section_payload, dict):
        raise ValueError("Section cache payload is missing.")
    if not isinstance(result, dict):
        raise ValueError("Section result is missing.")
    cache_key = _section_cache_key(section_payload)
    _save_section_cache(cache_key, _clean_section_cache_result(result))
    _emit("result", cached=True, cacheKey=cache_key)


def _section_cache_key(payload: JsonDict) -> str:
    model_path = resolve_model_path(str(payload.get("path", "")).strip())
    trajectory_path = resolve_model_path(str(payload.get("trajectoryPath", "")).strip()) if payload.get("trajectoryPath") else model_path
    data = {
        "version": 6,
        "model": _file_cache_identity(model_path),
        "trajectory": _file_cache_identity(trajectory_path),
        "gridUuid": str(payload.get("gridUuid", "")).strip(),
        "propertyUuid": str(payload.get("propertyUuid", "")).strip(),
        "wellName": _empty_to_none(payload.get("wellName")),
        "trajectoryUuid": _empty_to_none(payload.get("trajectoryUuid")),
        "sampleStep": _to_float(payload.get("sampleStep"), 25.0),
        "depthOffset": _to_float(payload.get("depthOffset"), 0.0),
        "skipInactive": bool(payload.get("skipInactive", True)),
        "extraMds": [round(value, 4) for value in _float_list(payload.get("extraMds"))],
        "horizonSources": payload.get("horizonSources") or [],
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_cache_identity(path: Path) -> JsonDict:
    try:
        stat = path.stat()
        return {
            "path": str(path.resolve()),
            "mtimeNs": stat.st_mtime_ns,
            "size": stat.st_size,
        }
    except OSError:
        return {"path": str(path), "mtimeNs": None, "size": None}


def _section_cache_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "PetrelHacker" / "section-cache"
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "PetrelHacker" / "section-cache"
    root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "petrelhacker" / "section-cache"


def _section_cache_file(key: str) -> Path:
    return _section_cache_dir() / f"{key}.json.gz"


def _load_section_cache(key: str) -> JsonDict | None:
    path = _section_cache_file(key)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        os.utime(path, None)
        result = payload.get("result") if isinstance(payload, dict) else None
        return _clean_section_cache_result(result) if isinstance(result, dict) else None
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        return None


def _clean_section_cache_result(result: JsonDict) -> JsonDict:
    cleaned = dict(result)
    cleaned.pop("event", None)
    cleaned.pop("cacheKey", None)
    return cleaned


def _save_section_cache(key: str, result: JsonDict) -> None:
    cache_dir = _section_cache_dir()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _section_cache_file(key)
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump({"version": 1, "result": result}, stream, ensure_ascii=True)
        _prune_section_cache(cache_dir, max_bytes=500 * 1024 * 1024)
    except Exception as exc:  # noqa: BLE001
        _emit("log", message=f"Warning: section cache was not saved: {exc}")


def _prune_section_cache(cache_dir: Path, max_bytes: int) -> None:
    files = [path for path in cache_dir.glob("*.json.gz") if path.is_file()]
    total = sum(path.stat().st_size for path in files)
    if total <= max_bytes:
        return
    for path in sorted(files, key=lambda item: item.stat().st_mtime):
        try:
            total -= path.stat().st_size
            path.unlink()
            path.with_name(path.name.replace(".json.gz", ".meta.json")).unlink(missing_ok=True)
        except OSError:
            pass
        if total <= max_bytes:
            break


def _boundary_output_columns(raw: pd.DataFrame, mapping: dict[str, str]) -> dict[str, str]:
    defaults = {
        "X": "X",
        "Y": "Y",
        "TVDSS_PORT": "TVDSS_PORT",
        "TVDSS_TOP_TOTAL": "TVDSS_TOP_TOTAL",
        "TVDSS_BOT_TOTAL": "TVDSS_BOT_TOTAL",
        "TVDSS_TOP_LOCAL": "TVDSS_TOP_LOCAL",
        "TVDSS_BOT_LOCAL": "TVDSS_BOT_LOCAL",
        "TVDSS_TOP_BARRIER_LOCAL": "TVDSS_TOP_BARRIER_LOCAL",
        "TVDSS_BOT_BARRIER_LOCAL": "TVDSS_BOT_BARRIER_LOCAL",
        "BARRIER_TOP_LOCAL": "BARRIER_TOP_LOCAL",
        "BARRIER_BOT_LOCAL": "BARRIER_BOT_LOCAL",
    }
    result = {}
    for key, default in defaults.items():
        mapped = mapping.get(key) if isinstance(mapping, dict) else None
        result[key] = str(mapped) if mapped and mapped in raw.columns else default
    return result


def _save_boundaries_openpyxl(
    input_path: str,
    output_path: str,
    normalized: pd.DataFrame,
    column_targets: dict[str, str],
    records: list[object],
) -> tuple[int, list[JsonDict]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openpyxl is required to save augmented XLSX frac-list files.") from exc

    workbook = load_workbook(input_path)
    sheet = workbook.worksheets[0]
    headers = [str(cell.value) if cell.value is not None else "" for cell in sheet[1]]
    column_indices = {header: index + 1 for index, header in enumerate(headers) if header}
    for column in column_targets.values():
        if column in column_indices:
            continue
        headers.append(column)
        column_indices[column] = len(headers)
        sheet.cell(row=1, column=len(headers), value=column)

    updated = 0
    skipped: list[JsonDict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        index = _find_boundary_row(normalized, record)
        if index is None:
            skipped.append(_boundary_record_label(record))
            continue
        excel_row = int(index) + 2
        for key, column in column_targets.items():
            if key in record:
                sheet.cell(row=excel_row, column=column_indices[column], value=_json_value(record.get(key)))
        updated += 1
    workbook.save(output_path)
    return updated, skipped


def _find_boundary_row(df: pd.DataFrame, record: dict[str, Any]) -> int | None:
    if "Well" not in df.columns:
        return None
    well_key = _normalize_text(record.get("well"))
    candidates = df[df["Well"].map(_normalize_text) == well_key]
    if candidates.empty:
        return None

    port_value = record.get("port")
    port_matched = False
    if "Port" in candidates.columns and port_value is not None:
        port_key = _normalize_value(port_value)
        by_port = candidates[candidates["Port"].map(_normalize_value) == port_key]
        if by_port.empty:
            return None
        candidates = by_port
        port_matched = True

    md_value = _to_float(record.get("md"), math.nan)
    if math.isfinite(md_value) and "MD" in candidates.columns:
        md_values = pd.to_numeric(candidates["MD"], errors="coerce")
        if md_values.notna().any():
            distances = (md_values - md_value).abs()
            nearest_index = distances.idxmin()
            if math.isfinite(float(distances.loc[nearest_index])) and float(distances.loc[nearest_index]) <= 0.5:
                return int(nearest_index)
            if not port_matched or len(candidates) > 1:
                return None

    if len(candidates) == 1:
        return int(candidates.index[0])
    return None


def _boundary_record_label(record: dict[str, Any]) -> JsonDict:
    return {
        "well": _json_value(record.get("well")),
        "port": _json_value(record.get("port")),
        "md": _json_value(record.get("md")),
    }


def _verify_saved_global_bounds(
    output_path: str,
    records: list[object],
    mapping: dict[str, str],
) -> list[JsonDict]:
    raw = read_sleeves_table_raw(output_path)
    normalized = apply_sleeves_column_mapping(raw, mapping)
    column_targets = _boundary_output_columns(raw, mapping)
    missing: list[JsonDict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        index = _find_boundary_row(normalized, record)
        if index is None:
            continue
        missing_fields = [
            key
            for key in ("TVDSS_TOP_TOTAL", "TVDSS_BOT_TOTAL")
            if column_targets[key] not in raw.columns
            or not math.isfinite(_to_float(raw.at[index, column_targets[key]], math.nan))
        ]
        if not missing_fields:
            continue
        label = _boundary_record_label(record)
        label["missingFields"] = missing_fields
        missing.append(label)
    return missing


def _find_md_column(columns: object) -> str | None:
    for column in columns:
        text = _normalize_text(column)
        if text == "MD" or text.endswith("MD") or "MEASUREDDEPTH" in text:
            return str(column)
    return None


def _read_payload() -> JsonDict:
    data = sys.stdin.buffer.read()
    text = data.decode("utf-8-sig") if data else ""
    if not text.strip():
        return {}
    return json.loads(text)


def _normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        head = text[:-2]
        if head.isdigit():
            return head
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
            "х": "X",
        }
    )
    return "".join(ch for ch in text.translate(translation).upper() if ch.isalnum())


def _models(payload: JsonDict) -> list[JsonDict]:
    models = payload.get("models")
    if isinstance(models, list):
        return [model for model in models if isinstance(model, dict)]
    path = payload.get("path") or payload.get("epcPath")
    return [{"path": path}] if path else []


def _select_grid(grids: list[object], grid_uuid: str, label: str, backend: str) -> object:
    if grid_uuid:
        for grid in grids:
            if getattr(grid, "uuid", None) == grid_uuid:
                return grid
        raise ValueError(f"Selected grid was not found for {label}: {grid_uuid}")
    if backend == "petrel-project" and len(grids) > 1:
        titles = ", ".join(getattr(grid, "title", getattr(grid, "uuid", "?")) for grid in grids[:5])
        raise ValueError(f"{label}: select one internal Petrel model before loading. Available: {titles}")
    return grids[0]


def _model_summary(
    label: str,
    reader: object,
    grids: list[object],
    properties: list[object],
    trajectories: list[object],
    named_horizons: list[object],
) -> str:
    lines = [f"{label}: model summary", f"  Backend: {getattr(reader, 'backend', '-') or '-'}"]
    for grid in grids:
        ni = getattr(grid, "ni", None)
        nj = getattr(grid, "nj", None)
        nk = getattr(grid, "nk", None)
        cells = int(ni) * int(nj) * int(nk) if ni and nj and nk else None
        cell_text = f", cells={cells:,}" if cells else ""
        lines.append(
            f"  Grid: {getattr(grid, 'title', '-')}, shape={ni or '?'} x {nj or '?'} x {nk or '?'}{cell_text}"
        )
    lines.append(f"  Property cubes: {len(properties)}")
    lines.append(f"  Well trajectories: {len(trajectories)}")
    lines.append(f"  Named surfaces: {len(named_horizons)}")
    max_listed_properties = 30
    for prop in properties[:max_listed_properties]:
        title = getattr(prop, "title", "-")
        kind = getattr(prop, "property_kind", None)
        uom = getattr(prop, "uom", None)
        tail = ", ".join(value for value in [f"kind={kind}" if kind else "", f"uom={uom}" if uom else ""] if value)
        lines.append(f"    - {title}" + (f" ({tail})" if tail else ""))
    if len(properties) > max_listed_properties:
        lines.append(f"    ... {len(properties) - max_listed_properties} more")
    return "\n".join(lines)


def _records(df: pd.DataFrame) -> list[JsonDict]:
    cleaned = df.where(pd.notna(df), None)
    return [
        {str(key): _json_value(value) for key, value in record.items()}
        for record in cleaned.to_dict(orient="records")
    ]


def _deduplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    seen: dict[str, int] = {}
    columns: list[str] = []
    for column in df.columns:
        name = str(column)
        count = seen.get(name, 0)
        seen[name] = count + 1
        columns.append(name if count == 0 else f"{name}_{count + 1}")
    out = df.copy()
    out.columns = columns
    return out


def _unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _first_existing_column(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def _dataclass_dict(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _dataclass_dict(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _dataclass_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_dataclass_dict(item) for item in value]
    return _json_value(value)


def _section_result_payload(result: Any) -> JsonDict:
    payload: JsonDict = {}
    for field in fields(result):
        value = getattr(result, field.name)
        if field.name != "rows":
            payload[field.name] = _dataclass_dict(value)
    rows = result.rows
    row_fields = fields(rows[0]) if rows else ()
    payload["rowColumns"] = {
        field.name: [_json_value(getattr(row, field.name)) for row in rows]
        for field in row_fields
    }
    return payload


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _emit(event: str, **payload: Any) -> None:
    message = {"event": event, **_dataclass_dict(payload)}
    print(json.dumps(message, ensure_ascii=True, separators=(",", ":")), flush=True)


def _to_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _float_list(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    result: list[float] = []
    for value in values:
        number = _to_float(value, math.nan)
        if math.isfinite(number):
            result.append(number)
    return result


def _empty_to_none(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _normalize_value(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if text.endswith(".0"):
        return text[:-2]
    return text


def _unique_strings(series: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    if series is None:
        return values
    for value in series:
        text = _normalize_value(value)
        if text and text not in seen:
            values.append(text)
            seen.add(text)
    return values


def _permission_error_message(exc: OSError) -> str:
    path = getattr(exc, "filename", None)
    if path:
        return f"Cannot write file. Close it in Excel or choose another path: {path}"
    return "Cannot write file. Close it in Excel or choose another output path."


if __name__ == "__main__":
    raise SystemExit(main())

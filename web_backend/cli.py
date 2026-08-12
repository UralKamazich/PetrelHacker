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
    IntervalMetricSettings,
    calculate_interval_metrics,
    write_interval_metrics_xlsx,
)
from core.model_section import extract_well_section
from core.model_reader import open_model_reader, resolve_model_path
from core.multi_model_extractor import ExtractionModelSpec, MultiModelPropertyExtractor
from core.output_planner import choose_output_plan
from core.petrel_project_reader import describe_petrel_project, is_petrel_project_path
from core.property_extractor import ExtractionSettings, write_extraction_log
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
from core.table_io import read_table


JsonDict = dict[str, Any]


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
            "table-info",
            "metrics",
            "curve-data",
            "well-trajectories",
            "model-section",
            "sleeve-markers",
            "load-section-boundaries",
            "save-section-boundaries",
            "save-section-cache",
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
            "table-info": table_info,
            "metrics": metrics,
            "curve-data": curve_data,
            "well-trajectories": well_trajectories,
            "model-section": model_section,
            "sleeve-markers": sleeve_markers,
            "load-section-boundaries": load_section_boundaries,
            "save-section-boundaries": save_section_boundaries,
            "save-section-cache": save_section_cache,
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


def load_models(payload: JsonDict) -> None:
    results = []
    for index, model in enumerate(_models(payload), start=1):
        path = str(model.get("path", "")).strip()
        if not path:
            continue
        label = str(model.get("label") or f"M{index}")
        depth_offset = _to_float(model.get("depthOffset"), 0.0)
        _emit("log", message=f"Opening model {label}: {path}")
        reader = open_model_reader(path)
        grids = reader.list_grids()
        selected_grid_uuid = ""
        if grids:
            selected_grid_uuid = str(model.get("gridUuid") or "").strip()
            grid = _select_grid(grids, selected_grid_uuid, label, getattr(reader, "backend", ""))
            reader.select_grid(grid.uuid)
            selected_grid_uuid = grid.uuid
        properties = reader.list_properties()
        list_horizons = getattr(reader, "list_named_horizons", None)
        try:
            named_horizons = list_horizons() if callable(list_horizons) else []
        except Exception as exc:  # noqa: BLE001
            named_horizons = []
            _emit("log", message=f"Warning: cannot read named surfaces from {label}: {exc}")
        list_trajectories = getattr(reader, "list_well_trajectories", None)
        try:
            trajectories = list_trajectories() if callable(list_trajectories) else []
        except Exception as exc:  # noqa: BLE001
            trajectories = []
            _emit("log", message=f"Warning: cannot read well trajectories from {label}: {exc}")
        summary = _model_summary(label, reader, grids, properties, trajectories, named_horizons)
        _emit("log", message=summary)
        results.append(
            {
                "path": str(reader.epc_path),
                "h5Path": str(reader.h5_path) if reader.h5_path else None,
                "backend": getattr(reader, "backend", ""),
                "label": label,
                "depthOffset": depth_offset,
                "gridUuid": selected_grid_uuid,
                "summary": summary,
                "grids": [_dataclass_dict(grid) for grid in grids],
                "properties": [_dataclass_dict(prop) for prop in properties],
                "trajectories": [_dataclass_dict(trajectory) for trajectory in trajectories],
                "namedHorizons": [_dataclass_dict(horizon) for horizon in named_horizons],
            }
        )
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
    _emit(
        "result",
        columns=[str(column) for column in raw.columns],
        guessedMapping=guessed_mapping,
        columnMapping=requested_mapping,
        warnings=warnings,
        rows=len(normalized),
        wells=[{"name": well, "count": counts.get(well, 0)} for well in wells],
        preview=_records(normalized.head(100)),
    )


def suggest_output(payload: JsonDict) -> None:
    sleeves_path = str(payload.get("sleevesPath", "")).strip()
    if not sleeves_path:
        _emit("result", outputPath="")
        return
    _emit("result", outputPath=str(default_extraction_output_path(sleeves_path)))


def extract(payload: JsonDict) -> None:
    sleeves_path = str(payload.get("sleevesPath", "")).strip()
    output_path = str(payload.get("outputPath", "")).strip()
    if not sleeves_path:
        raise ValueError("Sleeves path is empty.")
    if not output_path:
        raise ValueError("Output path is empty.")

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
    _emit("result", outputPath=str(output_plan.path), logPath=str(log_path), stats=_dataclass_dict(stats))


def table_info(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise ValueError("Table path is empty.")
    df = _deduplicate_columns(read_table(path))
    wells = _unique_strings(df.get("Well")) if "Well" in df else []
    ports = _unique_strings(df.get("Port")) if "Port" in df else []
    _emit(
        "result",
        columns=[str(column) for column in df.columns],
        rows=len(df),
        wells=wells,
        ports=ports,
        preview=_records(df.head(100)),
    )


def metrics(payload: JsonDict) -> None:
    extracted_path = str(payload.get("extractedPath", "")).strip()
    intervals_path = str(payload.get("intervalsPath", "")).strip()
    output_path = str(payload.get("outputPath", "")).strip()
    if not extracted_path or not intervals_path or not output_path:
        raise ValueError("Metrics paths are incomplete.")
    _emit("progress", value=5)
    _emit("log", message="Loading extracted cell table...")
    extracted = read_table(extracted_path)
    _emit("progress", value=35)
    _emit("log", message="Loading interval table...")
    intervals = read_table(intervals_path)
    _emit("progress", value=55)
    settings = IntervalMetricSettings(
        ntg_column=_empty_to_none(payload.get("ntgColumn")),
        poro_column=_empty_to_none(payload.get("poroColumn")),
        perm_column=_empty_to_none(payload.get("permColumn")),
        lithology_column=_empty_to_none(payload.get("lithologyColumn")),
        reservoir_values={_normalize_value(value) for value in payload.get("reservoirValues") or []},
        property_columns=[str(value) for value in payload.get("propertyColumns") or []],
        metric_keys=[str(value) for value in payload.get("metricKeys") or DEFAULT_METRIC_KEYS],
    )

    def metrics_progress(current: int, total: int) -> None:
        value = 55 + int((current / total) * 25) if total else 80
        _emit("progress", value=min(80, max(55, value)), current=current, total=total)

    _emit("log", message="Calculating interval metrics...")
    result = calculate_interval_metrics(extracted, intervals, settings, progress_callback=metrics_progress)
    for warning in result.warnings:
        _emit("log", message=f"Warning: {warning}")
    _emit("progress", value=80)
    _emit("log", message=f"Writing metrics XLSX: {output_path}")
    write_interval_metrics_xlsx(result, output_path)
    _emit("progress", value=100)
    _emit("result", outputPath=output_path, rowsWritten=len(result.rows), warnings=result.warnings)


def curve_data(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise ValueError("Curve table path is empty.")
    df = _deduplicate_columns(read_table(path))
    well = _empty_to_none(payload.get("well"))
    port = _empty_to_none(payload.get("port"))
    if well is not None and "Well" in df:
        df = df[df["Well"].map(_normalize_value) == _normalize_value(well)]
    if port is not None and "Port" in df:
        df = df[df["Port"].map(_normalize_value) == _normalize_value(port)]
    columns = [str(value) for value in payload.get("columns") or [] if str(value) in df.columns]
    depth_mode = str(payload.get("depthMode") or "individual")
    depth_col = _first_existing_column(df, ("TVD_top", "TVD_center", "TVDSS_top", "TVDSS_center"))
    if depth_col is None:
        raise ValueError("Curve table has no supported depth column.")
    channel_depth_columns: dict[str, str] = {}
    for column in columns:
        diagnostic_depth = f"{column}_TVD_center"
        if depth_mode != "common" and diagnostic_depth in df.columns:
            channel_depth_columns[column] = diagnostic_depth
        else:
            channel_depth_columns[column] = depth_col
    keep = _unique_list(
        [
            column
            for column in ["Well", "Port", "TVDSS_PORT", "Depth_KB_PORT", depth_col, *channel_depth_columns.values(), *columns]
            if column in df.columns
        ]
    )
    df = df[keep].copy()
    if depth_col in df:
        df = df.sort_values(depth_col)
    _emit(
        "result",
        depthColumn=depth_col,
        channelDepthColumns=channel_depth_columns,
        columns=columns,
        rows=_records(df.head(int(payload.get("limit") or 20000))),
    )


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
        _emit("result", **_clean_section_cache_result(cached))
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
    _emit("result", outputPath=output_path, rowsUpdated=updated, rowsRequested=len(records), rowsSkipped=len(skipped), skipped=skipped[:20])


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

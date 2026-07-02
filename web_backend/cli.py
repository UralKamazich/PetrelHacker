from __future__ import annotations

import argparse
from datetime import date, datetime
from dataclasses import asdict, is_dataclass
import errno
import json
import math
from pathlib import Path
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
from core.model_reader import open_model_reader
from core.multi_model_extractor import ExtractionModelSpec, MultiModelPropertyExtractor
from core.output_planner import choose_output_plan
from core.property_extractor import ExtractionSettings, write_extraction_log
from core.sleeves_loader import (
    apply_sleeves_column_mapping,
    filter_sleeves_by_wells,
    guess_sleeves_column_mapping,
    load_sleeves_table,
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
            "preview-sleeves",
            "suggest-output",
            "extract",
            "table-info",
            "metrics",
            "curve-data",
        ),
    )
    args = parser.parse_args(argv)

    try:
        payload = _read_payload()
        handlers: dict[str, Callable[[JsonDict], None]] = {
            "load-models": load_models,
            "preview-sleeves": preview_sleeves,
            "suggest-output": suggest_output,
            "extract": extract,
            "table-info": table_info,
            "metrics": metrics,
            "curve-data": curve_data,
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
        if grids:
            reader.select_grid(grids[0].uuid)
        properties = reader.list_properties()
        summary = _model_summary(label, reader, grids, properties)
        _emit("log", message=summary)
        results.append(
            {
                "path": str(reader.epc_path),
                "h5Path": str(reader.h5_path) if reader.h5_path else None,
                "backend": getattr(reader, "backend", ""),
                "label": label,
                "depthOffset": depth_offset,
                "summary": summary,
                "grids": [_dataclass_dict(grid) for grid in grids],
                "properties": [_dataclass_dict(prop) for prop in properties],
            }
        )
    if not results:
        raise ValueError("Select at least one model path.")
    _emit("result", models=results)


def preview_sleeves(payload: JsonDict) -> None:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise ValueError("Sleeves path is empty.")
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
    for warning in validate_sleeves_table(sleeves):
        _emit("log", message=f"Warning: {warning}")

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
            for column in ["Well", "Port", depth_col, *channel_depth_columns.values(), *columns]
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


def _read_payload() -> JsonDict:
    text = sys.stdin.read().lstrip("\ufeff")
    if not text.strip():
        return {}
    return json.loads(text)


def _models(payload: JsonDict) -> list[JsonDict]:
    models = payload.get("models")
    if isinstance(models, list):
        return [model for model in models if isinstance(model, dict)]
    path = payload.get("path") or payload.get("epcPath")
    return [{"path": path}] if path else []


def _model_summary(label: str, reader: object, grids: list[object], properties: list[object]) -> str:
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
    for prop in properties:
        title = getattr(prop, "title", "-")
        kind = getattr(prop, "property_kind", None)
        uom = getattr(prop, "uom", None)
        tail = ", ".join(value for value in [f"kind={kind}" if kind else "", f"uom={uom}" if uom else ""] if value)
        lines.append(f"    - {title}" + (f" ({tail})" if tail else ""))
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
        return _dataclass_dict(asdict(value))
    if isinstance(value, dict):
        return {str(key): _dataclass_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_dataclass_dict(item) for item in value]
    return _json_value(value)


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
    print(json.dumps(message, ensure_ascii=False), flush=True)


def _to_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


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

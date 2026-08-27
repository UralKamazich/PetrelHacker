from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from core.exporter import StreamingCsvExporter, StreamingXlsxExporter
from core.multi_model_extractor import (
    MIN_PROPERTY_VALID_OVERLAP_FRACTION,
    LoadedColumn,
    _aggregate_property_samples,
    _find_depth_k,
    _merge_depth_boundaries,
    _overlapping_cells,
)
from core.property_extractor import (
    ExtractionStats,
    _cell_center,
    _is_blank_property_value,
    _numeric_or_blank,
    _relative_depth,
    transform_property_value,
)
from core.resqml_reader import PropertyInfo


WORKSPACE_VERSION = 1
PORT_DEPTH_COLUMN = "TVDSS_PORT"
BASE_OUTPUT_COLUMNS = [
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
]


def workspace_path_for(boundary_path: str | Path) -> Path:
    path = Path(boundary_path)
    return path.with_name(f"{path.stem}_sections")


def resolve_workspace_path(path_or_boundary: str | Path) -> Path:
    path = Path(path_or_boundary)
    if path.name == "manifest.json":
        return path.parent
    if path.name.endswith("_sections") or path.is_dir():
        return path
    return workspace_path_for(path)


def save_section(
    boundary_path: str | Path,
    section_payload: dict[str, Any],
    result_payload: dict[str, Any],
    *,
    scene_settings: dict[str, Any] | None = None,
    boundary_records: list[dict[str, Any]] | None = None,
    column_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = workspace_path_for(boundary_path)
    sections_dir = workspace / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)

    rows = _result_frame(result_payload)
    if rows.empty:
        raise ValueError("The current section has no rows to save.")
    required = {"station_index", "md", "tvd_top", "tvd_base", "value"}
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise ValueError(f"Section data is incomplete: {', '.join(missing)}")

    section_id = _section_id(section_payload, result_payload)
    data_name = f"{section_id}.parquet"
    metadata_name = f"{section_id}.json"
    data_path = sections_dir / data_name
    metadata_path = sections_dir / metadata_name
    saved_at = datetime.now(UTC).isoformat()
    station_mds = _station_mds(rows)
    entry = {
        "id": section_id,
        "savedAt": saved_at,
        "dataFile": f"sections/{data_name}",
        "metadataFile": f"sections/{metadata_name}",
        "boundaryFile": Path(boundary_path).name,
        "modelPath": str(section_payload.get("path") or result_payload.get("model_path") or ""),
        "modelLabel": str(section_payload.get("modelLabel") or ""),
        "gridUuid": str(section_payload.get("gridUuid") or ""),
        "propertyUuid": str(section_payload.get("propertyUuid") or result_payload.get("property_uuid") or ""),
        "propertyTitle": str(section_payload.get("propertyTitle") or result_payload.get("property_title") or ""),
        "propertyType": _empty_or_text(section_payload.get("propertyType")),
        "propertyKind": _empty_or_text(section_payload.get("propertyKind")),
        "propertyUom": _empty_or_text(section_payload.get("propertyUom")),
        "trajectoryPath": str(section_payload.get("trajectoryPath") or section_payload.get("path") or ""),
        "trajectoryUuid": str(section_payload.get("trajectoryUuid") or result_payload.get("trajectory_uuid") or ""),
        "modelWellName": str(result_payload.get("well_name") or section_payload.get("modelWellName") or ""),
        "fracWellName": str(section_payload.get("fracWellName") or result_payload.get("well_name") or ""),
        "sampleStep": _finite_or_none(section_payload.get("sampleStep")),
        "depthOffset": _finite_or_none(section_payload.get("depthOffset")),
        "skipInactive": bool(section_payload.get("skipInactive", True)),
        "stationCount": len(station_mds),
        "cellCount": int(len(rows)),
        "stationMds": station_mds,
    }

    parquet_temp = data_path.with_name(f".{data_path.name}.tmp")
    rows.to_parquet(parquet_temp, index=False, engine="pyarrow", compression="zstd")
    parquet_temp.replace(data_path)
    metadata = {
        "version": WORKSPACE_VERSION,
        "entry": entry,
        "sectionPayload": _json_clean(section_payload),
        "result": _result_metadata(result_payload),
        "sceneSettings": _json_clean(scene_settings or {}),
        "boundaryRecords": _json_clean(boundary_records or []),
        "columnMapping": _json_clean(column_mapping or {}),
    }
    _write_json_atomic(metadata_path, metadata)

    manifest = _read_manifest(workspace, required=False)
    entries = [item for item in manifest["sections"] if item.get("id") != section_id]
    entries.append(entry)
    entries.sort(key=lambda item: (str(item.get("fracWellName", "")), str(item.get("propertyTitle", ""))))
    manifest["sections"] = entries
    manifest["updatedAt"] = saved_at
    _write_json_atomic(workspace / "manifest.json", manifest)
    return {"workspacePath": str(workspace), "section": entry, **workspace_info(workspace)}


def workspace_info(path_or_boundary: str | Path) -> dict[str, Any]:
    workspace = resolve_workspace_path(path_or_boundary)
    manifest = _read_manifest(workspace, required=False)
    entries = manifest.get("sections", [])
    wells = sorted({str(item.get("fracWellName") or item.get("modelWellName") or "") for item in entries if item})
    properties = sorted(
        {
            (str(item.get("modelLabel") or ""), str(item.get("propertyUuid") or ""), str(item.get("propertyTitle") or ""))
            for item in entries
            if item
        },
        key=lambda item: (item[0], item[2]),
    )
    size_bytes = sum(file.stat().st_size for file in workspace.rglob("*") if file.is_file()) if workspace.exists() else 0
    max_cells_per_station = max(
        (
            math.ceil(int(item.get("cellCount") or 0) / max(1, int(item.get("stationCount") or 0)))
            for item in entries
        ),
        default=0,
    )
    return {
        "workspacePath": str(workspace),
        "exists": bool(entries),
        "sectionCount": len(entries),
        "wellCount": len([well for well in wells if well]),
        "propertyCount": len(properties),
        "sizeBytes": size_bytes,
        "maxCellsPerStation": max_cells_per_station,
        "wells": [well for well in wells if well],
        "properties": [
            {"modelLabel": model, "uuid": uuid, "title": title}
            for model, uuid, title in properties
        ],
        "sections": [_section_summary(entry) for entry in entries],
    }


def load_section(workspace_path: str | Path, section_id: str) -> dict[str, Any]:
    workspace = resolve_workspace_path(workspace_path)
    manifest = _read_manifest(workspace)
    entry = next((item for item in manifest["sections"] if str(item.get("id") or "") == section_id), None)
    if entry is None:
        raise ValueError(f"Saved section was not found: {section_id}")
    metadata_path = _workspace_file(workspace, str(entry.get("metadataFile") or ""))
    data_path = _workspace_file(workspace, str(entry.get("dataFile") or ""))
    if not metadata_path.is_file() or not data_path.is_file():
        raise ValueError(f"Saved section files are incomplete: {section_id}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    rows = pd.read_parquet(data_path)
    result = dict(metadata.get("result") or {})
    result["rowColumns"] = {
        str(column): [_json_clean(value) for value in rows[column].tolist()]
        for column in rows.columns
    }
    boundary_file = str(entry.get("boundaryFile") or "")
    return {
        "workspacePath": str(workspace),
        "entry": _section_summary(entry),
        "sectionPayload": metadata.get("sectionPayload") or {},
        "result": result,
        "sceneSettings": metadata.get("sceneSettings") or {},
        "boundaryRecords": metadata.get("boundaryRecords") or [],
        "columnMapping": metadata.get("columnMapping") or {},
        "boundaryPath": str(workspace.parent / boundary_file) if boundary_file else "",
    }


def extract_workspace(
    workspace_path: str | Path,
    sleeves: pd.DataFrame,
    output_path: str | Path,
    *,
    selected_properties: dict[str, list[str]] | None = None,
    skip_inactive: bool = True,
    write_diagnostics: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> ExtractionStats:
    workspace = Path(workspace_path)
    manifest = _read_manifest(workspace)
    entries = _select_entries(manifest["sections"], selected_properties)
    if not entries:
        raise ValueError("Section workspace has no saved sections for the selected properties.")

    property_defs = _property_definitions(entries)
    output_columns = BASE_OUTPUT_COLUMNS + [
        column
        for definition in property_defs.values()
        for column in _property_columns(definition.output_name, write_diagnostics)
    ]
    exporter_class = StreamingCsvExporter if Path(output_path).suffix.lower() == ".csv" else StreamingXlsxExporter
    stats = ExtractionStats(sleeves_total=len(sleeves), started=datetime.now())
    entries_by_well = _entries_by_well(entries)
    missing_wells: set[str] = set()

    if log_callback:
        log_callback(f"Section workspace: {workspace}")
        log_callback(f"Saved sections selected: {len(entries)}, properties: {len(property_defs)}")

    with exporter_class(output_path, output_columns) as exporter:
        processed = 0
        for well, well_sleeves in sleeves.groupby("Well", sort=False, dropna=False):
            well_entries = entries_by_well.get(_normalize_well(well), [])
            if not well_entries:
                missing_wells.add(str(well))
                processed += len(well_sleeves)
                if progress_callback:
                    progress_callback(processed, len(sleeves))
                continue
            loaded = [_load_saved_section(workspace, entry, property_defs) for entry in well_entries]
            for sleeve in well_sleeves.itertuples(index=False):
                rows = _extract_sleeve_rows(
                    sleeve,
                    loaded,
                    property_defs,
                    skip_inactive=skip_inactive,
                    write_diagnostics=write_diagnostics,
                )
                exporter.write_rows(rows)
                if rows:
                    stats.sleeves_inside_grid += 1
                else:
                    stats.sleeves_outside_grid += 1
                stats.extracted_rows += len(rows)
                processed += 1
                if progress_callback:
                    progress_callback(processed, len(sleeves))

    if missing_wells:
        warning = "No saved sections for wells: " + ", ".join(sorted(missing_wells))
        stats.warnings.append(warning)
        if log_callback:
            log_callback(f"Warning: {warning}")
        stats.sleeves_outside_grid += sum(
            1 for value in sleeves["Well"] if _normalize_well(value) in {_normalize_well(item) for item in missing_wells}
        )
    stats.finished = datetime.now()
    return stats


@dataclass(frozen=True)
class _PropertyDefinition:
    key: tuple[str, str]
    info: PropertyInfo
    output_name: str


@dataclass
class _SavedSection:
    entry: dict[str, Any]
    definition: _PropertyDefinition
    rows: pd.DataFrame


def _extract_sleeve_rows(
    sleeve: Any,
    sections: list[_SavedSection],
    property_defs: dict[tuple[str, str], _PropertyDefinition],
    *,
    skip_inactive: bool,
    write_diagnostics: bool,
) -> list[dict[str, Any]]:
    md = _numeric_or_blank(getattr(sleeve, "MD", ""))
    if md == "":
        return []
    columns: list[tuple[_SavedSection, LoadedColumn, list[int]]] = []
    for section in sections:
        station = _nearest_station(section.entry.get("stationMds") or [], float(md))
        if station is None:
            continue
        station_rows = section.rows[section.rows["station_index"] == station].copy()
        if station_rows.empty:
            continue
        station_rows = station_rows.sort_values(["tvd_top", "tvd_base", "k"], kind="stable")
        tops = pd.to_numeric(station_rows["tvd_top"], errors="coerce").tolist()
        bases = pd.to_numeric(station_rows["tvd_base"], errors="coerce").tolist()
        values = station_rows["value"].tolist()
        source_k = pd.to_numeric(station_rows.get("k"), errors="coerce").fillna(0).astype(int).tolist()
        i_value = _first_int(station_rows.get("i"), default=1) - 1
        j_value = _first_int(station_rows.get("j"), default=1) - 1
        column = LoadedColumn(
            i=max(0, i_value),
            j=max(0, j_value),
            geometry={
                "TVD_top": tops,
                "TVD_base": bases,
                "CellHeight": [abs(float(base) - float(top)) for top, base in zip(tops, bases, strict=False)],
            },
            active=None,
            property_columns={section.definition.info.uuid: values},
        )
        columns.append((section, column, source_k))
    if not columns:
        return []

    boundaries = _merge_depth_boundaries(
        [value for _section, column, _source_k in columns for key in ("TVD_top", "TVD_base") for value in column.geometry[key]]
    )
    segments = [(top, base) for top, base in zip(boundaries, boundaries[1:], strict=False) if base > top]
    well = getattr(sleeve, "Well", "")
    port = getattr(sleeve, "Port", "")
    x = _numeric_or_blank(getattr(sleeve, "X", ""))
    y = _numeric_or_blank(getattr(sleeve, "Y", ""))
    port_tvd = _numeric_or_blank(getattr(sleeve, PORT_DEPTH_COLUMN, ""))
    rows: list[dict[str, Any]] = []
    for segment_index, (top, base) in enumerate(segments, start=1):
        center = _cell_center(top, base)
        geometry = next(
            ((column, _find_depth_k(column, center)) for _section, column, _source_k in columns if _find_depth_k(column, center) is not None),
            None,
        )
        row = {
            "Well": well,
            "Port": port,
            "X": x,
            "Y": y,
            PORT_DEPTH_COLUMN: port_tvd,
            "Datum_Z": "",
            "Depth_KB_PORT": "",
            "I": "" if geometry is None else geometry[0].i + 1,
            "J": "" if geometry is None else geometry[0].j + 1,
            "K": segment_index,
            "IsActive": False,
            "TVDSS_top": top,
            "TVDSS_base": base,
            "TVDSS_center": center,
            "TVD_top": top,
            "TVD_base": base,
            "TVD_center": center,
            "Depth_KB_top": "",
            "Depth_KB_base": "",
            "Depth_KB_center": "",
            "Rel_TVD_top": _relative_depth(top, port_tvd),
            "Rel_TVD_base": _relative_depth(base, port_tvd),
            "Rel_TVD_center": _relative_depth(center, port_tvd),
            "CellHeight": abs(base - top),
            "CellSizeI": "",
            "CellSizeJ": "",
            "CellAreaXY": "",
        }
        for definition in property_defs.values():
            row.update(_blank_property_values(definition.output_name, write_diagnostics))

        any_value = False
        for section, column, source_k in columns:
            definition = section.definition
            overlaps = _overlapping_cells(column, top, base)
            total_weight = sum(weight for _index, weight in overlaps)
            samples: list[tuple[object, float, int]] = []
            for index, weight in overlaps:
                value = column.property_columns[definition.info.uuid][index]
                value = transform_property_value(definition.info, value)
                if not _is_blank_property_value(value):
                    samples.append((value, weight, index))
            valid_weight = sum(weight for _value, weight, _index in samples)
            if not samples or (total_weight > 0 and valid_weight < total_weight * MIN_PROPERTY_VALID_OVERLAP_FRACTION):
                continue
            value = _aggregate_property_samples(definition.info, [(value, weight) for value, weight, _index in samples])
            row[definition.output_name] = value
            row["IsActive"] = True
            any_value = True
            if write_diagnostics:
                _value, _weight, index = max(samples, key=lambda item: item[1])
                row.update(
                    {
                        f"{definition.output_name}_Model": section.entry.get("modelLabel", ""),
                        f"{definition.output_name}_I": column.i + 1,
                        f"{definition.output_name}_J": column.j + 1,
                        f"{definition.output_name}_K": source_k[index] if index < len(source_k) else index + 1,
                        f"{definition.output_name}_TVD_center": _cell_center(
                            column.geometry["TVD_top"][index], column.geometry["TVD_base"][index]
                        ),
                        f"{definition.output_name}_Depth_KB": "",
                    }
                )
        if skip_inactive and not any_value:
            continue
        rows.append(row)
    return rows


def _select_entries(entries: list[dict[str, Any]], selected: dict[str, list[str]] | None) -> list[dict[str, Any]]:
    if not selected:
        return _latest_entries(entries)
    allowed = {(str(label), str(uuid)) for label, uuids in selected.items() for uuid in uuids}
    return _latest_entries(
        [entry for entry in entries if (str(entry.get("modelLabel") or ""), str(entry.get("propertyUuid") or "")) in allowed]
    )


def _latest_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (
            _normalize_well(entry.get("fracWellName") or entry.get("modelWellName")),
            str(entry.get("modelLabel") or ""),
            str(entry.get("propertyUuid") or ""),
        )
        current = latest.get(key)
        if current is None or str(entry.get("savedAt") or "") > str(current.get("savedAt") or ""):
            latest[key] = entry
    return list(latest.values())


def _property_definitions(entries: list[dict[str, Any]]) -> dict[tuple[str, str], _PropertyDefinition]:
    metadata: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (str(entry.get("modelLabel") or ""), str(entry.get("propertyUuid") or ""))
        metadata.setdefault(key, entry)
    title_counts: dict[str, int] = {}
    for entry in metadata.values():
        title = str(entry.get("propertyTitle") or entry.get("propertyUuid") or "Property")
        title_counts[title] = title_counts.get(title, 0) + 1
    definitions: dict[tuple[str, str], _PropertyDefinition] = {}
    used: set[str] = set()
    for key, entry in metadata.items():
        title = str(entry.get("propertyTitle") or entry.get("propertyUuid") or "Property")
        base = title if title_counts[title] == 1 else f"{entry.get('modelLabel') or 'Model'}_{title}"
        output_name = base
        counter = 2
        while output_name in used:
            output_name = f"{base}_{counter}"
            counter += 1
        used.add(output_name)
        prop = PropertyInfo(
            index=0,
            title=title,
            uuid=str(entry.get("propertyUuid") or title),
            uom=_empty_or_text(entry.get("propertyUom")),
            property_kind=_empty_or_text(entry.get("propertyKind")),
            property_type=_empty_or_text(entry.get("propertyType")),
            supporting_grid_uuid=_empty_or_text(entry.get("gridUuid")),
        )
        definitions[key] = _PropertyDefinition(key=key, info=prop, output_name=output_name)
    return definitions


def _load_saved_section(
    workspace: Path,
    entry: dict[str, Any],
    definitions: dict[tuple[str, str], _PropertyDefinition],
) -> _SavedSection:
    key = (str(entry.get("modelLabel") or ""), str(entry.get("propertyUuid") or ""))
    data_path = workspace / str(entry.get("dataFile") or "")
    if not data_path.is_file():
        raise ValueError(f"Saved section data is missing: {data_path}")
    return _SavedSection(entry=entry, definition=definitions[key], rows=pd.read_parquet(data_path))


def _entries_by_well(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        key = _normalize_well(entry.get("fracWellName") or entry.get("modelWellName"))
        if key:
            result.setdefault(key, []).append(entry)
    return result


def _nearest_station(stations: list[dict[str, Any]], md: float) -> int | None:
    candidates = [
        (abs(float(item["md"]) - md), int(item["stationIndex"]))
        for item in stations
        if _is_finite(item.get("md")) and item.get("stationIndex") is not None
    ]
    if not candidates:
        return None
    distance, index = min(candidates)
    return index if distance <= 0.5 else None


def _station_mds(rows: pd.DataFrame) -> list[dict[str, Any]]:
    stations = rows[["station_index", "md"]].drop_duplicates(subset=["station_index"]).sort_values("station_index")
    return [
        {"stationIndex": int(row.station_index), "md": _finite_or_none(row.md)}
        for row in stations.itertuples(index=False)
    ]


def _result_frame(result: dict[str, Any]) -> pd.DataFrame:
    if isinstance(result.get("rows"), list):
        return pd.DataFrame(result["rows"])
    columns = result.get("rowColumns")
    if isinstance(columns, dict):
        return pd.DataFrame(columns)
    return pd.DataFrame()


def _result_metadata(result: dict[str, Any]) -> dict[str, Any]:
    return _json_clean({key: value for key, value in result.items() if key not in {"rows", "rowColumns"}})


def _section_id(section: dict[str, Any], result: dict[str, Any]) -> str:
    identity = {
        "modelPath": section.get("path") or result.get("model_path"),
        "gridUuid": section.get("gridUuid"),
        "propertyUuid": section.get("propertyUuid") or result.get("property_uuid"),
        "trajectoryPath": section.get("trajectoryPath") or section.get("path"),
        "trajectoryUuid": section.get("trajectoryUuid") or result.get("trajectory_uuid"),
        "sampleStep": section.get("sampleStep"),
        "depthOffset": section.get("depthOffset"),
        "skipInactive": section.get("skipInactive"),
    }
    raw = json.dumps(_json_clean(identity), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _section_summary(entry: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "savedAt",
        "boundaryFile",
        "modelPath",
        "modelLabel",
        "gridUuid",
        "propertyUuid",
        "propertyTitle",
        "propertyType",
        "propertyKind",
        "propertyUom",
        "trajectoryPath",
        "trajectoryUuid",
        "modelWellName",
        "fracWellName",
        "sampleStep",
        "depthOffset",
        "skipInactive",
        "stationCount",
        "cellCount",
    )
    return {key: _json_clean(entry.get(key)) for key in keys}


def _workspace_file(workspace: Path, relative_path: str) -> Path:
    if not relative_path:
        return workspace / "__missing__"
    workspace_root = workspace.resolve()
    path = (workspace / relative_path).resolve()
    if path != workspace_root and workspace_root not in path.parents:
        raise ValueError("Section workspace contains an invalid file path.")
    return path


def _read_manifest(workspace: Path, *, required: bool = True) -> dict[str, Any]:
    manifest_path = workspace / "manifest.json"
    if not manifest_path.is_file():
        if required:
            raise ValueError(f"Section workspace was not found: {workspace}")
        return {"version": WORKSPACE_VERSION, "createdAt": datetime.now(UTC).isoformat(), "sections": []}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if int(data.get("version") or 0) != WORKSPACE_VERSION:
        raise ValueError(f"Unsupported section workspace version: {data.get('version')}")
    if not isinstance(data.get("sections"), list):
        raise ValueError("Section workspace manifest is damaged.")
    return data


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(_json_clean(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _property_columns(name: str, diagnostics: bool) -> list[str]:
    columns = [name]
    if diagnostics:
        columns.extend([f"{name}_Model", f"{name}_I", f"{name}_J", f"{name}_K", f"{name}_TVD_center", f"{name}_Depth_KB"])
    return columns


def _blank_property_values(name: str, diagnostics: bool) -> dict[str, Any]:
    return {column: "" for column in _property_columns(name, diagnostics)}


def _first_int(values: Any, *, default: int) -> int:
    if values is None:
        return default
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return int(numeric.iloc[0]) if len(numeric) else default


def _normalize_well(value: Any) -> str:
    text = "" if value is None else str(value).strip().upper()
    transliteration = str.maketrans("АВЕКМНОРСТХ", "ABEKMHOPCTX")
    return "".join(character for character in text.translate(transliteration) if character.isalnum())


def _empty_or_text(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_finite(value: Any) -> bool:
    return _finite_or_none(value) is not None


def _json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value

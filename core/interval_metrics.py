from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import re

import pandas as pd

from core.exporter import export_xlsx


INTERVAL_COLUMNS = (
    "Well",
    "Port",
    "TVDSS_TOP_TOTAL",
    "TVDSS_BOT_TOTAL",
    "TVDSS_TOP_LOCAL",
    "TVDSS_BOT_LOCAL",
)
BASE_EXTRACTION_COLUMNS = {
    "Well",
    "Port",
    "X",
    "Y",
    "I",
    "J",
    "K",
    "IsActive",
    "TVD_top",
    "TVD_base",
    "CellHeight",
    "CellSizeI",
    "CellSizeJ",
    "CellAreaXY",
    "WellKey",
    "PortKey",
    "XKey",
    "YKey",
}
INTERVAL_BUFFER_METERS = 15.0
INTERVAL_DEFINITIONS = (
    ("Global", "TVDSS_TOP_TOTAL", "TVDSS_BOT_TOTAL", 0.0, 0.0),
    ("Local", "TVDSS_TOP_LOCAL", "TVDSS_BOT_LOCAL", 0.0, 0.0),
    ("Total_pm15m", "TVDSS_TOP_TOTAL", "TVDSS_BOT_TOTAL", -INTERVAL_BUFFER_METERS, INTERVAL_BUFFER_METERS),
    ("TopTotal_m15m", "TVDSS_TOP_TOTAL", "TVDSS_TOP_TOTAL", -INTERVAL_BUFFER_METERS, 0.0),
    ("BotTotal_p15m", "TVDSS_BOT_TOTAL", "TVDSS_BOT_TOTAL", 0.0, INTERVAL_BUFFER_METERS),
)
BASE_METRIC_KEYS = (
    "thickness",
    "net_thickness",
    "ntg_avg",
    "ntg_median",
    "poro_avg",
    "poro_median",
    "perm_avg_arith",
    "perm_avg_geom",
    "perm_median",
    "kh",
    "phih",
)
PROPERTY_METRIC_KEYS = (
    "avg",
    "mean_arith",
    "geom",
    "median",
    "min",
    "max",
    "integral",
    "min_star",
    "max_star",
    "std",
    "delta",
)
DEFAULT_METRIC_KEYS = BASE_METRIC_KEYS + PROPERTY_METRIC_KEYS


@dataclass(frozen=True)
class IntervalMetricSettings:
    ntg_column: str | None = "NTG"
    poro_column: str | None = "PORO"
    perm_column: str | None = None
    lithology_column: str | None = None
    reservoir_values: set[str] = field(default_factory=set)
    property_columns: list[str] = field(default_factory=list)
    metric_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IntervalMetricResult:
    rows: list[dict]
    warnings: list[str]


def calculate_interval_metrics(
    extracted_df: pd.DataFrame,
    intervals_df: pd.DataFrame,
    settings: IntervalMetricSettings | None = None,
) -> IntervalMetricResult:
    settings = settings or IntervalMetricSettings()
    extracted = _normalize_identity_columns(extracted_df.copy())
    intervals = _normalize_identity_columns(intervals_df.copy())
    warnings = _validate_inputs(extracted, intervals)
    if warnings:
        return IntervalMetricResult(rows=[], warnings=warnings)

    extracted["WellKey"] = extracted["Well"].map(_normalize_value)
    extracted["PortKey"] = extracted["Port"].map(_normalize_value)
    intervals["WellKey"] = intervals["Well"].map(_normalize_value)
    intervals["PortKey"] = intervals["Port"].map(_normalize_value)
    extracted["CellCenterTVD"] = (_numeric(extracted["TVD_top"]) + _numeric(extracted["TVD_base"])) / 2.0
    extracted["CellHeight"] = _numeric(extracted["CellHeight"])

    property_columns = _additional_property_columns(
        settings,
        settings.property_columns or _default_property_columns(extracted.columns),
    )
    metric_keys = _metric_key_set(settings.metric_keys)
    warnings.extend(_settings_warnings(extracted, settings, property_columns))
    rows: list[dict] = []
    grouped = {
        (str(well), str(port)): group
        for (well, port), group in extracted.groupby(["WellKey", "PortKey"], dropna=False)
    }
    xy_grouped = _xy_groups(extracted)

    for _, interval in intervals.iterrows():
        well = _normalize_value(interval["Well"])
        port = _normalize_value(interval["Port"])
        row: dict = _interval_base_row(interval)
        row["Well"] = well
        row["Port"] = port
        cells = grouped.get((well, port))
        if cells is None:
            cells = _cells_by_xy(interval, xy_grouped)
        if cells is None:
            warnings.append(f"No extracted cells found for {well}_{port}; tried Well/Port and X/Y.")
            rows.append(row)
            continue

        interval_sets: dict[str, pd.DataFrame] = {}
        for name, top_col, bot_col, top_delta, bot_delta in INTERVAL_DEFINITIONS:
            top = _to_float(interval.get(top_col))
            bot = _to_float(interval.get(bot_col))
            if top is None or bot is None:
                warnings.append(f"{well}_{port}: missing interval bounds for {name}.")
                interval_sets[name] = cells.iloc[0:0]
                interval_sets[f"{name}_Net"] = cells.iloc[0:0]
                interval_sets[f"{name}_NonNet"] = cells.iloc[0:0]
                continue
            top += top_delta
            bot += bot_delta
            interval_cells = _cells_in_interval(cells, top, bot)
            net_cells = _net_cells(interval_cells, settings)
            interval_sets[name] = interval_cells
            interval_sets[f"{name}_Net"] = net_cells
            interval_sets[f"{name}_NonNet"] = _non_net_cells(interval_cells, net_cells)

        metric_suffixes = _metric_suffixes()
        for suffix in metric_suffixes:
            _add_base_metrics(row, interval_sets.get(suffix, cells.iloc[0:0]), suffix, settings, metric_keys)
        for suffix in metric_suffixes:
            _add_property_metrics(row, interval_sets.get(suffix, cells.iloc[0:0]), suffix, property_columns, metric_keys)

        rows.append(row)

    return IntervalMetricResult(rows=rows, warnings=warnings)


def write_interval_metrics_xlsx(result: IntervalMetricResult, output_path: str | Path) -> None:
    export_xlsx(pd.DataFrame(result.rows), output_path)


def _validate_inputs(extracted: pd.DataFrame, intervals: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    missing_extracted = [column for column in ("Well", "Port", "TVD_top", "TVD_base", "CellHeight") if column not in extracted]
    missing_intervals = [column for column in INTERVAL_COLUMNS if column not in intervals]
    if missing_extracted:
        warnings.append(f"Extracted table is missing columns: {', '.join(missing_extracted)}.")
    if missing_intervals:
        warnings.append(f"Intervals table is missing columns: {', '.join(missing_intervals)}.")
    return warnings


def _interval_base_row(interval: pd.Series) -> dict:
    return {
        str(column): _clean_output_value(value)
        for column, value in interval.items()
        if str(column) not in {"WellKey", "PortKey"} and not _is_computed_metric_column(str(column))
    }


def _is_computed_metric_column(column: str) -> bool:
    if re.match(r"^(Thickness|NetThickness|NTG|PORO|PERM|KH|PHIH)_(Global|Local)(?:_Net)?$", column):
        return True
    if re.match(r"^(NTG|PORO|PERM)_(avg|median|avg_arith|avg_geom)_(Global|Local)(?:_Net)?$", column):
        return True
    if re.match(r"^(CellCount|CollectorCellCount)_(Global|Local)(?:_Net)?$", column):
        return True
    interval_names = "|".join(re.escape(name) for name, *_rest in INTERVAL_DEFINITIONS)
    suffix = rf"(?:{interval_names})(?:_(?:Net|NonNet))?"
    if re.match(rf"^(Thickness|NetThickness|NTG|PORO|PERM|KH|PHIH)_{suffix}$", column):
        return True
    if re.match(rf"^(NTG|PORO|PERM)_(avg|median|avg_arith|avg_geom)_{suffix}$", column):
        return True
    return bool(
        re.match(
            rf"^.+_(avg|mean_arith|geom|median|min|max|integral|min_star|max_star|std|delta)_{suffix}$",
            column,
        )
    )


def _settings_warnings(
    extracted: pd.DataFrame,
    settings: IntervalMetricSettings,
    property_columns: list[str],
) -> list[str]:
    warnings: list[str] = []
    for label, column in (
        ("NTG", settings.ntg_column),
        ("PORO", settings.poro_column),
        ("PERM", settings.perm_column),
        ("lithology", settings.lithology_column),
    ):
        if column and column not in extracted.columns:
            warnings.append(f"Configured {label} column is missing from extracted table: {column}.")
    missing_properties = [column for column in property_columns if column not in extracted.columns]
    if missing_properties:
        warnings.append(f"Selected property columns are missing: {', '.join(missing_properties)}.")
    if settings.lithology_column and not settings.reservoir_values:
        warnings.append("Lithology column is configured, but no reservoir values were provided.")
    has_lithology_net = bool(settings.lithology_column and settings.lithology_column in extracted.columns and settings.reservoir_values)
    has_ntg_net = bool(settings.ntg_column and settings.ntg_column in extracted.columns)
    if not has_lithology_net and not has_ntg_net:
        warnings.append("Net metrics use all interval cells because no NTG or lithology net filter is available.")
    return warnings


def _normalize_identity_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = _restore_pandas_duplicate_column_names(df)
    rename: dict[str, str] = {}
    for column in df.columns:
        normalized = str(column).strip().lower().replace(" ", "_").replace("-", "_")
        if normalized in {"well", "well_name"}:
            rename[column] = "Well"
        elif normalized in {"port", "stage", "port_id"}:
            rename[column] = "Port"
        elif normalized in {"x", "coord_x", "coordinate_x"}:
            rename[column] = "X"
        elif normalized in {"y", "coord_y", "coordinate_y"}:
            rename[column] = "Y"
    return _deduplicate_columns(df.rename(columns=rename))


def _restore_pandas_duplicate_column_names(df: pd.DataFrame) -> pd.DataFrame:
    existing = {str(column) for column in df.columns}
    rename: dict[object, str] = {}
    for column in df.columns:
        text = str(column)
        match = re.match(r"^(.+)\.(\d+)$", text)
        if match and match.group(1) in existing:
            rename[column] = match.group(1)
    return df.rename(columns=rename)


def _deduplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not df.columns.duplicated().any():
        return df
    data: dict[str, pd.Series] = {}
    for column in dict.fromkeys(df.columns):
        subset = df.loc[:, df.columns == column]
        if subset.shape[1] == 1:
            data[str(column)] = subset.iloc[:, 0]
        else:
            data[str(column)] = subset.replace("", pd.NA).bfill(axis=1).iloc[:, 0].fillna("")
    return pd.DataFrame(data, index=df.index)


def _xy_groups(extracted: pd.DataFrame) -> dict[tuple[float, float], pd.DataFrame]:
    if "X" not in extracted.columns or "Y" not in extracted.columns:
        return {}
    prepared = extracted.copy()
    prepared["XKey"] = _numeric(prepared["X"]).round(3)
    prepared["YKey"] = _numeric(prepared["Y"]).round(3)
    return {
        (float(x), float(y)): group
        for (x, y), group in prepared.groupby(["XKey", "YKey"], dropna=False)
        if not pd.isna(x) and not pd.isna(y)
    }


def _cells_by_xy(interval: pd.Series, xy_grouped: dict[tuple[float, float], pd.DataFrame]) -> pd.DataFrame | None:
    if not xy_grouped or "X" not in interval.index or "Y" not in interval.index:
        return None
    x = _to_float(interval.get("X"))
    y = _to_float(interval.get("Y"))
    if x is None or y is None:
        return None
    return xy_grouped.get((round(x, 3), round(y, 3)))


def _cells_in_interval(cells: pd.DataFrame, top: float, bot: float) -> pd.DataFrame:
    low = min(top, bot)
    high = max(top, bot)
    tops = _numeric(cells["TVD_top"])
    bases = _numeric(cells["TVD_base"])
    cell_low = pd.concat([tops, bases], axis=1).min(axis=1)
    cell_high = pd.concat([tops, bases], axis=1).max(axis=1)
    overlap = (cell_high.clip(upper=high) - cell_low.clip(lower=low)).clip(lower=0.0)
    selected = cells[overlap > 0.0].copy()
    selected["MetricCellHeight"] = overlap[overlap > 0.0]
    return selected


def _add_base_metrics(
    row: dict,
    cells: pd.DataFrame,
    suffix: str,
    settings: IntervalMetricSettings,
    metric_keys: set[str],
) -> None:
    heights = _metric_heights(cells)
    ntg = _optional_numeric(cells, settings.ntg_column)
    poro = _optional_numeric(cells, settings.poro_column)
    perm = _optional_numeric(cells, settings.perm_column) if settings.perm_column else _auto_perm(cells)

    if "thickness" in metric_keys:
        row[f"Thickness_{suffix}"] = _sum(heights)
    if "net_thickness" in metric_keys and not suffix.endswith("_Net"):
        row[f"NetThickness_{suffix}"] = _sum(heights * ntg) if ntg is not None else ""
    if "ntg_avg" in metric_keys:
        row[f"NTG_avg_{suffix}"] = _mean(ntg, heights) if ntg is not None else ""
    if "ntg_median" in metric_keys:
        row[f"NTG_median_{suffix}"] = _median(ntg) if ntg is not None else ""
    if "poro_avg" in metric_keys:
        row[f"PORO_avg_{suffix}"] = _mean(poro, heights) if poro is not None else ""
    if "poro_median" in metric_keys:
        row[f"PORO_median_{suffix}"] = _median(poro) if poro is not None else ""
    if "perm_avg_arith" in metric_keys:
        row[f"PERM_avg_arith_{suffix}"] = _mean(perm, heights) if perm is not None else ""
    if "perm_avg_geom" in metric_keys:
        row[f"PERM_avg_geom_{suffix}"] = _geom_mean(perm, heights) if perm is not None else ""
    if "perm_median" in metric_keys:
        row[f"PERM_median_{suffix}"] = _median(perm) if perm is not None else ""
    if "kh" in metric_keys:
        row[f"KH_{suffix}"] = _sum(perm * heights * (ntg if ntg is not None else 1.0)) if perm is not None else ""
    if "phih" in metric_keys:
        row[f"PHIH_{suffix}"] = _sum(poro * heights * (ntg if ntg is not None else 1.0)) if poro is not None else ""


def _add_property_metrics(
    row: dict,
    cells: pd.DataFrame,
    suffix: str,
    property_columns: list[str],
    metric_keys: set[str],
) -> None:
    heights = _metric_heights(cells)
    for column in property_columns:
        values = _optional_numeric(cells, column)
        if values is None:
            continue
        if "avg" in metric_keys:
            row[f"{column}_avg_{suffix}"] = _mean(values, heights)
        if "mean_arith" in metric_keys:
            row[f"{column}_mean_arith_{suffix}"] = _mean(values, heights)
        if "geom" in metric_keys:
            row[f"{column}_geom_{suffix}"] = _geom_mean(values, heights)
        if "median" in metric_keys:
            row[f"{column}_median_{suffix}"] = _median(values)
        if "min" in metric_keys:
            row[f"{column}_min_{suffix}"] = _min(values)
        if "max" in metric_keys:
            row[f"{column}_max_{suffix}"] = _max(values)
        if "integral" in metric_keys:
            row[f"{column}_integral_{suffix}"] = _sum(values * heights)
        if "min_star" in metric_keys:
            row[f"{column}_min_star_{suffix}"] = _robust_tail_mean(values, lower=True)
        if "max_star" in metric_keys:
            row[f"{column}_max_star_{suffix}"] = _robust_tail_mean(values, lower=False)
        if "std" in metric_keys:
            row[f"{column}_std_{suffix}"] = _std(values, heights)
        if "delta" in metric_keys:
            row[f"{column}_delta_{suffix}"] = _delta_star(values)


def _net_cells(cells: pd.DataFrame, settings: IntervalMetricSettings) -> pd.DataFrame:
    if settings.lithology_column and settings.lithology_column in cells.columns and settings.reservoir_values:
        values = cells[settings.lithology_column].map(_normalize_value)
        return cells[values.isin(settings.reservoir_values)]
    if settings.ntg_column and settings.ntg_column in cells.columns:
        return cells[_numeric(cells[settings.ntg_column]) > 0]
    return cells


def _non_net_cells(cells: pd.DataFrame, net_cells: pd.DataFrame) -> pd.DataFrame:
    if cells.empty:
        return cells
    if net_cells.empty:
        return cells
    return cells.loc[~cells.index.isin(net_cells.index)]


def _metric_suffixes() -> tuple[str, ...]:
    values: list[str] = []
    for name, _top_col, _bot_col, _top_delta, _bot_delta in INTERVAL_DEFINITIONS:
        values.extend([name, f"{name}_Net", f"{name}_NonNet"])
    return tuple(values)


def _default_property_columns(columns) -> list[str]:
    return [str(column) for column in columns if str(column) not in BASE_EXTRACTION_COLUMNS and str(column) != "CellCenterTVD"]


def _additional_property_columns(settings: IntervalMetricSettings, property_columns: list[str]) -> list[str]:
    base_columns = {settings.ntg_column, settings.poro_column, settings.perm_column}
    return [column for column in property_columns if column and column not in base_columns]


def _metric_key_set(metric_keys: list[str]) -> set[str]:
    selected = set(metric_keys)
    if not selected:
        return set(DEFAULT_METRIC_KEYS)
    return selected & set(DEFAULT_METRIC_KEYS)


def _auto_perm(cells: pd.DataFrame) -> pd.Series | None:
    for column in cells.columns:
        if "perm" in str(column).lower():
            return _numeric(cells[column])
    return None


def _optional_numeric(df: pd.DataFrame, column: str | None) -> pd.Series | None:
    if not column or column not in df.columns:
        return None
    return _numeric(df[column])


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _metric_heights(cells: pd.DataFrame) -> pd.Series:
    if "MetricCellHeight" in cells:
        return _numeric(cells["MetricCellHeight"])
    if "CellHeight" in cells:
        return _numeric(cells["CellHeight"])
    return pd.Series(dtype=float)


def _to_float(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _valid(series: pd.Series) -> pd.Series:
    return series.dropna()


def _sum(series: pd.Series) -> float:
    values = _valid(series)
    return float(values.sum()) if len(values) else 0.0


def _mean(series: pd.Series, weights: pd.Series | None = None) -> float | str:
    values = _valid(series)
    if weights is not None and len(values):
        aligned_weights = _numeric(weights).reindex(values.index).dropna()
        aligned_values = values.reindex(aligned_weights.index)
        total_weight = aligned_weights.sum()
        if len(aligned_values) and total_weight > 0.0:
            return float((aligned_values * aligned_weights).sum() / total_weight)
    return float(values.mean()) if len(values) else ""


def _median(series: pd.Series) -> float | str:
    values = _valid(series)
    return float(values.median()) if len(values) else ""


def _min(series: pd.Series) -> float | str:
    values = _valid(series)
    return float(values.min()) if len(values) else ""


def _max(series: pd.Series) -> float | str:
    values = _valid(series)
    return float(values.max()) if len(values) else ""


def _geom_mean(series: pd.Series, weights: pd.Series | None = None) -> float | str:
    values = _valid(series)
    values = values[values > 0]
    if not len(values):
        return ""
    logs = values.map(math.log)
    if weights is not None:
        aligned_weights = _numeric(weights).reindex(logs.index).dropna()
        aligned_logs = logs.reindex(aligned_weights.index)
        total_weight = aligned_weights.sum()
        if len(aligned_logs) and total_weight > 0.0:
            return float(math.exp((aligned_logs * aligned_weights).sum() / total_weight))
    return float(math.exp(logs.mean()))


def _std(series: pd.Series, weights: pd.Series | None = None) -> float | str:
    values = _valid(series)
    if weights is not None and len(values):
        aligned_weights = _numeric(weights).reindex(values.index).dropna()
        aligned_values = values.reindex(aligned_weights.index)
        total_weight = aligned_weights.sum()
        if len(aligned_values) and total_weight > 0.0:
            mean = (aligned_values * aligned_weights).sum() / total_weight
            variance = (((aligned_values - mean) ** 2) * aligned_weights).sum() / total_weight
            return float(math.sqrt(variance))
    return float(values.std(ddof=0)) if len(values) else ""


def _delta_star(series: pd.Series) -> float | str:
    min_star = _robust_tail_mean(series, lower=True)
    max_star = _robust_tail_mean(series, lower=False)
    if min_star == "" or max_star == "":
        return ""
    return float(max_star) - float(min_star)


def _robust_tail_mean(series: pd.Series, *, lower: bool) -> float | str:
    values = _valid(series).astype(float).sort_values()
    if not len(values):
        return ""
    filtered = _drop_iqr_outliers(values)
    if not len(filtered):
        filtered = values
    tail_count = max(1, math.ceil(len(filtered) * 0.1))
    tail = filtered.head(tail_count) if lower else filtered.tail(tail_count)
    return float(tail.mean())


def _drop_iqr_outliers(values: pd.Series) -> pd.Series:
    if len(values) < 4:
        return values
    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return values
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    return values[(values >= low) & (values <= high)]


def _normalize_value(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        return text[:-2]
    return text


def _clean_output_value(value: object) -> object:
    if pd.isna(value):
        return ""
    return value

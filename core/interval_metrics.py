from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import math
import re
from typing import Callable

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
    "TVDSS_PORT",
    "TVDSS_TOP_TOTAL",
    "TVDSS_BOT_TOTAL",
    "TVDSS_TOP_LOCAL",
    "TVDSS_BOT_LOCAL",
    "MD",
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
# Fixed channels are written under a stable output name regardless of the source column,
# so metric files from different models share the same columns.
FIXED_PROPERTY_CHANNELS = (
    ("Density", "density_column"),
    ("Shmin", "shmin_column"),
)
MetricProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class IntervalMetricSettings:
    ntg_column: str | None = "NTG"
    poro_column: str | None = "PORO"
    perm_column: str | None = None
    lithology_column: str | None = None
    density_column: str | None = None
    shmin_column: str | None = None
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
    progress_callback: MetricProgressCallback | None = None,
) -> IntervalMetricResult:
    settings = settings or IntervalMetricSettings()
    extracted = _normalize_identity_columns(extracted_df.copy())
    intervals = _normalize_identity_columns(intervals_df.copy())
    validation_warnings = _validate_inputs(extracted, intervals)
    if validation_warnings:
        return IntervalMetricResult(rows=[], warnings=validation_warnings)
    warnings: list[str] = []

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

    total_intervals = len(intervals)
    missing_cells: list[tuple[str, str]] = []
    missing_bounds: dict[str, list[tuple[str, str]]] = {}
    for interval_index, (_index, interval) in enumerate(intervals.iterrows(), start=1):
        well = _normalize_value(interval["Well"])
        port = _normalize_value(interval["Port"])
        row: dict = _interval_base_row(interval)
        row["Well"] = well
        row["Port"] = port
        cells = grouped.get((well, port))
        if cells is None:
            cells = _cells_by_xy(interval, xy_grouped)
        if cells is None:
            missing_cells.append((well, port))
            rows.append(row)
            continue

        interval_sets: dict[str, pd.DataFrame] = {}
        for name, top_col, bot_col, top_delta, bot_delta in INTERVAL_DEFINITIONS:
            top = _to_float(interval.get(top_col))
            bot = _to_float(interval.get(bot_col))
            if top is None or bot is None:
                missing_bounds.setdefault(name, []).append((well, port))
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
        for name, attribute in FIXED_PROPERTY_CHANNELS:
            column = getattr(settings, attribute)
            for suffix in metric_suffixes:
                interval_cells = interval_sets.get(suffix, cells.iloc[0:0])
                _add_channel_metrics(
                    row,
                    name,
                    _optional_numeric(interval_cells, column),
                    _metric_heights(interval_cells),
                    suffix,
                    metric_keys,
                )
        for suffix in metric_suffixes:
            _add_property_metrics(row, interval_sets.get(suffix, cells.iloc[0:0]), suffix, property_columns, metric_keys)

        rows.append(row)
        if progress_callback:
            progress_callback(interval_index, total_intervals)

    warnings.extend(_missing_bounds_warnings(missing_bounds))
    warnings.extend(_missing_cells_warnings(missing_cells))
    return IntervalMetricResult(rows=rows, warnings=warnings)


def write_interval_metrics_xlsx(result: IntervalMetricResult, output_path: str | Path) -> None:
    export_xlsx(pd.DataFrame(result.rows), output_path)


def write_interval_metrics_description(
    result: IntervalMetricResult,
    output_path: str | Path,
    settings: IntervalMetricSettings,
    *,
    extracted_path: str | Path | None = None,
    intervals_path: str | Path | None = None,
) -> Path:
    output = Path(output_path)
    description_path = output.with_suffix(".txt")
    metric_keys = _metric_key_set(settings.metric_keys)
    property_columns = [str(value) for value in settings.property_columns if str(value)]
    reservoir_values = sorted(str(value) for value in settings.reservoir_values)
    lines = [
        "ОПИСАНИЕ РАСЧЕТА ИНТЕРВАЛЬНЫХ МЕТРИК",
        "",
        f"Дата расчета (UTC): {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"Файл метрик: {output}",
        f"Таблица ячеек: {extracted_path or 'не указана'}",
        f"Таблица интервалов: {intervals_path or 'не указана'}",
        f"Количество строк результата: {len(result.rows)}",
        "",
        "НАСТРОЙКИ КАНАЛОВ",
        f"NTG: {settings.ntg_column or 'не выбран; при PORO > 0 используется маска 1, иначе 0'}",
        f"PORO: {settings.poro_column or 'не выбран'}",
        f"PERM: {settings.perm_column or 'автоматический поиск столбца с PERM'}",
        f"Литология: {settings.lithology_column or 'не выбрана'}",
        f"Density: {settings.density_column or 'не выбран; столбцы Density_* остаются пустыми'}",
        f"Shmin: {settings.shmin_column or 'не выбран; столбцы Shmin_* остаются пустыми'}",
        f"Пластовые значения литологии: {', '.join(reservoir_values) if reservoir_values else 'не заданы'}",
        f"Дополнительные свойства: {', '.join(property_columns) if property_columns else 'не выбраны'}",
        "",
        "СОПОСТАВЛЕНИЕ СТРОК",
        "Сначала ячейки сопоставляются с интервалом по Well и Port.",
        "Если совпадение не найдено, используется X/Y с округлением до 0.001 м.",
        "Названия Скважина/Well и Стадия/Муфта/Порт/Port распознаются как эквивалентные.",
        "",
        "ИНТЕРВАЛЫ",
        "Global: TVDSS_TOP_TOTAL ... TVDSS_BOT_TOTAL.",
        "Local: TVDSS_TOP_LOCAL ... TVDSS_BOT_LOCAL.",
        "Total_pm15m: от TVDSS_TOP_TOTAL - 15 м до TVDSS_BOT_TOTAL + 15 м.",
        "TopTotal_m15m: от TVDSS_TOP_TOTAL - 15 м до TVDSS_TOP_TOTAL.",
        "BotTotal_p15m: от TVDSS_BOT_TOTAL до TVDSS_BOT_TOTAL + 15 м.",
        "Для каждого интервала также рассчитываются выборки Net и NonNet.",
        "У граничных ячеек учитывается только фактическая мощность пересечения с интервалом (h).",
        "",
        "NET / NONNET",
        "Если выбраны литология и пластовые значения, Net = ячейки с указанными значениями литологии.",
        "Иначе, если выбран NTG, Net = ячейки с NTG > 0.",
        "Иначе, если выбран PORO, Net = ячейки с PORO > 0.",
        "Для этого варианта внутренний NTG принимается равным 1 при PORO > 0 и 0 во всех остальных случаях.",
        "Если нет литологии, NTG и PORO, все ячейки считаются Net; это отражается в предупреждениях.",
        "NonNet = ячейки интервала, не вошедшие в Net.",
        "",
        "ВЫБРАННЫЕ ФОРМУЛЫ",
    ]
    formulas = {
        "thickness": "Thickness = сумма h.",
        "net_thickness": "NetThickness = сумма(h * NTG); без NTG при выбранном PORO используется маска PORO > 0, без обоих каналов значение пустое.",
        "ntg_avg": "NTG_avg = сумма(NTG * h) / сумма(h).",
        "ntg_median": "NTG_median = обычная медиана валидных значений NTG.",
        "poro_avg": "PORO_avg = сумма(PORO * h) / сумма(h).",
        "poro_median": "PORO_median = обычная медиана валидных значений PORO.",
        "perm_avg_arith": "PERM_avg_arith = сумма(PERM * h) / сумма(h).",
        "perm_avg_geom": "PERM_avg_geom = exp(сумма(ln(PERM) * h) / сумма(h)); учитываются только PERM > 0.",
        "perm_median": "PERM_median = обычная медиана валидных значений PERM.",
        "kh": "KH = сумма(PERM * h * NTG); без NTG используется маска PORO > 0, а без PORO множитель равен 1.",
        "phih": "PHIH = сумма(PORO * h * NTG); без NTG используется маска PORO > 0, а без PORO множитель равен 1.",
        "avg": "<property>_avg = сумма(value * h) / сумма(h).",
        "mean_arith": "<property>_mean_arith = сумма(value * h) / сумма(h).",
        "geom": "<property>_geom = exp(сумма(ln(value) * h) / сумма(h)); учитываются только value > 0.",
        "median": "<property>_median = обычная медиана валидных значений.",
        "min": "<property>_min = минимальное валидное значение.",
        "max": "<property>_max = максимальное валидное значение.",
        "integral": "<property>_integral = сумма(value * h).",
        "min_star": "<property>_min_star = среднее нижних 10% после удаления выбросов по правилу 1.5 * IQR.",
        "max_star": "<property>_max_star = среднее верхних 10% после удаления выбросов по правилу 1.5 * IQR.",
        "std": "<property>_std = взвешенное по h стандартное отклонение генеральной совокупности.",
        "delta": "<property>_delta = max_star - min_star.",
    }
    lines.extend(f"- {formulas[key]}" for key in DEFAULT_METRIC_KEYS if key in metric_keys)
    lines.extend(
        [
            "",
            "ОБРАБОТКА ДАННЫХ",
            "Пустые и нечисловые значения свойства не участвуют в его статистике.",
            "Если для показателя нет валидных значений, соответствующая ячейка результата остается пустой.",
            "Медиана, min, max и min*/max* не взвешиваются по мощности; остальные указанные формулы используют h.",
            "",
            "ПРЕДУПРЕЖДЕНИЯ РАСЧЕТА",
        ]
    )
    lines.extend(f"- {warning}" for warning in result.warnings)
    if not result.warnings:
        lines.append("Нет.")
    lines.append("")

    description_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = description_path.with_name(f".{description_path.name}.tmp")
    temporary_path.write_text("\n".join(lines), encoding="utf-8")
    temporary_path.replace(description_path)
    return description_path


def _validate_inputs(extracted: pd.DataFrame, intervals: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    missing_extracted = [column for column in ("Well", "Port", "TVD_top", "TVD_base", "CellHeight") if column not in extracted]
    missing_intervals = [column for column in INTERVAL_COLUMNS if column not in intervals]
    if missing_extracted:
        warnings.append(f"Extracted table is missing columns: {', '.join(missing_extracted)}.")
    if missing_intervals:
        warnings.append(f"Intervals table is missing columns: {', '.join(missing_intervals)}.")
    return warnings


def _missing_bounds_warnings(missing: dict[str, list[tuple[str, str]]]) -> list[str]:
    warnings: list[str] = []
    for name, identities in missing.items():
        if len(identities) == 1:
            well, port = identities[0]
            warnings.append(f"{well}_{port}: missing interval bounds for {name}.")
        else:
            warnings.append(
                f"Missing interval bounds for {name}: {len(identities)} rows in wells: "
                f"{_well_count_summary(identities)}."
            )
    return warnings


def _missing_cells_warnings(identities: list[tuple[str, str]]) -> list[str]:
    if not identities:
        return []
    if len(identities) == 1:
        well, port = identities[0]
        return [f"No extracted cells found for {well}_{port}; tried Well/Port and X/Y."]
    return [
        f"No extracted cells found for {len(identities)} interval rows in wells: "
        f"{_well_count_summary(identities)}; tried Well/Port and X/Y."
    ]


def _well_count_summary(identities: list[tuple[str, str]]) -> str:
    counts: dict[str, int] = {}
    for well, _port in identities:
        counts[well] = counts.get(well, 0) + 1
    return ", ".join(f"{well} ({count})" for well, count in sorted(counts.items()))


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
        ("Density", settings.density_column),
        ("Shmin", settings.shmin_column),
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
    has_poro_net = bool(settings.poro_column and settings.poro_column in extracted.columns)
    if not has_lithology_net and not has_ntg_net and has_poro_net:
        warnings.append("Net metrics use PORO > 0 as a binary NTG mask because no lithology or NTG filter is available.")
    elif not has_lithology_net and not has_ntg_net:
        warnings.append("Net metrics use all interval cells because no lithology, NTG, or PORO net filter is available.")
    return warnings


def _normalize_identity_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = _restore_pandas_duplicate_column_names(df)
    rename: dict[str, str] = {}
    for column in df.columns:
        normalized = str(column).strip().lower().replace(" ", "_").replace("-", "_")
        if normalized in {"well", "well_name", "skv", "скважина"}:
            rename[column] = "Well"
        elif normalized in {"port", "stage", "port_id", "муфта", "порт", "стадия"}:
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
    ntg = _effective_ntg(cells, settings)
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
        _add_channel_metrics(row, column, values, heights, suffix, metric_keys)


def _add_channel_metrics(
    row: dict,
    name: str,
    values: pd.Series | None,
    heights: pd.Series,
    suffix: str,
    metric_keys: set[str],
) -> None:
    calculators = {
        "avg": lambda: _mean(values, heights),
        "mean_arith": lambda: _mean(values, heights),
        "geom": lambda: _geom_mean(values, heights),
        "median": lambda: _median(values),
        "min": lambda: _min(values),
        "max": lambda: _max(values),
        "integral": lambda: _sum(values * heights),
        "min_star": lambda: _robust_tail_mean(values, lower=True),
        "max_star": lambda: _robust_tail_mean(values, lower=False),
        "std": lambda: _std(values, heights),
        "delta": lambda: _delta_star(values),
    }
    for key in PROPERTY_METRIC_KEYS:
        if key in metric_keys:
            row[f"{name}_{key}_{suffix}"] = calculators[key]() if values is not None else ""


def _net_cells(cells: pd.DataFrame, settings: IntervalMetricSettings) -> pd.DataFrame:
    if settings.lithology_column and settings.lithology_column in cells.columns and settings.reservoir_values:
        values = cells[settings.lithology_column].map(_normalize_value)
        return cells[values.isin(settings.reservoir_values)]
    if settings.ntg_column and settings.ntg_column in cells.columns:
        return cells[_numeric(cells[settings.ntg_column]) > 0]
    if settings.poro_column and settings.poro_column in cells.columns:
        return cells[_numeric(cells[settings.poro_column]) > 0]
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
    return [
        str(column)
        for column in columns
        if str(column) not in BASE_EXTRACTION_COLUMNS
        and str(column) != "CellCenterTVD"
        and not _is_source_diagnostic_column(str(column))
    ]


def _is_source_diagnostic_column(column_name: str) -> bool:
    return column_name.endswith(("_Model", "_I", "_J", "_K", "_TVD_center", "_Depth_KB"))


def _additional_property_columns(settings: IntervalMetricSettings, property_columns: list[str]) -> list[str]:
    base_columns = {
        settings.ntg_column,
        settings.poro_column,
        settings.perm_column,
        settings.lithology_column,
        *(getattr(settings, attribute) for _name, attribute in FIXED_PROPERTY_CHANNELS),
    }
    return [
        column
        for column in property_columns
        if column and column not in base_columns and column not in BASE_EXTRACTION_COLUMNS
    ]


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


def _effective_ntg(cells: pd.DataFrame, settings: IntervalMetricSettings) -> pd.Series | None:
    ntg = _optional_numeric(cells, settings.ntg_column)
    if ntg is not None:
        return ntg
    has_lithology_filter = bool(
        settings.lithology_column
        and settings.lithology_column in cells.columns
        and settings.reservoir_values
    )
    if not has_lithology_filter and settings.poro_column and settings.poro_column in cells.columns:
        return (_numeric(cells[settings.poro_column]) > 0).astype(float)
    return None


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

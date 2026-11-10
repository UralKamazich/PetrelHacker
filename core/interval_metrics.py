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
# Default windows (m). The clay window is taken from the big clays above/below the reservoir
# (TopTotal_m<N>m, BotTotal_p<N>m, Total_pm<N>m and the cap-clay barriers); the barrier window
# is the nearest part of an internal barrier. Both are set on the Metrics page.
INTERVAL_BUFFER_METERS = 15.0


def window_label(window: float) -> str:
    """Window as it appears in interval names: 15 -> "15", 7.5 -> "7.5"."""
    return f"{float(window):g}"


def interval_definitions(clay_window: float = INTERVAL_BUFFER_METERS) -> tuple[tuple[str, str, str, float, float], ...]:
    """Fixed intervals: (name, top column, bottom column, top shift, bottom shift)."""
    label = window_label(clay_window)
    return (
        ("Total", "TVDSS_TOP_TOTAL", "TVDSS_BOT_TOTAL", 0.0, 0.0),
        ("Local", "TVDSS_TOP_LOCAL", "TVDSS_BOT_LOCAL", 0.0, 0.0),
        (f"Total_pm{label}m", "TVDSS_TOP_TOTAL", "TVDSS_BOT_TOTAL", -clay_window, clay_window),
        (f"TopTotal_m{label}m", "TVDSS_TOP_TOTAL", "TVDSS_TOP_TOTAL", -clay_window, 0.0),
        (f"BotTotal_p{label}m", "TVDSS_BOT_TOTAL", "TVDSS_BOT_TOTAL", 0.0, clay_window),
    )


INTERVAL_DEFINITIONS = interval_definitions()
# Interval name patterns for any clay window (used to drop old metric columns from input tables).
WINDOW_INTERVAL_PATTERNS = (r"Total_pm[0-9.]+m", r"TopTotal_m[0-9.]+m", r"BotTotal_p[0-9.]+m")
WINDOW_COLUMNS = {"clay_window_m": "CLAY_WINDOW_M", "barrier_window_m": "BARRIER_WINDOW_M"}
# Barrier next to Local on each side (top / bottom). Boundaries are corrected by hand, so
# marks closer than SEAL_ADJACENCY_METERS are treated as coinciding:
# - "seal": the Local boundary is within the tolerance of the Total boundary, i.e. Local
#   is the outermost body (monolithic reservoir on that side). The internal barrier
#   thickness is zeroed, metrics use the nearest clay window of the cap clay.
# - "interlayer": Local is away from Total and the TB/BB marks give an internal barrier
#   thicker than the tolerance; metrics use its nearest barrier window.
# - "seal_total": Local is away from Total but there is no internal barrier mark (or it is
#   within the tolerance): inconsistent marks, the clay beyond the Total boundary is used.
# - "none": Local (or Total and the mark) is missing; metrics stay empty.
BARRIER_TOP_COLUMN = "TVDSS_TOP_BARRIER_LOCAL"
BARRIER_BOT_COLUMN = "TVDSS_BOT_BARRIER_LOCAL"
BARRIER_KIND_COLUMNS = {"TopBarrier": "BARRIER_TOP_KIND", "BotBarrier": "BARRIER_BOT_KIND"}
# Internal barrier thickness after the tolerance rules (0 = no internal barrier).
BARRIER_THICKNESS_COLUMNS = {"TopBarrier": "BARRIER_TOP_LOCAL", "BotBarrier": "BARRIER_BOT_LOCAL"}
SEAL_ADJACENCY_METERS = 1.0
# Distances in this window are reported for review: the decision depends on a fraction of a metre.
SEAL_BORDERLINE_WINDOW = (SEAL_ADJACENCY_METERS - 0.5, SEAL_ADJACENCY_METERS + 2.0)
BARRIER_INTERVAL_NAMES = ("LocalBarriers", "TopBarrier", "BotBarrier")
# Old interval names: their metric columns in input tables are dropped as well.
LEGACY_INTERVAL_NAMES = ("Global",)
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
    ("PORO", "poro_column"),
    ("PERM", "perm_column"),
)
# Stress contrasts (Shmin) between the pay and the barriers around it, see _add_stress_contrasts.
# Variant: (name, statistic over pay Net cells, statistic over barrier NonNet cells).
STRESS_CONTRAST_VARIANTS = (
    ("MinMax", "min", "max"),
    ("MinStarMaxStar", "min_star", "max_star"),
    ("MinStarMedian", "min_star", "median"),
    ("MedianMedian", "median", "median"),
)



def stress_contrast_scopes(definitions=INTERVAL_DEFINITIONS) -> tuple[tuple[str, str, str, str, bool], ...]:
    """Scope: (name, pay interval, barrier above, barrier below, write Δσ × barrier thickness)."""
    top_clay = definitions[3][0]
    bottom_clay = definitions[4][0]
    return (
        ("Local", "Local", "TopBarrier", "BotBarrier", True),
        ("Total", "Total", top_clay, bottom_clay, False),
    )
# A lithology code is recommended as reservoir when at least this share of its cells has PORO > 0.
RESERVOIR_PORO_SHARE = 0.5
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
    # Window from the big clays above/below the reservoir and from internal barriers, m.
    clay_window_m: float = INTERVAL_BUFFER_METERS
    barrier_window_m: float = INTERVAL_BUFFER_METERS


@dataclass(frozen=True)
class IntervalMetricResult:
    rows: list[dict]
    warnings: list[str]
    # Problems with the Net definition (inverted reservoir codes, upscaled lithology).
    net_warnings: list[str] = field(default_factory=list)
    # Sleeves near the seal tolerance or without a barrier: {well, port, side, gap, kind, thickness, reason}.
    barrier_notices: list[dict] = field(default_factory=list)


def calculate_interval_metrics(
    extracted_df: pd.DataFrame,
    intervals_df: pd.DataFrame,
    settings: IntervalMetricSettings | None = None,
    progress_callback: MetricProgressCallback | None = None,
) -> IntervalMetricResult:
    settings = settings or IntervalMetricSettings()
    for attribute, label in (("clay_window_m", "Clay window"), ("barrier_window_m", "Barrier window")):
        value = getattr(settings, attribute)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label} must be a positive number of metres.")
    definitions = interval_definitions(settings.clay_window_m)
    contrast_scopes = stress_contrast_scopes(definitions)
    metric_suffixes = _metric_suffixes(definitions)
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

    # Only explicitly selected channels are used; nothing is picked up automatically.
    property_columns = _additional_property_columns(settings, settings.property_columns)
    metric_keys = _metric_key_set(settings.metric_keys)
    warnings.extend(_settings_warnings(extracted, settings, property_columns))
    net_warnings = _net_definition_warnings(extracted, settings)
    warnings.extend(net_warnings)
    rows: list[dict] = []
    grouped = {
        (str(well), str(port)): group
        for (well, port), group in extracted.groupby(["WellKey", "PortKey"], dropna=False)
    }
    xy_grouped = _xy_groups(extracted)

    total_intervals = len(intervals)
    missing_cells: list[tuple[str, str]] = []
    missing_bounds: dict[str, list[tuple[str, str]]] = {}
    barrier_notices: list[dict] = []
    for interval_index, (_index, interval) in enumerate(intervals.iterrows(), start=1):
        well = _normalize_value(interval["Well"])
        port = _normalize_value(interval["Port"])
        row: dict = _interval_base_row(interval)
        row["Well"] = well
        row["Port"] = port
        # Barrier kind and corrected thickness depend only on the boundary marks, so they are
        # written for every row: metric files of different models then agree in these columns.
        for attribute, column in WINDOW_COLUMNS.items():
            row[column] = float(getattr(settings, attribute))
        barrier_bounds, barrier_sides = _barrier_interval_bounds(interval, settings.clay_window_m, settings.barrier_window_m)
        for side in barrier_sides:
            row[BARRIER_KIND_COLUMNS[side.name]] = side.kind
            row[BARRIER_THICKNESS_COLUMNS[side.name]] = "" if side.internal is None else side.internal
        cells = grouped.get((well, port))
        if cells is None:
            cells = _cells_by_xy(interval, xy_grouped)
        if cells is None:
            missing_cells.append((well, port))
            rows.append(row)
            continue

        interval_sets: dict[str, pd.DataFrame] = {}
        for name, top_col, bot_col, top_delta, bot_delta in definitions:
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

        unavailable_suffixes: set[str] = set()
        for side in barrier_sides:
            if side.reason:
                barrier_notices.append(side.notice(well, port))
        for name, bounds in barrier_bounds.items():
            if bounds is None:
                interval_sets[name] = cells.iloc[0:0]
                interval_sets[f"{name}_Net"] = cells.iloc[0:0]
                interval_sets[f"{name}_NonNet"] = cells.iloc[0:0]
                unavailable_suffixes.update({name, f"{name}_Net", f"{name}_NonNet"})
                continue
            interval_cells = _cells_in_interval(cells, *bounds)
            net_cells = _net_cells(interval_cells, settings)
            interval_sets[name] = interval_cells
            interval_sets[f"{name}_Net"] = net_cells
            interval_sets[f"{name}_NonNet"] = _non_net_cells(interval_cells, net_cells)

        _add_stress_contrasts(row, interval_sets, settings.shmin_column, contrast_scopes)

        base_keys = set(row)
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
        _blank_unavailable_metrics(row, base_keys, unavailable_suffixes)

        rows.append(row)
        if progress_callback:
            progress_callback(interval_index, total_intervals)

    warnings.extend(_missing_bounds_warnings(missing_bounds))
    warnings.extend(_missing_cells_warnings(missing_cells))
    missing_barrier_columns = [column for column in (BARRIER_TOP_COLUMN, BARRIER_BOT_COLUMN) if column not in intervals]
    if missing_barrier_columns:
        warnings.append(
            f"Intervals table has no barrier columns ({', '.join(missing_barrier_columns)}); "
            "only cap-rock barriers next to the Total boundaries are used on that side. "
            "Place TB/BB points on the Sections page and save boundaries."
        )
    warnings.extend(_barrier_warnings(barrier_notices, settings.clay_window_m))
    return IntervalMetricResult(rows=rows, warnings=warnings, barrier_notices=barrier_notices, net_warnings=net_warnings)


@dataclass(frozen=True)
class BarrierSide:
    """Barrier on one side of Local after the tolerance rules (see the constants above)."""

    name: str  # TopBarrier / BotBarrier
    side: str  # top / bottom
    kind: str  # seal / interlayer / seal_total / none
    internal: float | None  # internal barrier thickness, 0 = no internal barrier, None = unknown
    span: tuple[float, float] | None  # depth range used for the barrier metrics
    gap: float | None  # Local boundary -> Total boundary, outwards
    mark_thickness: float | None  # Local boundary -> TB/BB mark, outwards
    reason: str | None  # notice for review: none / no_mark / zeroed / borderline / zero

    def notice(self, well: str, port: str) -> dict:
        return {
            "well": well,
            "port": port,
            "side": self.side,
            "kind": self.kind,
            "reason": self.reason,
            "gap": _round_or_none(self.gap),
            "pointThickness": _round_or_none(self.mark_thickness),
            "thickness": _round_or_none(self.span[1] - self.span[0]) if self.span else None,
        }


def _round_or_none(value: float | None) -> float | None:
    return round(value, 2) if value is not None and math.isfinite(value) else None


def _barrier_interval_bounds(
    interval: pd.Series,
    clay_window: float = INTERVAL_BUFFER_METERS,
    barrier_window: float = INTERVAL_BUFFER_METERS,
) -> tuple[dict[str, tuple[float, float] | None], list[BarrierSide]]:
    """Depth ranges of the barrier intervals for one sleeve (None = absent) and both barrier sides."""
    top_local = _to_float(interval.get("TVDSS_TOP_LOCAL"))
    bot_local = _to_float(interval.get("TVDSS_BOT_LOCAL"))
    windows = {"clay_window": clay_window, "barrier_window": barrier_window}
    top = _barrier_side(
        "TopBarrier", top_local, _to_float(interval.get(BARRIER_TOP_COLUMN)), _to_float(interval.get("TVDSS_TOP_TOTAL")), upward=True, **windows
    )
    bot = _barrier_side(
        "BotBarrier", bot_local, _to_float(interval.get(BARRIER_BOT_COLUMN)), _to_float(interval.get("TVDSS_BOT_TOTAL")), upward=False, **windows
    )
    local_range = None
    if top_local is not None and bot_local is not None and (top.span or bot.span):
        local_range = (
            min(top.span[0], top_local) if top.span else top_local,
            max(bot.span[1], bot_local) if bot.span else bot_local,
        )
    bounds = {"LocalBarriers": local_range, "TopBarrier": top.span, "BotBarrier": bot.span}
    return bounds, [top, bot]


def _barrier_side(
    name: str,
    local: float | None,
    mark: float | None,
    total: float | None,
    *,
    upward: bool,
    clay_window: float = INTERVAL_BUFFER_METERS,
    barrier_window: float = INTERVAL_BUFFER_METERS,
) -> BarrierSide:
    side = "top" if upward else "bottom"
    outward = -1.0 if upward else 1.0  # depth direction away from Local
    tolerance = SEAL_ADJACENCY_METERS
    low, high = SEAL_BORDERLINE_WINDOW

    def span_from(boundary: float, thickness: float) -> tuple[float, float]:
        far = boundary + outward * thickness
        return (min(boundary, far), max(boundary, far))

    if local is None:
        return BarrierSide(name, side, "none", None, None, None, None, "none")
    gap = None if total is None else (local - total if upward else total - local)
    mark_thickness = None if mark is None else (local - mark if upward else mark - local)
    if mark_thickness is not None and not math.isfinite(mark_thickness):
        mark_thickness = None
    has_mark = mark_thickness is not None and mark_thickness > tolerance

    if gap is not None and gap <= tolerance:
        # Local reaches the Total boundary: monolithic on this side, the cap clay is the barrier.
        if has_mark:
            reason = "zeroed"
        elif gap > low:
            reason = "borderline"
        else:
            reason = "zero"
        return BarrierSide(name, side, "seal", 0.0, span_from(local, clay_window), gap, mark_thickness, reason)
    if has_mark:
        near_tolerance = mark_thickness <= high or (gap is not None and gap <= high)
        return BarrierSide(
            name,
            side,
            "interlayer",
            mark_thickness,
            span_from(local, min(mark_thickness, barrier_window)),
            gap,
            mark_thickness,
            "borderline" if near_tolerance else None,
        )
    if total is not None:
        # Local is away from Total, but no internal barrier was marked: take the clay beyond Total.
        boundary = total
        return BarrierSide(name, side, "seal_total", 0.0, span_from(boundary, clay_window), gap, mark_thickness, "no_mark")
    return BarrierSide(name, side, "none", None, None, gap, mark_thickness, "none")


def _barrier_warnings(notices: list[dict], clay_window: float = INTERVAL_BUFFER_METERS) -> list[str]:
    by_reason: dict[str, list[dict]] = {}
    for notice in notices:
        by_reason.setdefault(notice["reason"], []).append(notice)
    tolerance = SEAL_ADJACENCY_METERS
    low, high = SEAL_BORDERLINE_WINDOW
    texts = {
        "none": "barrier side(s) have no Local/Total bounds; barrier metrics are empty",
        "no_mark": (
            f"barrier side(s) have Local more than {tolerance:g} m from Total but no internal barrier mark "
            f"(> {tolerance:g} m); the clay beyond the Total boundary ({clay_window:g} m) was used"
        ),
        "zeroed": (
            f"barrier side(s) have TB/BB marks thicker than {tolerance:g} m, but Local is within {tolerance:g} m "
            f"of Total; the internal barrier thickness was set to 0 and the cap clay ({clay_window:g} m) used"
        ),
        "borderline": f"barrier side(s) are near the {tolerance:g} m tolerance (distance {low:g}-{high:g} m)",
    }
    warnings = []
    for reason in ("none", "no_mark", "zeroed", "borderline"):
        items = by_reason.get(reason, [])
        if items:
            listed = ", ".join(_format_barrier_notice(notice) for notice in items[:20])
            more = f" and {len(items) - 20} more (see .txt)" if len(items) > 20 else ""
            warnings.append(f"{len(items)} {texts[reason]}. Check them: {listed}{more}.")
    zero = by_reason.get("zero", [])
    if zero:
        warnings.append(
            f"{len(zero)} barrier side(s): Local is at the Total boundary (monolithic), internal barrier = 0, "
            f"the cap clay ({clay_window:g} m) was used. List: see .txt."
        )
    return warnings


def _format_barrier_notice(notice: dict) -> str:
    gap = "n/a" if notice["gap"] is None else f"{notice['gap']:g} m"
    mark = "no mark" if notice.get("pointThickness") is None else f"mark {notice['pointThickness']:g} m"
    used = "no barrier" if notice["thickness"] is None else f"{notice['kind']} {notice['thickness']:g} m"
    return f"{notice['well']}/{notice['port']} {notice['side']} (to Total {gap}, {mark}, {used})"


def _add_stress_contrasts(
    row: dict,
    interval_sets: dict[str, pd.DataFrame],
    shmin_column: str | None,
    scopes: tuple[tuple[str, str, str, str, bool], ...] | None = None,
) -> None:
    """Shmin contrasts between the pay (Net cells) and the barriers (NonNet cells) above and below.

    SC_<scope>_Top|Bot_<variant> = stat(barrier NonNet) - stat(pay Net); > 0 means the barrier holds.
    SC_<scope>_Asym_<variant> = Bot - Top; > 0 means the fracture tends to grow upwards.
    SCxH_Local_Top|Bot_<variant> = contrast x thickness of the barrier window (barrier strength).
    Columns are always written (empty when Shmin or the cells are missing) to keep the file layout stable.
    """
    statistics = {
        "min": _min,
        "max": _max,
        "median": _median,
        "min_star": lambda values: _robust_tail_mean(values, lower=True),
        "max_star": lambda values: _robust_tail_mean(values, lower=False),
    }

    def stat(interval: str, name: str) -> float | None:
        cells = interval_sets.get(interval)
        values = _optional_numeric(cells, shmin_column) if cells is not None else None
        if values is None:
            return None
        result = statistics[name](values)
        return None if result == "" else float(result)

    for scope, pay, top, bottom, with_strength in scopes or stress_contrast_scopes():
        thickness = {
            "Top": _sum(_metric_heights(interval_sets[top])) if top in interval_sets else 0.0,
            "Bot": _sum(_metric_heights(interval_sets[bottom])) if bottom in interval_sets else 0.0,
        }
        for variant, pay_stat, barrier_stat in STRESS_CONTRAST_VARIANTS:
            pay_value = stat(f"{pay}_Net", pay_stat)
            contrasts = {}
            for side, barrier in (("Top", top), ("Bot", bottom)):
                barrier_value = stat(f"{barrier}_NonNet", barrier_stat)
                contrast = None if pay_value is None or barrier_value is None else barrier_value - pay_value
                contrasts[side] = contrast
                row[f"SC_{scope}_{side}_{variant}"] = "" if contrast is None else contrast
            asymmetry = None if contrasts["Top"] is None or contrasts["Bot"] is None else contrasts["Bot"] - contrasts["Top"]
            row[f"SC_{scope}_Asym_{variant}"] = "" if asymmetry is None else asymmetry
            if with_strength:
                for side in ("Top", "Bot"):
                    contrast = contrasts[side]
                    row[f"SCxH_{scope}_{side}_{variant}"] = "" if contrast is None else contrast * thickness[side]


def _blank_unavailable_metrics(row: dict, base_keys: set[str], unavailable_suffixes: set[str]) -> None:
    if not unavailable_suffixes:
        return
    endings = tuple(f"_{suffix}" for suffix in unavailable_suffixes)
    for key in row:
        if key not in base_keys and key.endswith(endings):
            row[key] = ""


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
    clay_label = window_label(settings.clay_window_m)
    barrier_label = window_label(settings.barrier_window_m)
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
        f"PERM: {settings.perm_column or 'не выбран'}",
        f"Литология: {settings.lithology_column or 'не выбрана'}",
        f"Density: {settings.density_column or 'не выбран; столбцы Density_* остаются пустыми'}",
        f"Shmin: {settings.shmin_column or 'не выбран; столбцы Shmin_* остаются пустыми'}",
        "PORO и PERM, как Density и Shmin, получают полный набор метрик свойств (avg, median, min, max, std, ...)",
        "по всем интервалам: PORO_<метрика>_<интервал>, PERM_<метрика>_<интервал>.",
        f"Пластовые значения литологии: {', '.join(reservoir_values) if reservoir_values else 'не заданы'}",
        f"Дополнительные свойства: {', '.join(property_columns) if property_columns else 'не выбраны'}",
        "",
        "СОПОСТАВЛЕНИЕ СТРОК",
        "Сначала ячейки сопоставляются с интервалом по Well и Port.",
        "Если совпадение не найдено, используется X/Y с округлением до 0.001 м.",
        "Названия Скважина/Well и Стадия/Муфта/Порт/Port распознаются как эквивалентные.",
        "",
        "ИНТЕРВАЛЫ",
        "Total: TVDSS_TOP_TOTAL ... TVDSS_BOT_TOTAL (весь пласт; раньше назывался Global).",
        "Local: TVDSS_TOP_LOCAL ... TVDSS_BOT_LOCAL (может совпадать с Total, если пласт монолитный).",
        f"Total_pm{clay_label}m: от TVDSS_TOP_TOTAL - {clay_label} м до TVDSS_BOT_TOTAL + {clay_label} м.",
        f"TopTotal_m{clay_label}m: от TVDSS_TOP_TOTAL - {clay_label} м до TVDSS_TOP_TOTAL.",
        f"BotTotal_p{clay_label}m: от TVDSS_BOT_TOTAL до TVDSS_BOT_TOTAL + {clay_label} м.",
        f"Окно глин (над/под пластом) = {clay_label} м, окно внутренних барьеров = {barrier_label} м (настройки на странице Metrics;",
        "пишутся в колонки CLAY_WINDOW_M / BARRIER_WINDOW_M).",
        f"Барьеры сверху и снизу от Local. Метки корректируются вручную, поэтому расстояния до {SEAL_ADJACENCY_METERS:g} м",
        "считаются совпадением. Тип пишется в BARRIER_TOP_KIND / BARRIER_BOT_KIND, мощность внутреннего барьера",
        "(после допуска; 0 = внутреннего барьера нет) — в BARRIER_TOP_LOCAL / BARRIER_BOT_LOCAL:",
        f"  seal — граница Local не дальше {SEAL_ADJACENCY_METERS:g} м от границы Total (или за ней): пласт с этой стороны монолитный,",
        f"    мощность внутреннего барьера обнуляется (даже если метки TB/BB дают больше), метрики — по ближайшим {clay_label} м глины-покрышки;",
        f"  interlayer — Local дальше {SEAL_ADJACENCY_METERS:g} м от Total, и метки дают внутренний барьер толще {SEAL_ADJACENCY_METERS:g} м:",
        "    мощность верхнего = TVDSS_TOP_LOCAL - TVDSS_TOP_BARRIER_LOCAL, нижнего = TVDSS_BOT_BARRIER_LOCAL - TVDSS_BOT_LOCAL;",
        f"    метрики — по ближайшим {barrier_label} м барьера (весь барьер, если он тоньше {barrier_label} м);",
        f"  seal_total — Local дальше {SEAL_ADJACENCY_METERS:g} м от Total, но внутреннего барьера по меткам нет: метки не согласованы,",
        f"    мощность барьера 0, метрики — по {clay_label} м глины за границей Total; такие муфты выводятся для проверки;",
        "  none — нет границ Local (или Total и метки); метрики барьера пустые.",
        "TopBarrier / BotBarrier: окно глин (seal, seal_total) или окно барьера (interlayer) сверху / снизу.",
        "LocalBarriers: Local вместе с верхним и нижним барьером.",
        "Метрики считаются для всех интервалов, даже если интервалы совпадают (например, Local = Total).",
        "",
        "КОНТРАСТЫ НАПРЯЖЕНИЙ (по каналу Shmin)",
        "SC_<набор>_Top|Bot_<вариант> = статистика Shmin в барьере (NonNet) - статистика Shmin в пласте (Net); > 0 — барьер держит.",
        "Наборы: Local — пласт Local, барьеры TopBarrier / BotBarrier (при Local = Total это глины-покрышки);",
        f"        Total — пласт Total, глины TopTotal_m{clay_label}m / BotTotal_p{clay_label}m (если рвется весь Total).",
        "Варианты (пласт / барьер): MinMax — min / max; MinStarMaxStar — min* / max*; MinStarMedian — min* / медиана;",
        "        MedianMedian — медиана / медиана. min*/max* — среднее нижних/верхних 10% после удаления выбросов (1.5 IQR).",
        "SC_<набор>_Asym_<вариант> = контраст снизу - контраст сверху; > 0 — трещина склонна расти вверх.",
        "SCxH_Local_Top|Bot_<вариант> = контраст x мощность окна барьера — прочность барьера.",
        "Если в пласте нет ячеек Net или в барьере нет ячеек NonNet, контраст пустой.",
        "Для каждого интервала также рассчитываются выборки Net и NonNet.",
        "У граничных ячеек учитывается только фактическая мощность пересечения с интервалом (h).",
        "",
        "NET / NONNET",
        "Если выбраны литология и пластовые значения, Net = ячейки с указанными значениями литологии",
        "(числовые значения литологии округляются до ближайшего целого кода: осреднённое свойство дает 0.9999 и т.п.).",
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
            "МУФТЫ У ПОГРАНИЧНЫХ УСЛОВИЙ БАРЬЕРОВ",
            "none — нет границ, метрики барьера пустые; no_mark — Local далеко от Total, но внутреннего барьера по меткам нет",
            "(взята глина за Total); zeroed — метки дают барьер, но Local у границы Total (мощность обнулена, взята покрышка);",
            f"borderline — расстояние до Total или мощность по меткам {SEAL_BORDERLINE_WINDOW[0]:g}-{SEAL_BORDERLINE_WINDOW[1]:g} м",
            f"(у допуска {SEAL_ADJACENCY_METERS:g} м); zero — Local у границы Total, внутреннего барьера нет, взята покрышка {clay_label} м.",
            *(
                [f"- {notice['reason']}: {_format_barrier_notice(notice)}" for notice in result.barrier_notices]
                or ["Нет."]
            ),
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
    if column in WINDOW_COLUMNS.values():
        return True
    if re.match(r"^SC(?:xH)?_(?:Local|Total)_(?:Top|Bot|Asym)_[A-Za-z]+$", column):
        return True
    if re.match(r"^(Thickness|NetThickness|NTG|PORO|PERM|KH|PHIH)_(Global|Local)(?:_Net)?$", column):
        return True
    if re.match(r"^(NTG|PORO|PERM)_(avg|median|avg_arith|avg_geom)_(Global|Local)(?:_Net)?$", column):
        return True
    if re.match(r"^(CellCount|CollectorCellCount)_(Global|Local)(?:_Net)?$", column):
        return True
    fixed_names = ("Total", "Local") + BARRIER_INTERVAL_NAMES + LEGACY_INTERVAL_NAMES
    interval_names = "|".join([re.escape(name) for name in fixed_names] + list(WINDOW_INTERVAL_PATTERNS))
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
    perm = _optional_numeric(cells, settings.perm_column)

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
        codes = _lithology_codes(cells[settings.lithology_column])
        return cells[codes.isin(_reservoir_codes(settings.reservoir_values))]
    if settings.ntg_column and settings.ntg_column in cells.columns:
        return cells[_numeric(cells[settings.ntg_column]) > 0]
    if settings.poro_column and settings.poro_column in cells.columns:
        return cells[_numeric(cells[settings.poro_column]) > 0]
    return cells


def _lithology_codes(values: pd.Series) -> pd.Series:
    """Lithology codes as text. Numeric values are rounded to the nearest integer code:
    upscaled discrete properties come out of the model as 0.9999 / 0.0001 etc."""
    codes = values.map(_normalize_value)
    numeric = _numeric(values)
    mask = numeric.notna()
    if mask.any():
        codes.loc[mask] = numeric[mask].round().astype("int64").astype(str)
    return codes


def _reservoir_codes(reservoir_values: set[str]) -> set[str]:
    codes = set()
    for value in reservoir_values:
        number = _to_float(value)
        codes.add(str(int(round(number))) if number is not None and math.isfinite(number) else _normalize_value(value))
    return codes


def analyze_lithology_codes(
    cells: pd.DataFrame,
    lithology_column: str,
    poro_column: str | None = None,
    ntg_column: str | None = None,
) -> dict:
    """Per-code statistics of a lithology channel and the recommended reservoir codes.

    A code is a reservoir when PORO > 0 in at least RESERVOIR_PORO_SHARE of its cells
    (NTG > 0 is used when no PORO channel is given). Cells inside the Total intervals
    are used when the table has interval bounds, otherwise all cells.
    """
    if lithology_column not in cells.columns:
        raise ValueError(f"Lithology column is missing: {lithology_column}.")
    scope = "all"
    if {"TVD_top", "TVD_base", "TVDSS_TOP_TOTAL", "TVDSS_BOT_TOTAL"} <= set(cells.columns):
        center = (_numeric(cells["TVD_top"]) + _numeric(cells["TVD_base"])) / 2.0
        inside = (center >= _numeric(cells["TVDSS_TOP_TOTAL"])) & (center <= _numeric(cells["TVDSS_BOT_TOTAL"]))
        if inside.any():
            cells = cells[inside]
            scope = "total"
    raw = _numeric(cells[lithology_column])
    numeric = raw.dropna()
    fractional = float(((numeric - numeric.round()).abs() > 1e-9).mean()) if len(numeric) else 0.0
    codes = _lithology_codes(cells[lithology_column])
    valid = cells[lithology_column].notna() & (codes != "")
    basis_column, basis = None, None
    if poro_column and poro_column in cells.columns:
        basis_column, basis = poro_column, "PORO"
    elif ntg_column and ntg_column in cells.columns:
        basis_column, basis = ntg_column, "NTG"
    poro = _optional_numeric(cells, poro_column)
    ntg = _optional_numeric(cells, ntg_column)
    heights = _numeric(cells["CellHeight"]) if "CellHeight" in cells.columns else pd.Series(1.0, index=cells.index)
    rows = []
    for code in sorted(codes[valid].unique(), key=_code_sort_key):
        mask = valid & (codes == code)
        positive = None
        if basis_column:
            positive = float((_numeric(cells.loc[mask, basis_column]) > 0).mean())
        rows.append(
            {
                "code": code,
                "cells": int(mask.sum()),
                "thickness": round(float(heights[mask].sum()), 2),
                "share": round(float(mask.sum()) / max(int(valid.sum()), 1), 4),
                "positiveShare": round(positive, 4) if positive is not None else None,
                "poroMean": _rounded_mean(poro[mask]) if poro is not None else None,
                "ntgMean": _rounded_mean(ntg[mask]) if ntg is not None else None,
                "reservoir": bool(positive is not None and positive >= RESERVOIR_PORO_SHARE),
            }
        )
    return {
        "lithologyColumn": lithology_column,
        "basis": basis,
        "scope": scope,
        "cellCount": int(valid.sum()),
        "fractionalShare": round(fractional, 4),
        "codes": rows,
        "recommended": [row["code"] for row in rows if row["reservoir"]],
    }


def _code_sort_key(code: str) -> tuple[int, float, str]:
    number = _to_float(code)
    return (0, number, code) if number is not None else (1, 0.0, code)


def _rounded_mean(values: pd.Series) -> float | None:
    valid = values.dropna()
    return round(float(valid.mean()), 4) if len(valid) else None


def _net_definition_warnings(extracted: pd.DataFrame, settings: IntervalMetricSettings) -> list[str]:
    """Sanity checks of the lithology-based Net definition on the whole extracted table."""
    column = settings.lithology_column
    if not (column and column in extracted.columns and settings.reservoir_values):
        return []
    warnings: list[str] = []
    numeric = _numeric(extracted[column]).dropna()
    fractional = numeric[(numeric - numeric.round()).abs() > 1e-9]
    if len(numeric) and len(fractional) / len(numeric) > 0.01:
        warnings.append(
            f"Lithology column {column} has fractional values in {len(fractional) / len(numeric):.0%} of cells "
            "(upscaled property); they are rounded to the nearest code."
        )
    codes = _lithology_codes(extracted[column])
    net = codes.isin(_reservoir_codes(settings.reservoir_values))
    values = ", ".join(sorted(settings.reservoir_values))
    if not net.any():
        warnings.append(f"No cells have lithology {column} in reservoir values ({values}); Net metrics are empty.")
        return warnings
    for label, channel in (("PORO", settings.poro_column), ("NTG", settings.ntg_column)):
        if not channel or channel not in extracted.columns or net.all():
            continue
        positive = _numeric(extracted[channel]) > 0
        net_share = float(positive[net].mean())
        other_share = float(positive[~net].mean())
        if net_share < 0.5 and other_share > net_share + 0.3:
            warnings.append(
                f"Net cells ({column} in {values}) have {label} > 0 only in {net_share:.0%} of cells versus "
                f"{other_share:.0%} in other cells: the reservoir values look inverted, check the lithology codes."
            )
            break
    return warnings


def _non_net_cells(cells: pd.DataFrame, net_cells: pd.DataFrame) -> pd.DataFrame:
    if cells.empty:
        return cells
    if net_cells.empty:
        return cells
    return cells.loc[~cells.index.isin(net_cells.index)]


def _metric_suffixes(definitions=INTERVAL_DEFINITIONS) -> tuple[str, ...]:
    values: list[str] = []
    for name in tuple(definition[0] for definition in definitions) + BARRIER_INTERVAL_NAMES:
        values.extend([name, f"{name}_Net", f"{name}_NonNet"])
    return tuple(values)


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

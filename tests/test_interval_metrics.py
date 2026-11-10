from __future__ import annotations

import math

import pandas as pd

from core.interval_metrics import (
    IntervalMetricResult,
    IntervalMetricSettings,
    calculate_interval_metrics,
    write_interval_metrics_description,
)


def test_calculate_interval_metrics_for_global_local_and_net() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A", "A", "A"],
            "Port": [1, 1, 1],
            "TVD_top": [100.0, 110.0, 120.0],
            "TVD_base": [110.0, 120.0, 130.0],
            "CellHeight": [10.0, 10.0, 10.0],
            "NTG": [1.0, 0.5, 0.0],
            "PORO": [0.10, 0.20, 0.30],
            "PermX": [10.0, 100.0, 1000.0],
            "Lith": [1, 2, 3],
            "SW": [0.2, 0.4, 0.6],
        }
    )
    intervals = pd.DataFrame(
        {
            "Pad": ["P1"],
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [130.0],
            "TVDSS_TOP_LOCAL": [110.0],
            "TVDSS_BOT_LOCAL": [120.0],
            "TVDSS_TOP_BARRIER_LOCAL": [110.0],
            "TVDSS_BOT_BARRIER_LOCAL": [120.0],
        }
    )
    settings = IntervalMetricSettings(
        ntg_column="NTG",
        poro_column="PORO",
        perm_column="PermX",
        lithology_column="Lith",
        reservoir_values={"1", "2"},
        property_columns=["SW"],
    )

    result = calculate_interval_metrics(extracted, intervals, settings)

    assert [warning for warning in result.warnings if "barrier" not in warning] == []
    row = result.rows[0]
    assert row["Pad"] == "P1"
    assert row["Thickness_Total"] == 30.0
    assert row["NetThickness_Total"] == 15.0
    assert row["NTG_avg_Total"] == 0.5
    assert row["NTG_median_Total"] == 0.5
    assert math.isclose(row["PORO_avg_Total"], 0.2)
    assert row["PORO_median_Total"] == 0.2
    assert row["PERM_avg_arith_Total"] == 370.0
    assert math.isclose(row["PERM_avg_geom_Total"], 100.0)
    assert row["PERM_median_Total"] == 100.0
    assert row["KH_Total"] == 600.0
    assert row["PHIH_Total"] == 2.0
    assert math.isclose(row["SW_avg_Total"], 0.4)
    assert math.isclose(row["SW_mean_arith_Total"], 0.4)
    assert row["SW_median_Total"] == 0.4
    assert row["SW_min_Total"] == 0.2
    assert row["SW_max_Total"] == 0.6
    assert row["SW_integral_Total"] == 12.0
    assert row["SW_min_star_Total"] == 0.2
    assert row["SW_max_star_Total"] == 0.6
    assert math.isclose(row["SW_std_Total"], 0.16329931618554522)
    assert math.isclose(row["SW_delta_Total"], 0.4)

    assert row["Thickness_Local"] == 10.0
    assert row["NetThickness_Local"] == 5.0
    assert row["PERM_avg_arith_Local"] == 100.0
    assert row["KH_Local"] == 500.0
    assert row["Thickness_Total_pm15m"] == 30.0
    assert row["Thickness_TopTotal_m15m"] == 0.0
    assert row["Thickness_BotTotal_p15m"] == 0.0

    assert row["Thickness_Total_Net"] == 20.0
    assert row["Thickness_Total_NonNet"] == 10.0
    assert row["KH_Total_Net"] == 600.0
    assert "NetThickness_Total_Net" not in row
    assert "NetThickness_Local_Net" not in row
    assert "CellCount_Total" not in row
    assert "CollectorCellCount_Total_Net" not in row
    assert list(row).index("PHIH_Local_Net") < list(row).index("SW_avg_Total")


def test_calculate_interval_metrics_warns_for_missing_cells() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["B"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
        }
    )

    result = calculate_interval_metrics(extracted, intervals)

    assert result.rows == [
        {
            "Well": "B",
            "Port": "1",
            "TVDSS_TOP_TOTAL": 100.0,
            "TVDSS_BOT_TOTAL": 110.0,
            "TVDSS_TOP_LOCAL": 100.0,
            "TVDSS_BOT_LOCAL": 110.0,
            # Windows and barrier columns depend only on the settings and boundary marks.
            "CLAY_WINDOW_M": 15.0,
            "BARRIER_WINDOW_M": 15.0,
            "BARRIER_TOP_KIND": "seal",
            "BARRIER_TOP_LOCAL": 0.0,
            "BARRIER_BOT_KIND": "seal",
            "BARRIER_BOT_LOCAL": 0.0,
        }
    ]
    assert "No extracted cells found for B_1; tried Well/Port and X/Y." in result.warnings


def test_calculate_interval_metrics_matches_port_float_and_coordinates() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A", "A"],
            "Port": [1, 2],
            "X": [10.1234, 20.0],
            "Y": [30.1234, 40.0],
            "TVD_top": [100.0, 100.0],
            "TVD_base": [110.0, 110.0],
            "CellHeight": [10.0, 10.0],
            "NTG": [1.0, 1.0],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A", "Missing"],
            "Port": [1.0, 99],
            "X": [10.1234, 20.0],
            "Y": [30.1234, 40.0],
            "TVDSS_TOP_TOTAL": [100.0, 100.0],
            "TVDSS_BOT_TOTAL": [110.0, 110.0],
            "TVDSS_TOP_LOCAL": [100.0, 100.0],
            "TVDSS_BOT_LOCAL": [110.0, 110.0],
        }
    )

    result = calculate_interval_metrics(extracted, intervals, IntervalMetricSettings(ntg_column="NTG"))

    assert result.rows[0]["Thickness_Total"] == 10.0
    assert result.rows[1]["Thickness_Total"] == 10.0


def test_calculate_interval_metrics_recognizes_russian_well_and_stage_columns() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["3А011"],
            "Port": [3],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "KP1": [0.15],
        }
    )
    intervals = pd.DataFrame(
        {
            "Скважина": ["3А011"],
            "Стадия": [3],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [102.0],
            "TVDSS_BOT_LOCAL": [108.0],
        }
    )

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(ntg_column=None, poro_column=None, property_columns=["KP1"]),
    )

    assert result.warnings[0] == "Net metrics use all interval cells because no lithology, NTG, or PORO net filter is available."
    assert result.warnings[1].startswith("Intervals table has no barrier columns")
    assert len(result.rows) == 1
    assert result.rows[0]["Well"] == "3А011"
    assert result.rows[0]["Port"] == "3"
    assert result.rows[0]["Thickness_Total"] == 10.0
    assert result.rows[0]["KP1_avg_Total"] == 0.15


def test_calculate_interval_metrics_aggregates_repeated_missing_bound_warnings() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A", "A"],
            "Port": [1, 2],
            "TVD_top": [100.0, 100.0],
            "TVD_base": [110.0, 110.0],
            "CellHeight": [10.0, 10.0],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A", "A"],
            "Port": [1, 2],
            "TVDSS_TOP_TOTAL": [None, None],
            "TVDSS_BOT_TOTAL": [None, None],
            "TVDSS_TOP_LOCAL": [100.0, 100.0],
            "TVDSS_BOT_LOCAL": [110.0, 110.0],
        }
    )

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(ntg_column=None, poro_column=None),
    )

    global_warnings = [warning for warning in result.warnings if "bounds for Total:" in warning]
    assert global_warnings == ["Missing interval bounds for Total: 2 rows in wells: A (2)."]


def test_calculate_interval_metrics_merges_pandas_duplicate_columns() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "NTG": [1.0],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "ID_СКВ_Пласт": [""],
            "ID_СКВ_Пласт.1": ["A_layer"],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
        }
    )

    result = calculate_interval_metrics(extracted, intervals, IntervalMetricSettings(ntg_column="NTG"))

    row = result.rows[0]
    assert row["ID_СКВ_Пласт"] == "A_layer"
    assert "ID_СКВ_Пласт.1" not in row


def test_calculate_interval_metrics_drops_existing_metric_columns_from_frac_list() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "NTG": [1.0],
            "PORO": [0.2],
            "PERM": [100.0],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "Thickness_Global": [999.0],
            "CellCount_Global": [999],
            "PORO_avg_Global": [999.0],
            "SomeLog_avg_Global": [999.0],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
        }
    )

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column="PORO", perm_column="PERM"),
    )

    row = result.rows[0]
    assert row["Thickness_Total"] == 10.0
    assert row["PORO_avg_Total"] == 0.2
    assert "Thickness_Global" not in row
    assert "PORO_avg_Global" not in row
    assert "CellCount_Global" not in row
    assert "SomeLog_avg_Global" not in row


def test_calculate_interval_metrics_uses_gross_cells_for_net_without_net_filter() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A", "A"],
            "Port": [1, 1],
            "TVD_top": [100.0, 110.0],
            "TVD_base": [110.0, 120.0],
            "CellHeight": [10.0, 10.0],
            "DENSITY": [2.4, 2.6],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [120.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [120.0],
        }
    )

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(ntg_column=None, property_columns=["DENSITY"]),
    )

    row = result.rows[0]
    assert row["Thickness_Total"] == 20.0
    assert row["Thickness_Total_Net"] == 20.0
    assert row["DENSITY_avg_Total"] == 2.5
    assert row["DENSITY_avg_Total_Net"] == 2.5
    assert any("Net metrics use all interval cells" in warning for warning in result.warnings)


def test_calculate_interval_metrics_uses_positive_poro_as_binary_ntg() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A", "A", "A"],
            "Port": [1, 1, 1],
            "TVD_top": [100.0, 110.0, 120.0],
            "TVD_base": [110.0, 120.0, 130.0],
            "CellHeight": [10.0, 10.0, 10.0],
            "PORO": [0.1, None, 0.0],
            "PERM": [100.0, 100.0, 100.0],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [130.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [130.0],
        }
    )

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(ntg_column=None, poro_column="PORO", perm_column="PERM"),
    )

    row = result.rows[0]
    assert row["Thickness_Total"] == 30.0
    assert row["Thickness_Total_Net"] == 10.0
    assert row["Thickness_Total_NonNet"] == 20.0
    assert row["NetThickness_Total"] == 10.0
    assert math.isclose(row["NTG_avg_Total"], 1.0 / 3.0)
    assert row["NTG_median_Total"] == 0.0
    assert row["KH_Total"] == 1000.0
    assert row["PHIH_Total"] == 1.0
    assert any("PORO > 0 as a binary NTG mask" in warning for warning in result.warnings)


def test_calculate_interval_metrics_uses_partial_depth_overlap_for_coarse_cells() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVD_top": [90.0],
            "TVD_base": [130.0],
            "CellHeight": [40.0],
            "STRESS": [10.0],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [120.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [120.0],
        }
    )

    result = calculate_interval_metrics(extracted, intervals, IntervalMetricSettings(property_columns=["STRESS"]))

    row = result.rows[0]
    assert row["Thickness_Total"] == 20.0
    assert row["STRESS_integral_Total"] == 200.0


def test_calculate_interval_metrics_honors_selected_metric_keys() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "NTG": [1.0],
            "SW": [0.25],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
        }
    )

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(
            ntg_column="NTG",
            property_columns=["SW"],
            metric_keys=["thickness", "mean_arith"],
        ),
    )

    row = result.rows[0]
    assert row["Thickness_Total"] == 10.0
    assert row["SW_mean_arith_Total"] == 0.25
    assert "SW_median_Total" not in row
    assert "NTG_avg_Total" not in row


def test_write_interval_metrics_description_next_to_xlsx(tmp_path) -> None:
    output_path = tmp_path / "field_metrics.xlsx"
    result = IntervalMetricResult(rows=[{"Well": "A", "Port": "1"}], warnings=["Example warning."])
    settings = IntervalMetricSettings(
        ntg_column="NTG",
        poro_column=None,
        perm_column="PERM",
        property_columns=["KP1"],
        metric_keys=["thickness", "geom", "min_star"],
    )

    description_path = write_interval_metrics_description(
        result,
        output_path,
        settings,
        extracted_path=tmp_path / "extracted.xlsx",
        intervals_path=tmp_path / "boundaries.xlsx",
    )

    assert description_path == tmp_path / "field_metrics.txt"
    text = description_path.read_text(encoding="utf-8")
    assert "ОПИСАНИЕ РАСЧЕТА ИНТЕРВАЛЬНЫХ МЕТРИК" in text
    assert "Total: TVDSS_TOP_TOTAL ... TVDSS_BOT_TOTAL" in text
    assert "Thickness = сумма h." in text
    assert "<property>_geom" in text
    assert "<property>_min_star" in text
    assert "KP1" in text
    assert "внутренний NTG принимается равным 1 при PORO > 0" in text
    assert "Example warning." in text


def test_calculate_interval_metrics_writes_fixed_channels_under_stable_names() -> None:
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
        }
    )

    def model_columns(density: str, shmin: str, extra: str) -> list[str]:
        extracted = pd.DataFrame(
            {
                "Well": ["A"],
                "Port": [1],
                "TVD_top": [100.0],
                "TVD_base": [110.0],
                "CellHeight": [10.0],
                "NTG": [1.0],
                density: [2.4],
                shmin: [35.0],
                extra: [0.3],
            }
        )
        result = calculate_interval_metrics(
            extracted,
            intervals,
            IntervalMetricSettings(
                ntg_column="NTG",
                density_column=density,
                shmin_column=shmin,
                property_columns=[density, shmin, extra],
                metric_keys=["thickness", "avg"],
            ),
        )
        row = result.rows[0]
        assert row["Density_avg_Total"] == 2.4
        assert row["Shmin_avg_Total"] == 35.0
        assert f"{density}_avg_Total" not in row
        return [column for column in row if not column.startswith(extra)]

    first = model_columns("M1_RHOB", "M1_SHMIN_MPa", "M1_SW")
    second = model_columns("M2_Density", "M2_Shmin", "M2_SW")
    assert first == second


def test_calculate_interval_metrics_keeps_empty_fixed_channels_and_puts_additional_last() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "SW": [0.3],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
        }
    )

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(ntg_column=None, property_columns=["SW"], metric_keys=["avg"]),
    )

    columns = list(result.rows[0])
    assert result.rows[0]["Density_avg_Total"] == ""
    assert result.rows[0]["Shmin_avg_Total"] == ""
    assert columns.index("Shmin_avg_BotTotal_p15m_NonNet") < columns.index("SW_avg_Total")


def test_calculate_interval_metrics_ignores_interval_boundary_columns_as_properties() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "SW": [0.3],
        }
    )
    intervals = extracted[["Well", "Port", "TVDSS_TOP_TOTAL", "TVDSS_BOT_TOTAL", "TVDSS_TOP_LOCAL", "TVDSS_BOT_LOCAL"]]

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(property_columns=["SW", "TVDSS_BOT_LOCAL"], metric_keys=["avg"]),
    )
    row = result.rows[0]
    assert row["SW_avg_Total"] == 0.3
    assert not any(column.startswith("TVDSS_BOT_LOCAL_") for column in row)


def test_calculate_interval_metrics_uses_only_selected_channels() -> None:
    extracted = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "EFFECTIVE_STRESS": [30.0],
            "TOTAL_STRESS": [55.0],
            "PermX": [100.0],
        }
    )
    intervals = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [110.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [110.0],
        }
    )

    result = calculate_interval_metrics(
        extracted,
        intervals,
        IntervalMetricSettings(ntg_column=None, poro_column=None, property_columns=[]),
    )

    row = result.rows[0]
    assert not any("STRESS" in column for column in row)
    assert row["PERM_avg_arith_Total"] == ""


def _barrier_cells() -> pd.DataFrame:
    tops = [float(value) for value in range(80, 150, 5)]
    return pd.DataFrame(
        {
            "Well": ["A"] * len(tops),
            "Port": [1] * len(tops),
            "TVD_top": tops,
            "TVD_base": [top + 5.0 for top in tops],
            "CellHeight": [5.0] * len(tops),
            "NTG": [1.0 if 105.0 <= top < 120.0 else 0.0 for top in tops],
            "Shm": [top for top in tops],
        }
    )


def _barrier_intervals(top_barrier: object, bot_barrier: object) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [130.0],
            "TVDSS_TOP_LOCAL": [105.0],
            "TVDSS_BOT_LOCAL": [120.0],
            "TVDSS_TOP_BARRIER_LOCAL": [top_barrier],
            "TVDSS_BOT_BARRIER_LOCAL": [bot_barrier],
        }
    )


def _barrier_row(top_barrier: object, bot_barrier: object) -> dict:
    result = calculate_interval_metrics(
        _barrier_cells(),
        _barrier_intervals(top_barrier, bot_barrier),
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )
    assert [warning for warning in result.warnings if "barrier" not in warning] == []
    return result.rows[0]


def test_barrier_intervals_use_barrier_points() -> None:
    row = _barrier_row(95.0, 130.0)

    assert row["Thickness_TopBarrier"] == 10.0
    assert row["Thickness_BotBarrier"] == 10.0
    assert row["Thickness_LocalBarriers"] == 35.0
    assert row["BARRIER_TOP_KIND"] == "interlayer"
    assert row["BARRIER_BOT_KIND"] == "interlayer"
    assert row["BARRIER_TOP_LOCAL"] == 10.0
    assert row["Thickness_TopBarrier_NonNet"] == 10.0
    assert row["Thickness_TopBarrier_Net"] == 0.0
    assert row["NetThickness_LocalBarriers"] == 15.0
    assert row["Shmin_min_TopBarrier"] == 95.0
    assert row["Shmin_max_BotBarrier"] == 125.0
    assert row["Shmin_avg_Local"] == 110.0


def test_barrier_intervals_are_capped_at_15_m() -> None:
    row = _barrier_row(80.0, 145.0)

    assert row["Thickness_TopBarrier"] == 15.0
    assert row["Thickness_BotBarrier"] == 15.0
    assert row["Thickness_LocalBarriers"] == 45.0
    assert row["Shmin_min_TopBarrier"] == 90.0


def test_barrier_marks_within_1_m_mean_no_internal_barrier() -> None:
    # Local (105-120) is 5 m below Total top and 10 m above Total base.
    row = _barrier_row(105.0, 130.0)
    # Top: TB = TL, no internal barrier -> inconsistent marks, the clay above Total (85-100) is used.
    assert row["BARRIER_TOP_KIND"] == "seal_total"
    assert row["BARRIER_TOP_LOCAL"] == 0.0
    assert row["Thickness_TopBarrier"] == 15.0
    assert row["Shmin_min_TopBarrier"] == 85.0
    # Bottom: a real 10 m internal barrier.
    assert row["BARRIER_BOT_KIND"] == "interlayer"
    assert row["BARRIER_BOT_LOCAL"] == 10.0
    assert row["Thickness_BotBarrier"] == 10.0
    assert row["Thickness_LocalBarriers"] == 45.0

    # Marks 0.5 m / 0.8 m from Local are hand-correction noise, not barriers.
    row = _barrier_row(104.5, 120.8)
    assert row["BARRIER_TOP_KIND"] == "seal_total"
    assert row["BARRIER_BOT_KIND"] == "seal_total"
    assert row["BARRIER_TOP_LOCAL"] == 0.0
    assert row["BARRIER_BOT_LOCAL"] == 0.0
    assert row["Thickness_BotBarrier"] == 15.0
    assert row["Shmin_max_BotBarrier"] == 140.0
    assert row["Thickness_Local"] == 15.0


def test_missing_local_gives_empty_barrier_metrics() -> None:
    intervals = _barrier_intervals(100.0, 125.0)
    intervals["TVDSS_TOP_LOCAL"] = None

    result = calculate_interval_metrics(
        _barrier_cells(),
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )

    row = result.rows[0]
    assert row["BARRIER_TOP_KIND"] == "none"
    assert row["Thickness_TopBarrier"] == ""
    assert row["Thickness_LocalBarriers"] == ""
    assert row["BARRIER_BOT_KIND"] == "interlayer"
    assert row["Thickness_BotBarrier"] == 5.0
def test_barrier_metric_columns_are_dropped_from_input_frac_list() -> None:
    intervals = _barrier_intervals(95.0, 130.0)
    intervals["Thickness_TopBarrier"] = 999.0
    intervals["Shmin_avg_LocalBarriers_Net"] = 999.0

    result = calculate_interval_metrics(
        _barrier_cells(),
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )

    row = result.rows[0]
    assert row["Thickness_TopBarrier"] == 10.0
    assert row["Shmin_avg_LocalBarriers_Net"] != 999.0


def test_cap_rock_next_to_total_is_used_as_15_m_barrier() -> None:
    # Local is the outermost body: its top equals Total top (seal above), its base is
    # 0.5 m above Total base (within the 1 m tolerance, seal below). No TB/BB barriers.
    intervals = _barrier_intervals(105.0, 120.0)
    intervals["TVDSS_TOP_TOTAL"] = 105.0
    intervals["TVDSS_BOT_TOTAL"] = 120.5

    result = calculate_interval_metrics(
        _barrier_cells(),
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )

    assert not [warning for warning in result.warnings if "no top barrier" in warning or "no bottom barrier" in warning]
    row = result.rows[0]
    assert row["BARRIER_TOP_KIND"] == "seal"
    assert row["BARRIER_BOT_KIND"] == "seal"
    assert row["Thickness_TopBarrier"] == 15.0
    assert row["Thickness_BotBarrier"] == 15.0
    assert row["Thickness_LocalBarriers"] == 45.0
    assert row["Shmin_min_TopBarrier"] == 90.0
    assert row["Shmin_max_BotBarrier"] == 130.0


def test_local_at_total_zeroes_internal_barrier_thickness() -> None:
    # Top: Local is 0.5 m below Total top -> monolithic, the 5 m TB mark is zeroed, cap clay used.
    # Bottom: BB equals BL and Total is 10 m below -> clay beyond Total.
    intervals = _barrier_intervals(100.0, 120.0)
    intervals["TVDSS_TOP_TOTAL"] = 104.5

    result = calculate_interval_metrics(
        _barrier_cells(),
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )

    row = result.rows[0]
    assert row["BARRIER_TOP_KIND"] == "seal"
    assert row["BARRIER_TOP_LOCAL"] == 0.0
    assert row["Thickness_TopBarrier"] == 15.0
    assert row["Shmin_min_TopBarrier"] == 90.0
    assert row["BARRIER_BOT_KIND"] == "seal_total"
    assert row["Thickness_BotBarrier"] == 15.0
    assert row["Shmin_min_BotBarrier"] == 130.0
    reasons = {(notice["side"], notice["reason"]) for notice in result.barrier_notices}
    assert reasons == {("top", "zeroed"), ("bottom", "no_mark")}
    assert any("internal barrier thickness was set to 0" in warning for warning in result.warnings)
    assert any("no internal barrier mark" in warning for warning in result.warnings)
def test_barrier_notices_report_zero_borderline_and_missing_barriers(tmp_path) -> None:
    intervals = pd.concat(
        [
            _barrier_intervals(105.0, 120.0).assign(Port=1, TVDSS_TOP_TOTAL=105.0, TVDSS_BOT_TOTAL=130.0),
            _barrier_intervals(100.0, 125.0).assign(Port=2, TVDSS_TOP_TOTAL=103.5, TVDSS_BOT_TOTAL=130.0),
        ],
        ignore_index=True,
    )
    cells = pd.concat([_barrier_cells(), _barrier_cells().assign(Port=2)], ignore_index=True)

    result = calculate_interval_metrics(
        cells,
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )

    notices = {(notice["port"], notice["side"]): notice for notice in result.barrier_notices}
    assert notices[("1", "top")]["reason"] == "zero"
    assert notices[("1", "top")]["kind"] == "seal"
    assert notices[("1", "bottom")]["reason"] == "no_mark"
    assert notices[("1", "bottom")]["kind"] == "seal_total"
    assert notices[("2", "top")]["reason"] == "borderline"
    assert notices[("2", "top")]["gap"] == 1.5
    assert notices[("2", "top")]["thickness"] == 5.0
    assert ("2", "bottom") not in notices

    description = write_interval_metrics_description(result, tmp_path / "m.xlsx", IntervalMetricSettings())
    text = description.read_text(encoding="utf-8")
    assert "МУФТЫ У ПОГРАНИЧНЫХ УСЛОВИЙ БАРЬЕРОВ" in text
    assert "borderline: A/2 top" in text


def _upscaled_lithology_cells() -> pd.DataFrame:
    # Upscaled 0/1 lithology: 1 = reservoir with porosity, 0 = shale without porosity.
    return pd.DataFrame(
        {
            "Well": ["A"] * 4,
            "Port": [1] * 4,
            "TVD_top": [100.0, 110.0, 120.0, 130.0],
            "TVD_base": [110.0, 120.0, 130.0, 140.0],
            "CellHeight": [10.0] * 4,
            "Lith": [1.0, 0.9999, 0.0001, 0.0],
            "PORO": [0.20, 0.10, None, None],
        }
    )


def _global_intervals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [140.0],
            "TVDSS_TOP_LOCAL": [100.0],
            "TVDSS_BOT_LOCAL": [140.0],
        }
    )


def test_upscaled_lithology_values_are_rounded_to_codes() -> None:
    result = calculate_interval_metrics(
        _upscaled_lithology_cells(),
        _global_intervals(),
        IntervalMetricSettings(ntg_column=None, poro_column="PORO", lithology_column="Lith", reservoir_values={"1"}),
    )

    row = result.rows[0]
    assert row["Thickness_Total_Net"] == 20.0
    assert math.isclose(row["PORO_avg_Total_Net"], 0.15)
    assert row["Thickness_Total_NonNet"] == 20.0
    assert any("fractional values in 50% of cells" in warning for warning in result.net_warnings)
    assert not any("inverted" in warning for warning in result.net_warnings)


def test_inverted_reservoir_values_are_reported() -> None:
    result = calculate_interval_metrics(
        _upscaled_lithology_cells(),
        _global_intervals(),
        IntervalMetricSettings(ntg_column=None, poro_column="PORO", lithology_column="Lith", reservoir_values={"0"}),
    )

    assert result.rows[0]["PORO_avg_Total_Net"] == ""
    assert any("look inverted" in warning for warning in result.net_warnings)
    assert any("look inverted" in warning for warning in result.warnings)


def test_poro_and_perm_get_full_property_metric_set() -> None:
    cells = _upscaled_lithology_cells().assign(PermX=[100.0, 10.0, 1.0, 1.0])
    result = calculate_interval_metrics(
        cells,
        _global_intervals(),
        IntervalMetricSettings(ntg_column=None, poro_column="PORO", perm_column="PermX", lithology_column="Lith", reservoir_values={"1"}),
    )

    row = result.rows[0]
    assert math.isclose(row["PORO_avg_Total"], 0.15)
    assert row["PORO_min_Total"] == 0.10
    assert row["PORO_max_Total_Net"] == 0.20
    assert row["PORO_std_TopBarrier"] == ""
    assert math.isclose(row["PERM_geom_Total_Net"], math.sqrt(1000.0))
    assert row["PERM_max_Local"] == 100.0
    assert "PERM_delta_LocalBarriers_NonNet" in row
    assert "PORO_integral_BotTotal_p15m" in row


def test_analyze_lithology_codes_recommends_codes_with_porosity() -> None:
    from core.interval_metrics import analyze_lithology_codes

    cells = _upscaled_lithology_cells()
    cells = pd.concat([cells, cells.assign(Lith=[2.0, 2.0, 2.0, 2.0], PORO=[None, 0.0, None, None])], ignore_index=True)

    advice = analyze_lithology_codes(cells, "Lith", "PORO")

    assert advice["basis"] == "PORO"
    assert advice["scope"] == "all"
    assert advice["recommended"] == ["1"]
    codes = {row["code"]: row for row in advice["codes"]}
    assert codes["1"]["cells"] == 2
    assert codes["1"]["positiveShare"] == 1.0
    assert codes["0"]["reservoir"] is False
    assert codes["2"]["positiveShare"] == 0.0
    assert advice["fractionalShare"] == 0.25

    by_ntg = analyze_lithology_codes(cells.assign(NTG=[1, 1, 0, 0, 0, 0, 0, 0]), "Lith", None, "NTG")
    assert by_ntg["basis"] == "NTG"
    assert by_ntg["recommended"] == ["1"]


def test_stress_contrasts_between_pay_and_barriers() -> None:
    # Shm equals the cell top depth. Local 105-120 (Net cells 105, 110, 115),
    # TopBarrier 95-105 (NonNet 95, 100), BotBarrier 120-130 (NonNet 120, 125),
    # Total 100-130, TopTotal_m15m 85-100 (85, 90, 95), BotTotal_p15m 130-145 (130, 135, 140).
    row = _barrier_row(95.0, 130.0)

    assert row["SC_Local_Top_MinMax"] == 100.0 - 105.0
    assert row["SC_Local_Bot_MinMax"] == 125.0 - 105.0
    assert row["SC_Local_Asym_MinMax"] == 20.0 - (-5.0)
    assert row["SC_Local_Top_MedianMedian"] == 97.5 - 110.0
    assert row["SC_Local_Bot_MedianMedian"] == 122.5 - 110.0
    assert row["SC_Local_Top_MinStarMaxStar"] == 100.0 - 105.0
    assert row["SC_Local_Bot_MinStarMedian"] == 122.5 - 105.0
    assert row["SCxH_Local_Top_MinMax"] == -5.0 * 10.0
    assert row["SCxH_Local_Bot_MinMax"] == 20.0 * 10.0
    assert row["SC_Total_Top_MinMax"] == 95.0 - 105.0
    assert row["SC_Total_Bot_MinMax"] == 140.0 - 105.0
    assert row["SC_Total_Asym_MinMax"] == 35.0 - (-10.0)
    assert "SCxH_Total_Top_MinMax" not in row


def test_stress_contrasts_are_empty_without_shmin_or_barrier_shale() -> None:
    result = calculate_interval_metrics(
        _barrier_cells(),
        _barrier_intervals(95.0, 130.0),
        IntervalMetricSettings(ntg_column="NTG", poro_column=None),
    )
    row = result.rows[0]
    assert row["SC_Local_Top_MinMax"] == ""
    assert row["SCxH_Local_Bot_MedianMedian"] == ""
    assert row["SC_Total_Asym_MinStarMedian"] == ""

    # Every cell is reservoir: no NonNet cells in the barriers, no contrast.
    cells = _barrier_cells().assign(NTG=1.0)
    result = calculate_interval_metrics(
        cells,
        _barrier_intervals(95.0, 130.0),
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )
    assert result.rows[0]["SC_Local_Top_MedianMedian"] == ""


def test_stress_contrast_columns_are_dropped_from_input_frac_list() -> None:
    intervals = _barrier_intervals(95.0, 130.0)
    intervals["SC_Local_Top_MinMax"] = 999.0
    intervals["SCxH_Local_Bot_MedianMedian"] = 999.0

    result = calculate_interval_metrics(
        _barrier_cells(),
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )

    assert result.rows[0]["SC_Local_Top_MinMax"] == -5.0
    assert result.rows[0]["SCxH_Local_Bot_MedianMedian"] == 12.5 * 10.0


def test_barrier_thickness_is_written_for_rows_of_other_models() -> None:
    # The second sleeve has no cells in this model (it belongs to another model), but its
    # corrected barrier thickness must still be written so that model files agree when merged.
    intervals = pd.concat(
        [_barrier_intervals(95.0, 120.5), _barrier_intervals(104.6, 130.0).assign(Well="B")],
        ignore_index=True,
    )
    intervals["BARRIER_TOP_LOCAL"] = [10.0, 0.4]
    intervals["BARRIER_BOT_LOCAL"] = [0.5, 10.0]

    result = calculate_interval_metrics(
        _barrier_cells(),
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )

    own, other = result.rows
    assert own["BARRIER_TOP_LOCAL"] == 10.0
    assert own["BARRIER_BOT_LOCAL"] == 0.0
    assert other["BARRIER_TOP_LOCAL"] == 0.0
    assert other["BARRIER_TOP_KIND"] == "seal_total"
    assert other["BARRIER_BOT_LOCAL"] == 10.0
    assert "Thickness_Local" not in other
    assert all(notice["well"] == "A" for notice in result.barrier_notices)


def _window_row(top_barrier: object, bot_barrier: object, *, clay: float, barrier: float, total_top: float = 100.0) -> tuple[dict, list[str]]:
    intervals = _barrier_intervals(top_barrier, bot_barrier)
    intervals["TVDSS_TOP_TOTAL"] = total_top
    result = calculate_interval_metrics(
        _barrier_cells(),
        intervals,
        IntervalMetricSettings(
            ntg_column="NTG", poro_column=None, shmin_column="Shm", clay_window_m=clay, barrier_window_m=barrier
        ),
    )
    return result.rows[0], result.warnings


def test_clay_window_changes_clay_intervals_and_cap_rock_barriers() -> None:
    # Top: Local at Total (seal) -> clay window; bottom: 10 m interlayer -> barrier window (15 m keeps all 10 m).
    row, _warnings = _window_row(105.0, 130.0, clay=5.0, barrier=15.0, total_top=105.0)

    assert row["CLAY_WINDOW_M"] == 5.0
    assert row["BARRIER_WINDOW_M"] == 15.0
    assert row["Thickness_TopTotal_m5m"] == 5.0
    assert row["Thickness_BotTotal_p5m"] == 5.0
    assert row["Thickness_Total_pm5m"] == 35.0
    assert "Thickness_TopTotal_m15m" not in row
    assert row["BARRIER_TOP_KIND"] == "seal"
    assert row["Thickness_TopBarrier"] == 5.0
    assert row["Shmin_min_TopBarrier"] == 100.0
    assert row["BARRIER_BOT_KIND"] == "interlayer"
    assert row["Thickness_BotBarrier"] == 10.0
    assert row["SC_Total_Top_MinMax"] == 100.0 - 105.0


def test_barrier_window_limits_internal_barriers_only() -> None:
    # Top: 10 m interlayer limited to 3 m; bottom: Local away from Total, no mark -> clay window beyond Total.
    row, _warnings = _window_row(95.0, 120.0, clay=5.0, barrier=3.0)

    assert row["BARRIER_TOP_KIND"] == "interlayer"
    assert row["BARRIER_TOP_LOCAL"] == 10.0
    assert row["Thickness_TopBarrier"] == 3.0
    assert row["SCxH_Local_Top_MinMax"] == row["SC_Local_Top_MinMax"] * 3.0
    assert row["BARRIER_BOT_KIND"] == "seal_total"
    assert row["Thickness_BotBarrier"] == 5.0
    assert row["Shmin_min_BotBarrier"] == 130.0


def test_windows_must_be_positive() -> None:
    import pytest

    with pytest.raises(ValueError, match="Clay window"):
        calculate_interval_metrics(_barrier_cells(), _barrier_intervals(95.0, 130.0), IntervalMetricSettings(clay_window_m=0.0))
    with pytest.raises(ValueError, match="Barrier window"):
        calculate_interval_metrics(_barrier_cells(), _barrier_intervals(95.0, 130.0), IntervalMetricSettings(barrier_window_m=-1.0))


def test_metric_columns_of_other_windows_are_dropped_from_input() -> None:
    intervals = _barrier_intervals(95.0, 130.0)
    intervals["Thickness_TopTotal_m15m"] = 999.0
    intervals["CLAY_WINDOW_M"] = 15.0

    result = calculate_interval_metrics(
        _barrier_cells(), intervals, IntervalMetricSettings(ntg_column="NTG", poro_column=None, clay_window_m=5.0)
    )

    row = result.rows[0]
    assert "Thickness_TopTotal_m15m" not in row
    assert row["Thickness_TopTotal_m5m"] == 5.0
    assert row["CLAY_WINDOW_M"] == 5.0

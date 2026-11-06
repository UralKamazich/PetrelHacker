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
    assert row["Thickness_Global"] == 30.0
    assert row["NetThickness_Global"] == 15.0
    assert row["NTG_avg_Global"] == 0.5
    assert row["NTG_median_Global"] == 0.5
    assert math.isclose(row["PORO_avg_Global"], 0.2)
    assert row["PORO_median_Global"] == 0.2
    assert row["PERM_avg_arith_Global"] == 370.0
    assert math.isclose(row["PERM_avg_geom_Global"], 100.0)
    assert row["PERM_median_Global"] == 100.0
    assert row["KH_Global"] == 600.0
    assert row["PHIH_Global"] == 2.0
    assert math.isclose(row["SW_avg_Global"], 0.4)
    assert math.isclose(row["SW_mean_arith_Global"], 0.4)
    assert row["SW_median_Global"] == 0.4
    assert row["SW_min_Global"] == 0.2
    assert row["SW_max_Global"] == 0.6
    assert row["SW_integral_Global"] == 12.0
    assert row["SW_min_star_Global"] == 0.2
    assert row["SW_max_star_Global"] == 0.6
    assert math.isclose(row["SW_std_Global"], 0.16329931618554522)
    assert math.isclose(row["SW_delta_Global"], 0.4)

    assert row["Thickness_Local"] == 10.0
    assert row["NetThickness_Local"] == 5.0
    assert row["PERM_avg_arith_Local"] == 100.0
    assert row["KH_Local"] == 500.0
    assert row["Thickness_Total_pm15m"] == 30.0
    assert row["Thickness_TopTotal_m15m"] == 0.0
    assert row["Thickness_BotTotal_p15m"] == 0.0

    assert row["Thickness_Global_Net"] == 20.0
    assert row["Thickness_Global_NonNet"] == 10.0
    assert row["KH_Global_Net"] == 600.0
    assert "NetThickness_Global_Net" not in row
    assert "NetThickness_Local_Net" not in row
    assert "CellCount_Global" not in row
    assert "CollectorCellCount_Global_Net" not in row
    assert list(row).index("PHIH_Local_Net") < list(row).index("SW_avg_Global")


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

    assert result.rows[0]["Thickness_Global"] == 10.0
    assert result.rows[1]["Thickness_Global"] == 10.0


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
    assert result.rows[0]["Thickness_Global"] == 10.0
    assert result.rows[0]["KP1_avg_Global"] == 0.15


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

    global_warnings = [warning for warning in result.warnings if "bounds for Global" in warning]
    assert global_warnings == ["Missing interval bounds for Global: 2 rows in wells: A (2)."]


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
    assert row["Thickness_Global"] == 10.0
    assert row["PORO_avg_Global"] == 0.2
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
    assert row["Thickness_Global"] == 20.0
    assert row["Thickness_Global_Net"] == 20.0
    assert row["DENSITY_avg_Global"] == 2.5
    assert row["DENSITY_avg_Global_Net"] == 2.5
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
    assert row["Thickness_Global"] == 30.0
    assert row["Thickness_Global_Net"] == 10.0
    assert row["Thickness_Global_NonNet"] == 20.0
    assert row["NetThickness_Global"] == 10.0
    assert math.isclose(row["NTG_avg_Global"], 1.0 / 3.0)
    assert row["NTG_median_Global"] == 0.0
    assert row["KH_Global"] == 1000.0
    assert row["PHIH_Global"] == 1.0
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
    assert row["Thickness_Global"] == 20.0
    assert row["STRESS_integral_Global"] == 200.0


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
    assert row["Thickness_Global"] == 10.0
    assert row["SW_mean_arith_Global"] == 0.25
    assert "SW_median_Global" not in row
    assert "NTG_avg_Global" not in row


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
    assert "Global: TVDSS_TOP_TOTAL ... TVDSS_BOT_TOTAL." in text
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
        assert row["Density_avg_Global"] == 2.4
        assert row["Shmin_avg_Global"] == 35.0
        assert f"{density}_avg_Global" not in row
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
    assert result.rows[0]["Density_avg_Global"] == ""
    assert result.rows[0]["Shmin_avg_Global"] == ""
    assert columns.index("Shmin_avg_BotTotal_p15m_NonNet") < columns.index("SW_avg_Global")


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
    assert row["SW_avg_Global"] == 0.3
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
    assert row["PERM_avg_arith_Global"] == ""


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


def test_missing_or_zero_barrier_gives_empty_metrics() -> None:
    row = _barrier_row(105.0, 130.0)

    assert row["BARRIER_TOP_KIND"] == "none"
    assert row["Thickness_TopBarrier"] == ""
    assert row["Thickness_TopBarrier_Net"] == ""
    assert row["Shmin_avg_TopBarrier_NonNet"] == ""
    assert row["Thickness_BotBarrier"] == 10.0
    assert row["Thickness_LocalBarriers"] == 25.0

    row = _barrier_row(None, 118.0)
    assert row["Thickness_TopBarrier"] == ""
    assert row["Thickness_BotBarrier"] == ""
    assert row["Thickness_LocalBarriers"] == ""
    assert row["Shmin_avg_LocalBarriers"] == ""
    assert row["Thickness_Local"] == 15.0


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


def test_seal_wins_over_barrier_points_and_far_local_without_barrier_is_empty() -> None:
    # Top: Local is 0.5 m below Total top -> cap rock, even though TB marks a 5 m barrier.
    # Bottom: Local is 10 m above Total base and BB equals BL -> no barrier.
    intervals = _barrier_intervals(100.0, 120.0)
    intervals["TVDSS_TOP_TOTAL"] = 104.5

    result = calculate_interval_metrics(
        _barrier_cells(),
        intervals,
        IntervalMetricSettings(ntg_column="NTG", poro_column=None, shmin_column="Shm"),
    )

    row = result.rows[0]
    assert row["BARRIER_TOP_KIND"] == "seal"
    assert row["Thickness_TopBarrier"] == 15.0
    assert row["BARRIER_BOT_KIND"] == "none"
    assert row["Thickness_BotBarrier"] == ""
    assert any("1 sleeve(s) have no bottom barrier" in warning for warning in result.warnings)


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
    assert notices[("1", "bottom")]["reason"] == "none"
    assert notices[("2", "top")]["reason"] == "borderline"
    assert notices[("2", "top")]["gap"] == 1.5
    assert notices[("2", "top")]["thickness"] == 5.0
    assert ("2", "bottom") not in notices

    description = write_interval_metrics_description(result, tmp_path / "m.xlsx", IntervalMetricSettings())
    text = description.read_text(encoding="utf-8")
    assert "МУФТЫ У ПОГРАНИЧНЫХ УСЛОВИЙ БАРЬЕРОВ" in text
    assert "borderline: A/2 top" in text

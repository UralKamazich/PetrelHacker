from __future__ import annotations

import math

import pandas as pd

from core.interval_metrics import IntervalMetricSettings, calculate_interval_metrics


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

    assert result.warnings == []
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
    assert row["SW_median_Global"] == 0.4
    assert row["SW_min_Global"] == 0.2
    assert row["SW_max_Global"] == 0.6
    assert row["SW_integral_Global"] == 12.0

    assert row["Thickness_Local"] == 10.0
    assert row["NetThickness_Local"] == 5.0
    assert row["PERM_avg_arith_Local"] == 100.0
    assert row["KH_Local"] == 500.0

    assert row["Thickness_Global_Net"] == 20.0
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

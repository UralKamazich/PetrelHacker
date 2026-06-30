from __future__ import annotations

import pandas as pd

from app.main_window import _curve_depth_series


def test_curve_depth_series_prefers_property_diagnostic_depth_in_individual_mode() -> None:
    df = pd.DataFrame(
        {
            "TVD_top": [100.0, 110.0],
            "TVD_center": [105.0, 115.0],
            "M3_YME_STA": [10.0, 20.0],
            "M3_YME_STA_TVD_center": [104.5, 114.5],
        }
    )

    assert _curve_depth_series(df, "M3_YME_STA", depth_mode="individual").tolist() == [104.5, 114.5]


def test_curve_depth_series_uses_common_grid_top_in_common_mode() -> None:
    df = pd.DataFrame(
        {
            "TVD_top": [100.0, 110.0],
            "TVD_center": [105.0, 115.0],
            "M3_YME_STA": [10.0, 20.0],
            "M3_YME_STA_TVD_center": [104.5, 114.5],
        }
    )

    assert _curve_depth_series(df, "M3_YME_STA", depth_mode="common").tolist() == [100.0, 110.0]


def test_curve_depth_series_falls_back_to_common_center_in_individual_mode() -> None:
    df = pd.DataFrame(
        {
            "TVD_top": [100.0, 110.0],
            "TVD_center": [105.0, 115.0],
            "NTG": [1.0, 0.0],
        }
    )

    assert _curve_depth_series(df, "NTG", depth_mode="individual").tolist() == [105.0, 115.0]

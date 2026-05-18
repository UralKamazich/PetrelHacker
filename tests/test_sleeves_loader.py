from __future__ import annotations

import pandas as pd

from core.sleeves_loader import normalize_sleeves_columns, validate_sleeves_table


def test_normalize_sleeves_id_alias() -> None:
    df = pd.DataFrame({"Sleeves_ID": ["A"], "x": [1], "y": [2]})
    out = normalize_sleeves_columns(df)
    assert list(out.columns) == ["Sleeve_ID", "X", "Y"]


def test_validate_sleeves_table_coerces_xy() -> None:
    df = pd.DataFrame({"Sleeve_ID": ["A"], "X": ["1.5"], "Y": ["2.5"]})
    warnings = validate_sleeves_table(df)
    assert warnings == []
    assert df.loc[0, "X"] == 1.5
    assert df.loc[0, "Y"] == 2.5


def test_validate_sleeves_table_reports_missing_columns() -> None:
    df = pd.DataFrame({"Sleeve_ID": ["A"], "X": [1]})
    warnings = validate_sleeves_table(df)
    assert warnings == ["Missing required column: Y"]

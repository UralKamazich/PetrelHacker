from __future__ import annotations

import pandas as pd
import pytest

from core.table_io import read_table
from core.table_merge import MergeInput, file_labels, merge_tables, write_merged_table


def _model_table(filled_wells: set[str], value: float) -> pd.DataFrame:
    wells = ["3А011", "3А011", "5А020", "6А030", "7103"]
    return pd.DataFrame(
        {
            "Field": ["U"] * 5,
            "Well": wells,
            "Port": [1, 2, 1, 1, 1],
            "TVDSS_PORT": [3000.0, 3010.0, 3020.0, 3030.0, 3040.0],
            "Thickness_Local": [value if well[:2] in filled_wells else None for well in wells],
            "Shmin_avg_TopBarrier": [value * 2 if well[:2] in filled_wells else None for well in wells],
        }
    )


def test_merge_takes_metrics_from_the_model_that_has_them() -> None:
    inputs = [
        MergeInput("3А", _model_table({"3А"}, 3.0)),
        MergeInput("5А", _model_table({"5А"}, 5.0)),
        MergeInput("6А", _model_table({"6А"}, 6.0)),
    ]

    result = merge_tables(inputs, ["Well", "Port"])

    frame = result.frame
    assert list(frame.columns) == ["Field", "Well", "Port", "TVDSS_PORT", "Thickness_Local", "Shmin_avg_TopBarrier", "Merge_source"]
    assert frame["Thickness_Local"].tolist() == [3.0, 3.0, 5.0, 6.0, None]
    assert frame["Shmin_avg_TopBarrier"].tolist() == [6.0, 6.0, 10.0, 12.0, None]
    assert frame["Merge_source"].tolist() == ["3А", "3А", "5А", "6А", ""]
    assert frame["TVDSS_PORT"].tolist() == [3000.0, 3010.0, 3020.0, 3030.0, 3040.0]
    assert result.conflicts == 0
    assert [stats["rowsContributed"] for stats in result.file_stats] == [2, 1, 1]
    assert any("identical data in all files" in warning for warning in result.warnings)


def test_merge_matches_keys_by_normalized_text_and_keeps_extra_rows() -> None:
    first = pd.DataFrame({"Well": ["6А031", "6А032"], "Port": [1, 1], "A": [1.0, 2.0]})
    second = pd.DataFrame({"well": ["6a031 ", "6A099"], "PORT": ["1.0", "2"], "B": [10.0, 20.0]})

    result = merge_tables([MergeInput("m1", first), MergeInput("m2", second)], ["Well", "Port"])

    frame = result.frame
    assert frame["Well"].tolist() == ["6А031", "6А032", "6A099"]
    assert frame["A"].tolist() == [1.0, 2.0, None]
    assert frame["B"].tolist() == [10.0, None, 20.0]
    assert frame["Merge_source"].tolist() == ["m1+m2", "m1", "m2"]


def test_merge_reports_conflicts_and_keeps_first_file_value() -> None:
    first = pd.DataFrame({"Well": ["A", "B"], "Port": [1, 1], "X": [1.0, 2.0]})
    second = pd.DataFrame({"Well": ["A", "B"], "Port": [1, 1], "X": [1.0 + 1e-13, 3.0]})

    result = merge_tables([MergeInput("m1", first), MergeInput("m2", second)], ["Well", "Port"], add_source_column=False)

    assert result.frame["X"].tolist() == [1.0, 2.0]
    assert "Merge_source" not in result.frame.columns
    assert result.conflicts == 1
    assert "X (1)" in result.warnings[0]


def test_merge_warns_about_duplicate_keys_and_requires_key_columns() -> None:
    first = pd.DataFrame({"Well": ["A", "A"], "Port": [1, 1], "X": [1.0, 9.0]})
    second = pd.DataFrame({"Well": ["A"], "Port": [1], "Y": [5.0]})

    result = merge_tables([MergeInput("m1", first), MergeInput("m2", second)], ["Well", "Port"])
    assert result.frame["X"].tolist() == [1.0]
    assert any("duplicate key" in warning for warning in result.warnings)

    with pytest.raises(ValueError, match="key column"):
        merge_tables([MergeInput("m1", first), MergeInput("m2", second.drop(columns="Port"))], ["Well", "Port"])
    with pytest.raises(ValueError, match="at least two"):
        merge_tables([MergeInput("m1", first)], ["Well", "Port"])


def test_file_labels_keep_distinguishing_part() -> None:
    assert file_labels(["/d/Field_061126_metrics_3А.xlsx", "/d/Field_061126_metrics_5А.xlsx"]) == ["3А", "5А"]
    assert file_labels(["/d/m1_metrics.xlsx", "/d/m2_metrics.xlsx"]) == ["m1", "m2"]
    assert file_labels(["/a/x.xlsx", "/b/x.xlsx"]) == ["x#1", "x#2"]


def test_write_merged_table_round_trips_values(tmp_path) -> None:
    inputs = [MergeInput("3А", _model_table({"3А"}, 0.1234567890123456)), MergeInput("5А", _model_table({"5А"}, 5.0))]
    result = merge_tables(inputs, ["Well", "Port"])
    output = tmp_path / "merged.xlsx"

    write_merged_table(result, output)

    saved = read_table(output)
    assert saved["Thickness_Local"].iloc[0] == 0.1234567890123456
    assert pd.isna(saved["Thickness_Local"].iloc[4])
    assert saved["Merge_source"].fillna("").tolist() == ["3А", "3А", "5А", "", ""]


def test_merge_warns_about_shmin_in_different_units() -> None:
    mpa = pd.DataFrame({"Well": ["A", "B"], "Port": [1, 1], "Shmin_avg_Local": [66.0, None]})
    atm = pd.DataFrame({"Well": ["A", "B"], "Port": [1, 1], "Shmin_avg_Local": [None, 650.0]})

    result = merge_tables([MergeInput("3А", mpa), MergeInput("5А", atm)], ["Well", "Port"])

    assert any("different units" in warning and "3А: 66.0" in warning for warning in result.warnings)
    same = merge_tables([MergeInput("5А", atm), MergeInput("6А", atm.assign(Shmin_avg_Local=[630.0, None]))], ["Well", "Port"])
    assert not any("different units" in warning for warning in same.warnings)

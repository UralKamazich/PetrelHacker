from __future__ import annotations

import pandas as pd

from core.multi_model_extractor import (
    LoadedColumn,
    ExtractionModelSpec,
    ModelContext,
    MultiModelPropertyExtractor,
    _find_depth_k,
    _offset_geometry,
    _union_depth_segments,
)


class _FakeMatch:
    i = 0
    j = 0


class _FakeIndexer:
    def find_column(self, x: float, y: float):
        return _FakeMatch()


class _FakeReader:
    def get_cell_geometry_column(self, i: int, j: int) -> dict[str, list[float]]:
        return {
            "TVD_top": [100.0],
            "TVD_base": [110.0],
            "CellHeight": [10.0],
            "CellSizeI": [20.0],
            "CellSizeJ": [30.0],
            "CellAreaXY": [600.0],
        }

    def get_cell_active_column(self, i: int, j: int):
        return None


def test_find_depth_k_uses_depth_interval_not_matching_index() -> None:
    geometry = {
        "TVD_top": [90.0, 100.0, 110.0],
        "TVD_base": [100.0, 110.0, 120.0],
        "CellHeight": [10.0, 10.0, 10.0],
    }

    assert _find_depth_k(geometry, 115.0) == 2


def test_find_depth_k_applies_model_depth_offset_before_matching() -> None:
    geometry = {
        "TVD_top": [90.0, 100.0, 110.0],
        "TVD_base": [100.0, 110.0, 120.0],
        "CellHeight": [10.0, 10.0, 10.0],
    }

    shifted = _offset_geometry(geometry, 20.0)

    assert _find_depth_k(shifted, 125.0) == 1
    assert _find_depth_k(geometry, 125.0) is None


def test_union_depth_segments_keeps_broad_geomechanics_coverage() -> None:
    geology = LoadedColumn(
        i=0,
        j=0,
        geometry={
            "TVD_top": [100.0, 100.3],
            "TVD_base": [100.3, 100.6],
            "CellHeight": [0.3, 0.3],
        },
        active=None,
        property_columns={},
    )
    geomechanics = LoadedColumn(
        i=0,
        j=0,
        geometry={
            "TVD_top": [80.0, 120.0],
            "TVD_base": [120.0, 160.0],
            "CellHeight": [40.0, 40.0],
        },
        active=None,
        property_columns={},
    )

    assert _union_depth_segments([geology, geomechanics]) == [
        (80.0, 100.0),
        (100.0, 100.3),
        (100.3, 100.6),
        (100.6, 120.0),
        (120.0, 160.0),
    ]


def test_multi_model_extractor_writes_port_relative_depths(tmp_path) -> None:
    extractor = MultiModelPropertyExtractor([], skip_inactive=False)
    extractor.contexts = [
        ModelContext(
            spec=ExtractionModelSpec(path="fake"),
            reader=_FakeReader(),
            indexer=_FakeIndexer(),
            properties=[],
            output_names={},
        )
    ]
    sleeves = pd.DataFrame(
        {
            "Well": ["A"],
            "Port": [1],
            "X": [10.0],
            "Y": [20.0],
            "TVDSS_PORT": [95.0],
        }
    )
    output_path = tmp_path / "out.csv"

    stats = extractor.extract_to_csv(sleeves, output_path)
    rows = pd.read_csv(output_path)

    assert stats.extracted_rows == 1
    assert rows.loc[0, "TVDSS_PORT"] == 95.0
    assert rows.loc[0, "TVD_center"] == 105.0
    assert rows.loc[0, "Rel_TVD_top"] == 5.0
    assert rows.loc[0, "Rel_TVD_base"] == 15.0
    assert rows.loc[0, "Rel_TVD_center"] == 10.0

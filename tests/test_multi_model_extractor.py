from __future__ import annotations

from core.multi_model_extractor import LoadedColumn, _find_depth_k, _offset_geometry, _union_depth_segments


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

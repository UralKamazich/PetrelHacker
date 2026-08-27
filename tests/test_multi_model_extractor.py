from __future__ import annotations

import numpy as np
import pandas as pd

from core.multi_model_extractor import (
    LoadedColumn,
    ExtractionModelSpec,
    ModelContext,
    MultiModelPropertyExtractor,
    _datum_for_well,
    _find_depth_k,
    _offset_geometry,
    _property_values_for_interval,
    _union_depth_segments,
)
from core.resqml_reader import PropertyInfo


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

    def get_property_column_values(self, uuid: str, i: int, j: int):
        return [2.5]


class _FakePetrelPointsReader(_FakeReader):
    def get_cell_geometry_column(self, i: int, j: int):
        return {
            "points": np.asarray(
                [
                    [[0.0, 0.0, -100.0], [20.0, 0.0, -102.0], [0.0, 30.0, -100.0], [20.0, 30.0, -102.0]],
                    [[0.0, 0.0, -110.0], [20.0, 0.0, -112.0], [0.0, 30.0, -110.0], [20.0, 30.0, -112.0]],
                ],
                dtype=float,
            )
        }


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


def test_union_depth_segments_merges_float_noise_boundaries() -> None:
    first = LoadedColumn(
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
    second = LoadedColumn(
        i=0,
        j=0,
        geometry={
            "TVD_top": [100.0002, 100.3001],
            "TVD_base": [100.3001, 100.6002],
            "CellHeight": [0.3, 0.3],
        },
        active=None,
        property_columns={},
    )

    assert _union_depth_segments([first, second]) == [
        (100.0001, 100.30005),
        (100.30005, 100.6001),
    ]


def test_multi_model_extractor_writes_port_relative_depths(tmp_path) -> None:
    extractor = MultiModelPropertyExtractor([], skip_inactive=False)
    extractor.well_depth_datums = {"A": 85.0}
    extractor.contexts = [
        ModelContext(
            spec=ExtractionModelSpec(path="fake"),
            label="fake",
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
            "TVDSS_TOP_TOTAL": [92.0],
            "TVDSS_BOT_TOTAL": [118.0],
            "TVDSS_TOP_LOCAL": [98.0],
            "TVDSS_BOT_LOCAL": [112.0],
        }
    )
    output_path = tmp_path / "out.csv"

    stats = extractor.extract_to_csv(sleeves, output_path)
    rows = pd.read_csv(output_path)

    assert stats.extracted_rows == 1
    assert rows.loc[0, "TVDSS_PORT"] == 95.0
    assert rows.loc[0, "TVDSS_TOP_TOTAL"] == 92.0
    assert rows.loc[0, "TVDSS_BOT_TOTAL"] == 118.0
    assert rows.loc[0, "TVDSS_TOP_LOCAL"] == 98.0
    assert rows.loc[0, "TVDSS_BOT_LOCAL"] == 112.0
    assert rows.loc[0, "Datum_Z"] == 85.0
    assert rows.loc[0, "Depth_KB_PORT"] == 180.0
    assert rows.loc[0, "TVDSS_center"] == 105.0
    assert rows.loc[0, "TVD_center"] == 105.0
    assert rows.loc[0, "Depth_KB_center"] == 190.0
    assert rows.loc[0, "Rel_TVD_top"] == 5.0
    assert rows.loc[0, "Rel_TVD_base"] == 15.0
    assert rows.loc[0, "Rel_TVD_center"] == 10.0


def test_multi_model_extractor_normalizes_native_petrel_corner_points(tmp_path) -> None:
    extractor = MultiModelPropertyExtractor([], skip_inactive=False)
    extractor.contexts = [
        ModelContext(
            spec=ExtractionModelSpec(path="fake.pet"),
            label="petrel",
            reader=_FakePetrelPointsReader(),
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
            "Y": [15.0],
            "TVDSS_PORT": [105.0],
        }
    )
    output_path = tmp_path / "petrel.csv"

    stats = extractor.extract_to_csv(sleeves, output_path)
    rows = pd.read_csv(output_path)

    assert stats.extracted_rows == 1
    assert rows.loc[0, "TVD_top"] == 101.0
    assert rows.loc[0, "TVD_base"] == 111.0
    assert rows.loc[0, "CellHeight"] == 10.0
    assert rows.loc[0, "CellSizeI"] == 20.0
    assert rows.loc[0, "CellSizeJ"] == 30.0
    assert rows.loc[0, "CellAreaXY"] == 600.0


def test_multi_model_extractor_writes_property_source_diagnostics(tmp_path) -> None:
    extractor = MultiModelPropertyExtractor([], skip_inactive=False)
    extractor.well_depth_datums = {"A": 85.0}
    prop = PropertyInfo(index=0, title="YME_STA", uuid="prop-1")
    extractor.contexts = [
        ModelContext(
            spec=ExtractionModelSpec(path="fake"),
            label="rescue",
            reader=_FakeReader(),
            indexer=_FakeIndexer(),
            properties=[prop],
            output_names={prop.uuid: "YME_STA"},
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
    assert rows.loc[0, "YME_STA"] == 2.5
    assert rows.loc[0, "YME_STA_Model"] == "rescue"
    assert rows.loc[0, "YME_STA_I"] == 1
    assert rows.loc[0, "YME_STA_J"] == 1
    assert rows.loc[0, "YME_STA_K"] == 1
    assert rows.loc[0, "YME_STA_TVD_center"] == 105.0
    assert rows.loc[0, "YME_STA_Depth_KB"] == 190.0


def test_multi_model_extractor_can_skip_property_source_diagnostics(tmp_path) -> None:
    extractor = MultiModelPropertyExtractor([], skip_inactive=False, write_diagnostics=False)
    prop = PropertyInfo(index=0, title="YME_STA", uuid="prop-1")
    extractor.contexts = [
        ModelContext(
            spec=ExtractionModelSpec(path="fake"),
            label="rescue",
            reader=_FakeReader(),
            indexer=_FakeIndexer(),
            properties=[prop],
            output_names={prop.uuid: "YME_STA"},
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

    extractor.extract_to_csv(sleeves, output_path)
    rows = pd.read_csv(output_path)

    assert rows.loc[0, "YME_STA"] == 2.5
    assert "YME_STA_K" not in rows.columns
    assert "YME_STA_TVD_center" not in rows.columns


def test_multi_model_parallel_workers_preserve_output_order(tmp_path) -> None:
    prop = PropertyInfo(index=0, title="YME_STA", uuid="prop-1")
    sleeves = pd.DataFrame(
        {
            "Well": ["A", "B"],
            "Port": [1, 2],
            "X": [10.0, 10.0],
            "Y": [20.0, 20.0],
            "TVDSS_PORT": [95.0, 95.0],
        }
    )
    outputs = []
    for workers in (1, 2):
        extractor = MultiModelPropertyExtractor([], skip_inactive=False, parallel_workers=workers)
        extractor.contexts = [
            ModelContext(
                spec=ExtractionModelSpec(path="fake"),
                label="rescue",
                reader=_FakeReader(),
                indexer=_FakeIndexer(),
                properties=[prop],
                output_names={prop.uuid: "YME_STA"},
            )
        ]
        output_path = tmp_path / f"out-{workers}.csv"
        extractor.extract_to_csv(sleeves, output_path)
        outputs.append(pd.read_csv(output_path))

    pd.testing.assert_frame_equal(outputs[0], outputs[1])
    assert outputs[1]["Well"].tolist() == ["A", "B"]


def test_interval_sampling_does_not_fill_blank_cell_from_tiny_neighbor_overlap() -> None:
    prop = PropertyInfo(index=0, title="YME_STA", uuid="prop-1")
    context = ModelContext(
        spec=ExtractionModelSpec(path="fake"),
        label="rescue",
        reader=_FakeReader(),
        indexer=_FakeIndexer(),
        properties=[prop],
        output_names={prop.uuid: "YME_STA"},
    )
    column = LoadedColumn(
        i=0,
        j=0,
        geometry={
            "TVD_top": [100.0, 110.0],
            "TVD_base": [110.0, 120.0],
            "CellHeight": [10.0, 10.0],
        },
        active=None,
        property_columns={prop.uuid: ["", 25.0]},
    )

    values = _property_values_for_interval(
        context,
        column,
        109.0,
        110.0001,
        skip_inactive=False,
        allow_nearest=False,
    )

    assert values["YME_STA"] == ""
    assert values["YME_STA_K"] == ""


def test_datum_matching_normalizes_cyrillic_a_and_well_suffix() -> None:
    datums = {"6A031": 85.09}

    assert _datum_for_well(datums, "6А031") == 85.09
    assert _datum_for_well(datums, "6A031GS_NEW") == 85.09

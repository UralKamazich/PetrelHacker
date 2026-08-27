from __future__ import annotations

import json

import pandas as pd
import pytest

from core.section_workspace import extract_workspace, load_section, save_section, workspace_info


def _section_result(value: float = 0.15) -> dict:
    return {
        "model_path": "/models/geology.epc",
        "well_name": "3A001_GS",
        "trajectory_uuid": "trajectory-1",
        "property_title": "PORO",
        "property_uuid": "property-1",
        "station_count": 2,
        "cell_count": 4,
        "rowColumns": {
            "station_index": [0, 0, 1, 1],
            "well_name": ["3A001_GS"] * 4,
            "md": [1000.0, 1000.0, 1100.0, 1100.0],
            "distance": [0.0, 0.0, 100.0, 100.0],
            "horizontal_distance": [0.0, 0.0, 100.0, 100.0],
            "x": [10.0, 10.0, 20.0, 20.0],
            "y": [30.0, 30.0, 40.0, 40.0],
            "z": [-100.0, -100.0, -110.0, -110.0],
            "i": [5, 5, 6, 6],
            "j": [7, 7, 8, 8],
            "k": [1, 2, 1, 2],
            "tvd_top": [100.0, 110.0, 101.0, 111.0],
            "tvd_base": [110.0, 120.0, 111.0, 121.0],
            "tvd_center": [105.0, 115.0, 106.0, 116.0],
            "value": [value, value + 0.01, value + 0.02, value + 0.03],
        },
    }


def _section_payload() -> dict:
    return {
        "path": "/models/geology.epc",
        "modelLabel": "M1",
        "gridUuid": "grid-1",
        "propertyUuid": "property-1",
        "propertyTitle": "PORO",
        "propertyType": "ContinuousProperty",
        "propertyKind": "porosity",
        "propertyUom": "m3/m3",
        "trajectoryPath": "/models/geology.epc",
        "trajectoryUuid": "trajectory-1",
        "modelWellName": "3A001_GS",
        "fracWellName": "3A001",
        "sampleStep": 25,
        "depthOffset": 0,
        "skipInactive": True,
    }


def test_section_workspace_saves_parquet_and_overwrites_same_section(tmp_path) -> None:
    boundary_path = tmp_path / "field_boundaries.xlsx"

    first = save_section(boundary_path, _section_payload(), _section_result())
    second = save_section(
        boundary_path,
        _section_payload(),
        _section_result(0.25),
        scene_settings={"axis": "md", "depthMin": "100"},
        boundary_records=[{"well": "3A001", "port": 3, "TVDSS_TOP_TOTAL": 102.0}],
        column_mapping={"Well": "Скважина", "Port": "Муфта"},
    )

    assert first["workspacePath"] == second["workspacePath"]
    info = workspace_info(boundary_path)
    assert info["sectionCount"] == 1
    assert info["wellCount"] == 1
    assert info["propertyCount"] == 1
    assert info["sections"][0]["propertyTitle"] == "PORO"
    manifest = json.loads((tmp_path / "field_boundaries_sections" / "manifest.json").read_text(encoding="utf-8"))
    data_path = tmp_path / "field_boundaries_sections" / manifest["sections"][0]["dataFile"]
    assert pd.read_parquet(data_path).loc[0, "value"] == 0.25
    loaded = load_section(second["workspacePath"], second["section"]["id"])
    assert loaded["sceneSettings"]["axis"] == "md"
    assert loaded["boundaryRecords"][0]["TVDSS_TOP_TOTAL"] == 102.0
    assert loaded["columnMapping"]["Well"] == "Скважина"
    assert loaded["result"]["rowColumns"]["value"][0] == 0.25


def test_section_workspace_extracts_saved_property_at_sleeve_md(tmp_path) -> None:
    boundary_path = tmp_path / "field_boundaries.xlsx"
    saved = save_section(boundary_path, _section_payload(), _section_result())
    sleeves = pd.DataFrame(
        {
            "Well": ["3A001"],
            "Port": [3],
            "X": [20.0],
            "Y": [40.0],
            "MD": [1100.0],
            "TVDSS_PORT": [108.0],
            "TVDSS_TOP_TOTAL": [100.0],
            "TVDSS_BOT_TOTAL": [120.0],
            "TVDSS_TOP_LOCAL": [103.0],
            "TVDSS_BOT_LOCAL": [115.0],
        }
    )
    output_path = tmp_path / "extracted.csv"

    stats = extract_workspace(
        saved["workspacePath"],
        sleeves,
        output_path,
        selected_properties={"M1": ["property-1"]},
        write_diagnostics=True,
    )

    rows = pd.read_csv(output_path)
    assert stats.sleeves_inside_grid == 1
    assert stats.extracted_rows == 2
    assert rows["PORO"].tolist() == pytest.approx([0.17, 0.18])
    assert rows["PORO_Model"].tolist() == ["M1", "M1"]
    assert rows["PORO_I"].tolist() == [6, 6]
    assert rows["Rel_TVD_center"].tolist() == [-2.0, 8.0]
    assert rows["TVDSS_TOP_TOTAL"].tolist() == [100.0, 100.0]
    assert rows["TVDSS_BOT_TOTAL"].tolist() == [120.0, 120.0]
    assert rows["TVDSS_TOP_LOCAL"].tolist() == [103.0, 103.0]
    assert rows["TVDSS_BOT_LOCAL"].tolist() == [115.0, 115.0]

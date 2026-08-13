from pathlib import Path

import pandas as pd
import pytest

from core.resqml_reader import GridInfo, ResqmlNamedHorizon, WellTrajectoryInfo
from web_backend import cli
from core.resqml_reader import WellTrajectoryPoint


class _ModelReader:
    backend = "petrel-project"
    epc_path = Path("project.pet")
    h5_path = None

    def __init__(self) -> None:
        self.selected_grid_uuid = None
        self.grids = [
            GridInfo(0, "Grid A", "grid-a", 2, 3, 4, "PillarGrid2", ()),
            GridInfo(1, "Grid B", "grid-b", 5, 6, 7, "PillarGrid2", ()),
        ]

    def list_grids(self):
        return self.grids

    def select_grid(self, grid_uuid):
        self.selected_grid_uuid = grid_uuid

    def list_properties(self):
        return []

    def list_well_trajectories(self):
        return [WellTrajectoryInfo(0, "7103", "well-1", "7103", point_count=100)]

    def list_named_horizons(self):
        return [ResqmlNamedHorizon("horizon-1", "Top", "grid-b", 0)]


def test_load_models_returns_selected_internal_grid(monkeypatch):
    reader = _ModelReader()
    events = []
    monkeypatch.setattr(cli, "open_model_reader", lambda _path: reader)
    monkeypatch.setattr(cli, "_emit", lambda event, **payload: events.append((event, payload)))

    cli.load_models(
        {
            "models": [
                {
                    "label": "M1",
                    "path": "project.pet",
                    "gridUuid": "grid-b",
                }
            ]
        }
    )

    result = next(payload for event, payload in events if event == "result")
    assert reader.selected_grid_uuid == "grid-b"
    assert result["models"][0]["gridUuid"] == "grid-b"
    assert result["models"][0]["trajectories"][0]["well_name"] == "7103"
    assert result["models"][0]["namedHorizons"][0]["title"] == "Top"


def test_section_result_payload_uses_columnar_rows():
    from core.model_section import SectionCell, SectionResult

    row = SectionCell(0, "7103", 10.0, 11.0, 9.0, 1.0, 2.0, -3.0, 4, 5, 6, 100.0, 101.0, 100.5, 0.2)
    result = SectionResult("model", "7103", "trajectory", "PORO", "property", 1, 1, [row], [], [])

    payload = cli._section_result_payload(result)

    assert "rows" not in payload
    assert payload["rowColumns"]["well_name"] == ["7103"]
    assert payload["rowColumns"]["tvd_center"] == [100.5]


def test_preview_sleeves_reports_coordinate_coverage(tmp_path, monkeypatch):
    path = tmp_path / "frac-list.csv"
    pd.DataFrame(
        {
            "Well": ["A", "A", "B"],
            "Port": [1, 2, 1],
            "MD": [100.0, 120.0, None],
            "X": [10.0, None, 30.0],
            "Y": [20.0, 21.0, 40.0],
        }
    ).to_csv(path, index=False)
    events = []
    monkeypatch.setattr(cli, "_emit", lambda event, **payload: events.append((event, payload)))

    cli.preview_sleeves({"path": str(path)})

    result = next(payload for event, payload in events if event == "result")
    assert result["coordinateStats"] == {"validXY": 2, "missingXY": 1, "validMD": 2}


def test_calculate_sleeve_coordinates_fills_only_missing_values_in_source(tmp_path, monkeypatch):
    source = tmp_path / "frac-list.csv"
    pd.DataFrame(
        {
            "Скважина": ["A", "A", "B"],
            "Стадия": [1, 2, 1],
            "MD": [100.0, 150.0, 125.0],
            "X": [999.0, None, 1.0],
            "Y": [None, 888.0, 2.0],
        }
    ).to_csv(source, index=False)
    points = [
        WellTrajectoryPoint("t1", "A", "A", 0, 10, 20, 0, 0, 100, 0, 0),
        WellTrajectoryPoint("t1", "A", "A", 1, 30, 60, -100, 100, 200, 100, 100),
    ]

    class _Reader:
        def get_well_trajectory_points(self, _uuid):
            return points

    events = []
    monkeypatch.setattr(cli, "open_model_reader", lambda _path: _Reader())
    monkeypatch.setattr(cli, "_emit", lambda event, **payload: events.append((event, payload)))

    cli.calculate_sleeve_coordinates(
        {
            "path": str(source),
            "wellName": "A",
            "modelPath": "model.pet",
            "trajectoryUuid": "t1",
        }
    )

    result = pd.read_csv(source)
    assert result.loc[0, ["X", "Y"]].tolist() == pytest.approx([999, 20])
    assert result.loc[1, ["X", "Y"]].tolist() == pytest.approx([20, 888])
    assert result.loc[2, ["X", "Y"]].tolist() == pytest.approx([1, 2])
    payload = next(payload for event, payload in events if event == "result")
    assert payload["rowsUpdated"] == 2


def test_calculate_sleeve_coordinates_overwrites_existing_values(tmp_path, monkeypatch):
    source = tmp_path / "frac-list.csv"
    pd.DataFrame({"Well": ["A"], "Port": [1], "MD": [150.0], "X": [999.0], "Y": [888.0]}).to_csv(source, index=False)
    points = [
        WellTrajectoryPoint("t1", "A", "A", 0, 10, 20, 0, 0, 100, 0, 0),
        WellTrajectoryPoint("t1", "A", "A", 1, 30, 60, -100, 100, 200, 100, 100),
    ]

    class _Reader:
        def get_well_trajectory_points(self, _uuid):
            return points

    monkeypatch.setattr(cli, "open_model_reader", lambda _path: _Reader())
    monkeypatch.setattr(cli, "_emit", lambda _event, **_payload: None)

    cli.calculate_sleeve_coordinates(
        {
            "path": str(source),
            "wellName": "A",
            "modelPath": "model.pet",
            "trajectoryUuid": "t1",
            "overwriteExisting": True,
        }
    )

    result = pd.read_csv(source)
    assert result.loc[0, ["X", "Y"]].tolist() == pytest.approx([20, 40])


def test_calculate_sleeve_coordinates_updates_xlsx_in_place_and_preserves_sheets(tmp_path, monkeypatch):
    from openpyxl import Workbook, load_workbook

    source = tmp_path / "frac-list.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Well", "Port", "MD"])
    sheet.append(["A", 1, 150.0])
    workbook.create_sheet("Notes")["A1"] = "keep me"
    workbook.save(source)
    points = [
        WellTrajectoryPoint("t1", "A", "A", 0, 10, 20, 0, 0, 100, 0, 0),
        WellTrajectoryPoint("t1", "A", "A", 1, 30, 60, -100, 100, 200, 100, 100),
    ]

    class _Reader:
        def get_well_trajectory_points(self, _uuid):
            return points

    monkeypatch.setattr(cli, "open_model_reader", lambda _path: _Reader())
    monkeypatch.setattr(cli, "_emit", lambda _event, **_payload: None)

    cli.calculate_sleeve_coordinates(
        {"path": str(source), "wellName": "A", "modelPath": "model.pet", "trajectoryUuid": "t1"}
    )

    saved = load_workbook(source, data_only=False)
    headers = [cell.value for cell in saved.worksheets[0][1]]
    assert saved.worksheets[0].cell(2, headers.index("X") + 1).value == pytest.approx(20)
    assert saved.worksheets[0].cell(2, headers.index("Y") + 1).value == pytest.approx(40)
    assert saved["Notes"]["A1"].value == "keep me"

from pathlib import Path

from core.resqml_reader import GridInfo, ResqmlNamedHorizon, WellTrajectoryInfo
from web_backend import cli


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

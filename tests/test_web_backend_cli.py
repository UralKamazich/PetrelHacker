from pathlib import Path

from core.resqml_reader import GridInfo
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

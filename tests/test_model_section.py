from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

import core.model_section as model_section
from core.model_section import _build_section_horizons, _interface_plane_z_at_xy, _plane_z_at_xy, _sample_trajectory
from core.resqml_reader import GridInfo


def test_vectorized_interface_plane_projection_matches_individual_planes() -> None:
    xy = np.asarray([[0.0, 0.0], [2.0, 0.0], [0.0, 2.0], [2.0, 2.0]])
    points = np.empty((3, 4, 3), dtype=float)
    points[:, :, :2] = xy
    for interface, offset in enumerate((10.0, 20.0, 30.0)):
        points[interface, :, 2] = xy[:, 0] * 2.0 + xy[:, 1] * 3.0 + offset

    expected = np.asarray([_plane_z_at_xy(interface, 0.5, 1.5) for interface in points])

    assert _interface_plane_z_at_xy(points, 0.5, 1.5) == pytest.approx(expected)


def test_interface_plane_projection_falls_back_for_changing_xy() -> None:
    points = np.asarray(
        [
            [[0, 0, 0], [2, 0, 2], [0, 2, 4], [2, 2, 6]],
            [[1, 0, 10], [3, 0, 12], [1, 2, 14], [3, 2, 16]],
        ],
        dtype=float,
    )
    expected = np.asarray([_plane_z_at_xy(interface, 1.5, 1.0) for interface in points])

    assert _interface_plane_z_at_xy(points, 1.5, 1.0) == pytest.approx(expected)


def test_trajectory_sampling_has_no_station_limit_by_default() -> None:
    points = [
        SimpleNamespace(md=0.0, distance_along=0.0, horizontal_distance=0.0, x=0.0, y=0.0, z=0.0),
        SimpleNamespace(md=2000.0, distance_along=2000.0, horizontal_distance=2000.0, x=2000.0, y=0.0, z=0.0),
    ]

    stations = _sample_trajectory(points, sample_step=1.0, max_stations=None)

    assert len(stations) == 2001


def test_builds_horizon_from_a_different_model_grid(monkeypatch) -> None:
    grid = GridInfo(0, "Surface grid", "surface-grid", 1, 1, 1)

    class SurfaceReader:
        def list_grids(self):
            return [grid]

        def select_grid(self, _uuid):
            return None

        def list_named_horizons(self):
            return [SimpleNamespace(uuid="h1", title="Top", k_index=1)]

        def get_column_centers_xy(self):
            return np.asarray([[[0.5, 0.5]]])

        def get_cell_geometry_column(self, _i, _j):
            points = np.asarray(
                [
                    [[0, 0, -100], [1, 0, -100], [0, 1, -100], [1, 1, -100]],
                    [[0, 0, -200], [1, 0, -200], [0, 1, -200], [1, 1, -200]],
                ],
                dtype=float,
            )
            return {"points": points}

    surface_reader = SurfaceReader()
    monkeypatch.setattr(model_section, "resolve_model_path", lambda value: Path(value))
    monkeypatch.setattr(model_section, "open_model_reader", lambda _path: surface_reader)
    stations = [{"md": 10.0, "distance": 11.0, "horizontal_distance": 9.0, "x": 0.5, "y": 0.5}]
    sources = [{
        "path": "/surface-model",
        "gridUuid": "surface-grid",
        "horizonUuid": "h1",
        "selectionUuid": "M3::h1",
        "sourceModel": "M3",
        "depthOffset": 5.0,
    }]

    horizons = _build_section_horizons(
        stations,
        property_reader=object(),
        property_grid=GridInfo(0, "Property grid", "property-grid", 2, 2, 2),
        property_path=Path("/property-model"),
        property_depth_offset=0.0,
        horizon_sources=sources,
    )

    assert len(horizons) == 1
    assert (horizons[0].uuid, horizons[0].title) == ("M3::h1", "Top")
    assert horizons[0].points[0].depth == pytest.approx(205.0)

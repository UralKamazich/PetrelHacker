from types import SimpleNamespace

import pytest

from core.trajectory_analysis import analyze_trajectory, interpolate_trajectory_xy


def _point(md, x, y, z):
    return SimpleNamespace(md=md, distance_along=md, x=x, y=y, z=z)


def test_analyze_horizontal_trajectory_tail_azimuth_and_bottom_md():
    points = [_point(0, 0, 0, 100), _point(600, 0, 600, 100), _point(1000, 400, 600, 100)]

    result = analyze_trajectory(points)

    assert result["maxAngle"] == pytest.approx(90.0)
    assert result["last500Azimuth"] == pytest.approx(75.9637565)
    assert result["bottomMd"] == 1000
    assert result["altitude"] == 100


def test_interpolate_trajectory_xy_uses_md_and_rejects_outside_range():
    points = [_point(100, 10, 20, 0), _point(200, 30, 60, -100)]

    assert interpolate_trajectory_xy(points, 150) == pytest.approx((20, 40))
    assert interpolate_trajectory_xy(points, 99) is None
    assert interpolate_trajectory_xy(points, 201) is None

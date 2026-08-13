from __future__ import annotations

import math
from typing import Iterable


def analyze_trajectory(points: Iterable[object], altitude: float | None = None) -> dict[str, float | None]:
    ordered = sorted(list(points), key=_point_md)
    if not ordered:
        return {"maxAngle": None, "last500Azimuth": None, "bottomMd": None, "altitude": altitude}

    segments: list[dict[str, float]] = []
    max_angle = 0.0
    for left, right in zip(ordered, ordered[1:]):
        dx = float(right.x) - float(left.x)
        dy = float(right.y) - float(left.y)
        dz = float(right.z) - float(left.z)
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= 0:
            continue
        angle = math.degrees(math.acos(min(1.0, abs(dz) / length)))
        max_angle = max(max_angle, angle)
        segments.append(
            {
                "start": _point_md(left),
                "end": _point_md(right),
                "length": length,
                "azimuth": math.atan2(dx, dy),
            }
        )

    bottom_md = _point_md(ordered[-1])
    cutoff = bottom_md - 500.0
    sin_sum = 0.0
    cos_sum = 0.0
    for segment in segments:
        overlap = max(0.0, segment["end"] - max(segment["start"], cutoff))
        if overlap <= 0:
            continue
        sin_sum += math.sin(segment["azimuth"]) * overlap
        cos_sum += math.cos(segment["azimuth"]) * overlap
    azimuth = None
    if abs(sin_sum) > 1e-12 or abs(cos_sum) > 1e-12:
        azimuth = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0

    inferred_altitude = altitude
    if inferred_altitude is None:
        first_z = float(ordered[0].z)
        inferred_altitude = first_z if math.isfinite(first_z) else None
    return {
        "maxAngle": max_angle if segments else None,
        "last500Azimuth": azimuth,
        "bottomMd": bottom_md,
        "altitude": inferred_altitude,
    }


def interpolate_trajectory_xy(points: Iterable[object], md: float) -> tuple[float, float] | None:
    ordered = sorted(list(points), key=_point_md)
    if not ordered or not math.isfinite(md):
        return None
    first_md = _point_md(ordered[0])
    last_md = _point_md(ordered[-1])
    if md < first_md - 1e-6 or md > last_md + 1e-6:
        return None
    if md <= first_md:
        return float(ordered[0].x), float(ordered[0].y)
    for left, right in zip(ordered, ordered[1:]):
        left_md = _point_md(left)
        right_md = _point_md(right)
        if md > right_md:
            continue
        span = right_md - left_md
        fraction = 0.0 if span <= 0 else (md - left_md) / span
        return (
            float(left.x) + (float(right.x) - float(left.x)) * fraction,
            float(left.y) + (float(right.y) - float(left.y)) * fraction,
        )
    return float(ordered[-1].x), float(ordered[-1].y)


def _point_md(point: object) -> float:
    md = getattr(point, "md", None)
    if md is not None:
        value = float(md)
        if math.isfinite(value):
            return value
    return float(getattr(point, "distance_along"))

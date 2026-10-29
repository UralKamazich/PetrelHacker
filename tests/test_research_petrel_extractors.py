from __future__ import annotations

from pathlib import Path

from research.petrel.project_extractors import (
    read_well_shape_points,
    read_points3,
    read_xyz_trajectory_points,
    resolve_well_stub,
)
from research.petrel.project_metadata import PetrelProjectStub


def test_resolve_well_and_read_shape_points(tmp_path: Path) -> None:
    well = PetrelProjectStub("WellTraceSubject", "SubjectStub", "well", "root", 0, "5101G", True)
    folder = PetrelProjectStub("TrajectoryProviderFolder", "SubjectStub", "folder", "well", 0, "Surveys", True)
    trajectory = PetrelProjectStub("XYZTrajectoryProviderSubject", "SubjectStub", "trajectory", "folder", 0, "XYZ", True)
    stubs = {stub.uuid: stub for stub in (well, folder, trajectory) if stub.uuid}
    assert resolve_well_stub("trajectory", stubs) == well

    xml_path = tmp_path / "shape.xml"
    xml_path.write_text(
        """
        <data><full_trajectory_polygon><records><item>
          <md>100</md><vertex><double>1</double><double>2</double><double>-3</double></vertex>
          <inclination>4</inclination><azimuth>5</azimuth><dx_tn>6</dx_tn><dy_tn>7</dy_tn><dls>8</dls>
        </item></records></full_trajectory_polygon></data>
        """,
        encoding="utf-8",
    )
    rows = read_well_shape_points(
        xml_path,
        object_uuid="well",
        well_uuid="well",
        well_name="5101G",
    )
    assert rows[0]["md"] == 100.0
    assert rows[0]["tvd"] == 3.0


def test_read_xyz_trajectory_points(tmp_path: Path) -> None:
    xml_path = tmp_path / "xyz.xml"
    xml_path.write_text(
        """
        <data><settings><calculation_algorithm>2</calculation_algorithm><first_md>10</first_md></settings>
        <records><item><x>1</x><y>2</y><z>-3</z></item></records></data>
        """,
        encoding="utf-8",
    )
    rows = read_xyz_trajectory_points(
        xml_path,
        object_uuid="trajectory",
        well_uuid="well",
        well_name="5101G",
    )
    assert rows[0]["first_md"] == 10.0
    assert rows[0]["tvd"] == 3.0


def test_read_points3_with_typed_attributes(tmp_path: Path) -> None:
    xml_path = tmp_path / "points.xml"
    xml_path.write_text(
        """
        <data><vertices><double>1</double><double>2</double><double>-3</double></vertices>
        <attributes><type_vector><type>4</type><doubles><double>100</double></doubles><default /></type_vector>
        </attributes></data>
        """,
        encoding="utf-8",
    )
    z_stub = PetrelProjectStub("PointsAttrSubject", "SubjectStub", "z", None, 0, "Z", True)
    md_stub = PetrelProjectStub("PointsAttrSubject", "SubjectStub", "md", None, 1, "MD", True)
    rows = read_points3(xml_path, object_uuid="points", attribute_stubs=[z_stub, md_stub])
    assert rows == [
        {
            "object_uuid": "points",
            "point_index": 0,
            "x": 1.0,
            "y": 2.0,
            "z": -3.0,
            "tvd": 3.0,
            "MD": 100.0,
        }
    ]

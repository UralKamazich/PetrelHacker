from __future__ import annotations

from pathlib import Path
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from core.model_reader import open_model_reader
from core.rescue_reader import (
    RescueReader,
    _decode_triplet_file,
    _horizon_titles_from_model,
    _reshape_triplet_cell_points,
    _triplet_geometry_block_index,
    _trajectory_records_from_model,
    is_rescue_path,
)


def test_rescue_reader_loads_grid_properties_and_values(tmp_path: Path) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(
        b"%Rescue Model File\x00"
        b"\x00\x00\x04EOD"
        b"\x00\x00\x04EOD"
        b"\x00\x00\x05PORO"
        b"\x00\x00\x08Porosity"
        b"\x00\x00\x16Dummy Unit Of Measure"
        + (123).to_bytes(4, "big")
        + b"\x00\x0bdirtyMinMax"
        b"\x00\x06minMax"
    )
    _write_geometry(tmp_path / "model.bin.60", ni=3, nj=4, nk=5)
    _write_property(tmp_path / "model.bin.123", [0.1, 0.2, 0.3, 0.4])
    (tmp_path / "model.crsmeta.xml").write_text(
        """
        <SpatialCompanion>
          <ExamplePointConversions>
            <ExampleConversion><Point location="10 20" coordinateReferenceSystemId="GK42-13N" /></ExampleConversion>
            <ExampleConversion><Point location="30 20" coordinateReferenceSystemId="GK42-13N" /></ExampleConversion>
            <ExampleConversion><Point location="30 60" coordinateReferenceSystemId="GK42-13N" /></ExampleConversion>
            <ExampleConversion><Point location="10 60" coordinateReferenceSystemId="GK42-13N" /></ExampleConversion>
          </ExamplePointConversions>
        </SpatialCompanion>
        """,
        encoding="utf-8",
    )

    assert is_rescue_path(tmp_path)
    reader = open_model_reader(tmp_path)

    grid = reader.list_grids()[0]
    assert (grid.ni, grid.nj, grid.nk) == (2, 3, 4)
    prop = reader.list_properties()[0]
    assert prop.title == "PORO"
    stats = reader.get_property_decode_stats(prop.uuid)
    assert stats["logical_count"] == 24
    assert stats["valid_count"] == 2
    assert stats["blank_count"] == 22
    assert stats["first_run_length"] == 19
    assert reader.get_property_value(prop.uuid, 1, 0, 0) == 0.20000000298023224
    assert reader.get_property_value(prop.uuid, 0, 1, 0) == ""
    assert reader.get_property_value(prop.uuid, 1, 1, 0) == 0.4000000059604645
    geometry = reader.get_cell_geometry_column(0, 0)
    assert geometry["TVD_top"] == [57.5, 67.5, 77.5, 87.5]
    assert geometry["TVD_base"] == [67.5, 77.5, 87.5, 97.5]
    assert geometry["CellHeight"] == [10.0, 10.0, 10.0, 10.0]
    corner_geometry = reader.get_cell_geometry_column(1, 2)
    assert corner_geometry["TVD_top"] == [51.5, 61.5, 71.5, 81.5]
    assert corner_geometry["TVD_base"] == [61.5, 71.5, 81.5, 91.5]
    centers = reader.get_column_centers_xy()
    assert centers.shape == (3, 2, 2)
    assert centers[0, 0].tolist() == pytest.approx([15.0, 26.666666666666668])
    assert centers[-1, -1].tolist() == pytest.approx([25.0, 53.33333333333333])


def test_rescue_horizon_titles_and_triplet_geometry(tmp_path: Path) -> None:
    model_bytes = (
        b"%Rescue Model File\x00"
        b"\x00\x11Top_GMM - Ach_5\x00\x00\x00"
        b"\x00\x0fAch_5 - Bot_GMM\x00"
    )
    assert _horizon_titles_from_model(model_bytes) == ["Top_GMM", "Ach_5", "Bot_GMM"]

    path = tmp_path / "model.bin.100"
    _write_triplet(path, [1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0], [-100.0] * 4)
    x, y, z = _decode_triplet_file(path)

    assert x.tolist() == [1.0, 2.0, 3.0, 4.0]
    assert y.tolist() == [10.0, 20.0, 30.0, 40.0]
    assert z.tolist() == [-100.0] * 4


def test_reads_rescue_trajectory_name_and_triplet_reference() -> None:
    file_id = 15516
    raw = (
        b"prefix"
        + file_id.to_bytes(4, "big")
        + b"\x00\x04EOD\x00\x00\x057103\x00"
        + b"suffix"
    )

    assert _trajectory_records_from_model(raw, {file_id}) == [(file_id, "7103")]


def test_samples_multiple_rescue_horizons_with_one_xy_lookup(tmp_path: Path) -> None:
    reader = RescueReader(tmp_path)
    reader._horizon_files = {"h1": object(), "h2": object()}
    reader._xy_bounds = (100.0, 110.0, 200.0, 210.0)
    reader._grids = [SimpleNamespace(ni=2, nj=2)]
    reader._horizon_sample_points = lambda: (
        np.asarray([0.0, 10.0]),
        np.asarray([0.0, 10.0]),
        np.asarray([0, 1]),
    )
    values = {
        "h1": np.asarray([-10.0, -123.0]),
        "h2": np.asarray([-20.0, -456.0]),
    }
    reader._horizon_z_values = values.__getitem__

    depths = reader.get_named_horizon_depths(("h1", "h2", "missing"), 109.0, 209.0)

    assert depths == {"h1": 123.0, "h2": 456.0}


def test_reshape_triplet_surface_uses_doubled_grid_rows() -> None:
    # Stored as two complete corner rows for each J row:
    # [cell 0 left/right, cell 1 left/right], then the lower corners.
    x = np.asarray([0, 1, 1, 2, 10, 11, 11, 12], dtype=np.float32)
    y = np.asarray([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.float32)

    points = _reshape_triplet_cell_points(x, y, ni=2, nj=1)

    assert points.shape == (1, 2, 4, 2)
    assert points[0, 0].tolist() == [[0, 0], [1, 0], [10, 1], [11, 1]]
    assert points[0, 1].tolist() == [[1, 0], [2, 0], [11, 1], [12, 1]]

    block_index = _triplet_geometry_block_index(points, expected_block_count=6)
    assert block_index[(0.0, 0.0)] == 0
    assert block_index[(10.0, 1.0)] == 1
    assert block_index[(1.0, 0.0)] == 2
    assert block_index[(11.0, 1.0)] == 3


def _write_geometry(path: Path, *, ni: int, nj: int, nk: int) -> None:
    data = bytearray(80)
    label = b"\x03Rescue Geometry File\x00"
    data[: len(label)] = label
    data[22:25] = b"\x00\x00\x01"
    data[25:29] = b"\x7f\x7f\xff\xff"
    data[29:33] = ni.to_bytes(4, "big")
    data[33:37] = nj.to_bytes(4, "big")
    data[37:41] = nk.to_bytes(4, "big")
    for column in range(ni * nj):
        data.extend(nk.to_bytes(4, "big"))
        data.extend((1).to_bytes(4, "big"))
        data.extend(bytes([nk]))
        z0 = -100.0 + column
        data.extend(struct.pack(">" + "f" * nk, *(z0 + 10.0 * k for k in range(nk))))
    data.extend(b"\x00\x16abracadabra jump jump\x00")
    path.write_bytes(data)


def _write_property(path: Path, values: list[float]) -> None:
    data = bytearray(b"\x02Rescue Property File\x00\x00\x00\x01")
    data.extend((24).to_bytes(4, "big"))
    data.extend(b"\x13\x7f\x7f\xff\xff\xfd\x01")
    data.extend(struct.pack(">f", values[1]))
    data.extend(b"\x01\x7f\x7f\xff\xff\xfd\x01")
    data.extend(struct.pack(">f", values[3]))
    data.extend(b"\x02\x7f\x7f\xff\xff")
    data.extend(b"\x00\x16abracadabra jump jump\x00")
    path.write_bytes(data)


def _write_triplet(path: Path, x: list[float], y: list[float], z: list[float]) -> None:
    data = bytearray(b"\x03Rescue Triplet File\x00\x00\x00\x01")
    for values in (x, y, z):
        data.extend(len(values).to_bytes(4, "big"))
        data.extend(b"\xfd")
        data.extend(bytes((len(values),)))
        data.extend(struct.pack(">" + "f" * len(values), *values))
    data.extend(b"\x00\x00\x00\x00\x00\x04EOD\x00\x00\x16abracadabra jump jump\x00")
    path.write_bytes(data)

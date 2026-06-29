from __future__ import annotations

from pathlib import Path
import struct

import pytest

from core.model_reader import open_model_reader
from core.rescue_reader import is_rescue_path


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
    assert stats["first_run_length"] == 0
    assert reader.get_property_value(prop.uuid, 1, 0, 0) == 0.20000000298023224
    assert reader.get_property_value(prop.uuid, 0, 1, 0) == ""
    assert reader.get_property_value(prop.uuid, 1, 1, 0) == 0.4000000059604645
    geometry = reader.get_cell_geometry_column(0, 0)
    assert geometry["TVD_top"] == [58.0, 68.0, 78.0, 88.0]
    assert geometry["TVD_base"] == [68.0, 78.0, 88.0, 98.0]
    assert geometry["CellHeight"] == [10.0, 10.0, 10.0, 10.0]
    centers = reader.get_column_centers_xy()
    assert centers.shape == (3, 2, 2)
    assert centers[0, 0].tolist() == pytest.approx([15.0, 26.666666666666668])
    assert centers[-1, -1].tolist() == pytest.approx([25.0, 53.33333333333333])


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
    data = bytearray(34)
    label = b"\x02Rescue Property File\x00"
    data[: len(label)] = label
    data[22:25] = b"\x00\x00\x01"
    data[26:30] = struct.pack(">f", -999.25)
    data[30:34] = (0).to_bytes(4, "big")
    data.extend(b"\x13\x7f\x7f\xff\xff\xfd\x01")
    data.extend(struct.pack(">f", values[1]))
    data.extend(b"\x01\x7f\x7f\xff\xff\xfd\x01")
    data.extend(struct.pack(">f", values[3]))
    data.extend(b"\x00\x16abracadabra jump jump\x00")
    path.write_bytes(data)

from __future__ import annotations

import struct
import uuid

from core.petrel_grid_reader import (
    _detect_geometry_mode,
    _parse_horizontal_shape_data,
    _parse_vertical_curve_pillar_header,
    _read_paged_section,
    _remove_bxml_stream_metadata,
)
from core.petrel_model_metadata import extract_petrel_object_names, extract_petrel_parent_names
from core.petrel_property_reader import (
    PetrelPropertyReader,
    _parse_property_shape_data,
    _read_property_dictionary_extension,
    _strip_binary_segment_frame,
)
from core.petrel_trajectory_reader import _consume_marker, _read_bxml_number, decode_petrel_well_shape


def test_strips_binary_page_frame_between_float_bytes():
    values = struct.pack("<ff", -3721.79760742, -3722.37744141)
    framed = values[:3] + b"\xa0\xff\x1f" + values[3:]

    assert _remove_bxml_stream_metadata(framed) == values


def test_strips_dictionary_extension_between_float_bytes():
    values = struct.pack("<ff", -3894.06689453, -3894.39990234)
    dictionary = b"\xa1\x05alpha\xa1\x04beta\xa0\xf7\x0a"
    framed = values[:3] + dictionary + values[3:]

    assert _remove_bxml_stream_metadata(framed) == values


def test_strips_property_binary_segment_frame():
    payload = bytes(range(32))
    framed = payload[:7] + b"\xa0\x99\x80\x00" + payload[7:]

    assert _strip_binary_segment_frame(framed, len(payload)) == payload


def test_strips_property_binary_segment_frame_with_long_varint():
    payload = bytes(range(32))
    framed = payload[:7] + b"\xa0\x99\x80\x80\x00" + payload[7:]

    assert _strip_binary_segment_frame(framed, len(payload)) == payload


def test_strips_final_int_page_before_next_segment_and_pads_nodata_tail():
    payload = bytes((1, 2, 3, 4, 5, 6))
    framed = payload[:2] + b"\xa0\x04" + payload[2:] + b"\xa0\x05"

    assert _strip_binary_segment_frame(framed, 8, pad_byte=255) == payload + b"\xff\xff"


def test_extracts_model_name_for_binary_petrel_guid():
    object_uuid = uuid.UUID("97867d75-2577-4780-80ab-f8b31dd19380")
    dictionary = b"BXML\x01\xa1\x04name\xa0"
    record = b"\x42\x00\xb1" + object_uuid.bytes_le + b"\x42\x00\x99\x03NTG"

    assert extract_petrel_object_names(dictionary + record, [f"://Petrel/{object_uuid}"]) == {
        str(object_uuid): "NTG"
    }


def test_parses_property_cell_shape_from_header():
    names = ["cell_size", "int"]
    marker = b"\x42\x00\x03\x42\x02\x01\x8d\x03"
    body = marker + struct.pack("<III", 187, 187, 813)

    assert _parse_property_shape_data(body, names, 0) == (187, 187, 813)


def test_parses_grid_horizontal_shape_from_header():
    dictionary = b"BXML\x01\xa1\x09node_size\xa1\x03int\xa0"
    marker = b"\x42\x00\x03\x42\x02\x01\x8d\x02"
    body = marker + struct.pack("<II", 711, 715) + b"\x01"

    assert _parse_horizontal_shape_data(dictionary + body) == (710, 714)


def test_extracts_parent_well_name_for_trajectory_guid():
    well_uuid = uuid.UUID("ba30d4a6-5627-498e-b182-161fa05d5d7a")
    trajectory_uuid = uuid.UUID("064ed32f-fa0e-474f-a147-5f58ccc6d878")
    dictionary = b"BXML\x01\xa1\x0aunique_tag\xa1\x04name\xa0"
    record = (
        b"\x42\x00\xb1"
        + well_uuid.bytes_le
        + b"\x42\x02\x99\x04U202"
        + b"\x42\x04\xb1"
        + trajectory_uuid.bytes_le
    )
    raw = dictionary + b"\xa2\xa0" + bytes((len(record),)) + record

    assert extract_petrel_parent_names(raw, [str(trajectory_uuid)]) == {
        str(trajectory_uuid): "U202"
    }


def test_reads_compact_petrel_numbers():
    assert _read_bxml_number(b"\x81", 0) == (0, 1)
    assert _read_bxml_number(b"\x89\x55", 0) == (85, 2)
    assert _read_bxml_number(b"\x8b\xcd\xec", 0) == (-4915, 3)
    value, offset = _read_bxml_number(b"\x91" + struct.pack("<f", -3721.5), 0)
    assert value == -3721.5
    assert offset == 5


def test_decodes_dummy_well_shape_md_and_xyz_records():
    names = [
        "records",
        "item",
        "md",
        "vertex",
        "double",
        "inclination",
        "azimuth",
        "dx_tn",
        "dy_tn",
        "dls",
    ]
    dictionary = b"BXML\x01" + b"".join(
        b"\xa1" + bytes((len(name),)) + name.encode("ascii") for name in names
    ) + b"\xa0"
    tag = lambda index: bytes((0x42, index * 2))
    records = []
    for md, point in ((0.0, (10.0, 20.0, 30.0)), (100.0, (40.0, 50.0, -60.0))):
        records.append(
            tag(1)
            + tag(2)
            + b"\x93"
            + struct.pack("<d", md)
            + tag(3)
            + b"\x03"
            + tag(4)
            + b"\x01\x93\x03"
            + struct.pack("<3d", *point)
            + b"\x01"
            + b"".join(tag(index) + b"\x81" for index in range(5, 10))
            + b"\x01"
        )
    body = tag(0) + b"\x06\x08\x88\x02" + b"".join(records)
    page_size = bytes(((len(body) & 0x7F) | 0x80, len(body) >> 7))
    raw = dictionary + page_size + body

    md, points = decode_petrel_well_shape(raw)

    assert md.tolist() == [0.0, 100.0]
    assert points.tolist() == [[10.0, 20.0, 30.0], [40.0, 50.0, -60.0]]


def test_consumes_bxml_page_frame_inside_marker():
    data = b"\x42\xa0\xff\x1f\x24\x93"

    assert _consume_marker(data, 0, b"\x42\x24\x93") == len(data)


def test_reads_chained_bxml_pages_and_dictionary_extensions():
    first = b"first-page"
    second = b"second-page"
    data = (
        b"prefix"
        b"\xa1\x07pillars\xa1\x05curve\xa1\x08vertices\xa1\x07zvalues"
        + b"\xa0"
        + bytes((len(first),))
        + first
        + b"\xa1\x05float\xa1\x06double\xa0"
        + bytes((len(second),))
        + second
    )

    payload, pages, names = _read_paged_section(data, b"pillars")

    assert payload == first + second
    assert [page[2] for page in pages] == [len(first), len(second)]
    assert names == ["pillars", "curve", "vertices", "zvalues", "float", "double"]
    assert _detect_geometry_mode(data) == "vertical_curve"


def test_normalizes_vertical_petrel_curve_to_xy_position():
    vertices = (
        (527093.31250000, 7416219.00000000, -4500.0),
        (527093.31250001, 7416219.00000002, -2250.0),
        (527093.31249999, 7416218.99999998, 0.0),
    )
    flat_vertices = struct.pack("<9d", *(value for vertex in vertices for value in vertex))
    header = (
        b"\x40\x06\x00\x88\x07"
        b"\x42\x4c\x89\x03"
        b"\x42\x50\x01\x93\x09"
        + flat_vertices
        + b"\x42\x5a\x01\x91\x05"
    )

    xy, z_offset, count = _parse_vertical_curve_pillar_header(header, 0)

    assert xy == (527093.3125, 7416219.0)
    assert z_offset == len(header)
    assert count == 5


def test_reads_late_sparse_property_dictionary():
    extension = (
        b"prefix"
        b"\xa1\x10is_undef_checked"
        b"\xa1\x06values"
        b"\xa1\x0bno_elements"
        b"\xa1\x05pages"
        b"\xa1\x04page"
        b"\xa1\x05float"
        b"\xa0payload"
    )

    assert _read_property_dictionary_extension(extension, 0) == [
        "is_undef_checked",
        "values",
        "no_elements",
        "pages",
        "page",
        "float",
    ]


def test_maps_dense_cell_indices_through_sparse_property_mask():
    reader = PetrelPropertyReader.__new__(PetrelPropertyReader)
    reader._defined_mask = bytes((0b10110100,))
    reader._mask_block_size = 4096
    reader._mask_block_prefix = reader._build_mask_block_prefix()

    assert reader._stored_value_index(0) is None
    assert reader._stored_value_index(2) == 0
    assert reader._stored_value_index(4) == 1
    assert reader._stored_value_index(5) == 2
    assert reader._stored_value_index(7) == 3


def test_pillar_markers_follow_shifted_dictionary_tags() -> None:
    from core.petrel_grid_reader import _pillar_markers

    names = ["pillars", "pillar", "degree", "old_value", "is_truncated", "geometry", "position", "double",
             "zmin", "zmax", "sequence", "max_truncated", "min_truncated", "zvalues", "float", "has_bools"]
    extension = b"".join(b"\xa1" + bytes((len(name),)) + name.encode("ascii") for name in names)
    # "pillars" uses tag 0x40 instead of the usual 0x3e (one extra name earlier in the file).
    data = b"BXML\x01" + extension + b"\xa0\x80\x20\x01\x42\x40\x06\x08\x88\xff\x42\x42\x06\x00\x88\x07"

    markers = _pillar_markers(data)

    assert markers.straight == b"\x42\x06\x00\x88\x07"
    assert markers.position == b"\x4e\x01\x93\x02"
    assert markers.z_values == b"\x5c\x01\x91"

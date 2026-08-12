from __future__ import annotations

import struct
import uuid

from core.petrel_grid_reader import _parse_horizontal_shape_data, _remove_bxml_stream_metadata
from core.petrel_model_metadata import extract_petrel_object_names
from core.petrel_property_reader import _strip_binary_segment_frame
from core.petrel_property_reader import _parse_property_shape_data


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

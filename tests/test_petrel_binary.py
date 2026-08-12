from __future__ import annotations

import struct

from core.petrel_grid_reader import _remove_bxml_stream_metadata
from core.petrel_property_reader import _strip_binary_segment_frame


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

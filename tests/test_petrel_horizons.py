from __future__ import annotations

import struct
import uuid

from core.petrel_horizon_reader import _read_class_stubs


def test_reads_petrel_project_horizon_stub_records():
    folder_uuid = uuid.UUID("3e325e24-1a30-420e-8f68-3aa0b7d544cb")
    horizon_uuid = uuid.UUID("aac50edc-5175-4ca2-a166-cae4574bc2f1")
    raw = (
        _class_header("HorizonSubject")
        + _stub_record(folder_uuid, horizon_uuid, 2, "Ach_5")
        + _class_header("ZoneSubject")
    )

    assert _read_class_stubs(raw, "HorizonSubject") == [
        _stub(folder_uuid, horizon_uuid, 2, "Ach_5")
    ]


def _class_header(name: str) -> bytes:
    value = name.encode("utf-8")
    return b"\x42\x2a\x42\x2c\x99" + bytes((len(value),)) + value


def _stub_record(parent_uuid: uuid.UUID, item_uuid: uuid.UUID, kid_index: int, title: str) -> bytes:
    value = title.encode("utf-8")
    return (
        b"\x42\x36\xb1"
        + parent_uuid.bytes_le
        + b"\x42\x38\xb1"
        + item_uuid.bytes_le
        + b"\x42\x3a\x8d"
        + struct.pack("<i", kid_index)
        + b"\x42\x3c\x99"
        + bytes((len(value),))
        + value
    )


def _stub(parent_uuid: uuid.UUID, item_uuid: uuid.UUID, kid_index: int, title: str):
    from core.petrel_horizon_reader import _ProjectStub

    return _ProjectStub(str(parent_uuid), str(item_uuid), kid_index, title)

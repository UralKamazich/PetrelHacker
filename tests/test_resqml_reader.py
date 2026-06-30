from __future__ import annotations

from core.resqml_reader import _parse_epc_xml, _title


def test_parse_epc_xml_tolerates_cp1251_title_bytes_declared_as_utf8() -> None:
    root = _parse_epc_xml(
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<resqml2:IjkGridRepresentation '
        b'xmlns:resqml2="http://www.energistics.org/energyml/data/resqmlv2" '
        b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        b'uuid="grid-1" xsi:type="resqml2:obj_IjkGridRepresentation">'
        b'<eml20:Citation xmlns:eml20="http://www.energistics.org/energyml/data/commonv2">'
        b'<eml20:Title>Bad \xff title</eml20:Title>'
        b'</eml20:Citation>'
        b'<resqml2:Ni>1</resqml2:Ni>'
        b'</resqml2:IjkGridRepresentation>'
    )

    assert root.attrib["uuid"] == "grid-1"
    assert _title(root) == "Bad я title"

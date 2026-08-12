from __future__ import annotations

import zipfile

import h5py

from core.resqml_reader import ResqmlReader, _parse_epc_xml, _title


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


def test_lists_named_horizon_from_interval_edge_subrepresentation(tmp_path) -> None:
    epc_path = tmp_path / "model.epc"
    h5_path = tmp_path / "model.h5"
    grid_xml = _object_xml("IjkGridRepresentation", "grid-1", "Grid", "<resqml2:Ni>1</resqml2:Ni><resqml2:Nj>1</resqml2:Nj><resqml2:Nk>10</resqml2:Nk>")
    subrep_xml = _object_xml(
        "SubRepresentation",
        "horizon-1",
        "Ach_5 Subrepresentation",
        """
        <resqml2:SupportingRepresentation xmlns:eml20="http://www.energistics.org/energyml/data/commonv2">
          <eml20:ContentType>application/x-resqml+xml;version=2.0;type=obj_IjkGridRepresentation</eml20:ContentType>
          <eml20:UUID>grid-1</eml20:UUID>
        </resqml2:SupportingRepresentation>
        <resqml2:SubRepresentationPatch>
          <resqml2:ElementIndices>
            <resqml2:IndexableElement>interval edges</resqml2:IndexableElement>
            <resqml2:Indices><resqml2:Values xmlns:eml20="http://www.energistics.org/energyml/data/commonv2">
              <eml20:PathInHdfFile>/RESQML/horizon-1/indices</eml20:PathInHdfFile>
            </resqml2:Values></resqml2:Indices>
          </resqml2:ElementIndices>
        </resqml2:SubRepresentationPatch>
        """,
    )
    with zipfile.ZipFile(epc_path, "w") as package:
        package.writestr("obj_IjkGridRepresentation_grid-1.xml", grid_xml)
        package.writestr("obj_SubRepresentation_horizon-1.xml", subrep_xml)
    with h5py.File(h5_path, "w") as h5:
        h5.create_dataset("/RESQML/horizon-1/indices", data=[7])

    reader = ResqmlReader(epc_path)
    reader.open(validate_with_resqpy=False)
    reader.select_grid("grid-1")

    horizons = reader.list_named_horizons()
    assert len(horizons) == 1
    horizon = horizons[0]
    assert (horizon.uuid, horizon.title, horizon.grid_uuid, horizon.k_index) == (
        "horizon-1",
        "Ach_5",
        "grid-1",
        7,
    )


def _object_xml(kind: str, uuid: str, title: str, body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <resqml2:{kind} xmlns:resqml2="http://www.energistics.org/energyml/data/resqmlv2"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" uuid="{uuid}" xsi:type="resqml2:obj_{kind}">
      <eml20:Citation xmlns:eml20="http://www.energistics.org/energyml/data/commonv2">
        <eml20:Title>{title}</eml20:Title>
      </eml20:Citation>
      {body}
    </resqml2:{kind}>"""

from __future__ import annotations

from pathlib import Path

from research.petrel.project_metadata import read_project_stubs, stubs_by_uuid


def test_read_project_stubs(tmp_path: Path) -> None:
    xml_path = tmp_path / "project.xml"
    xml_path.write_text(
        """
        <node xmlns="http://www.slb.com/Petrel/2011/03/Serialization">
          <class_infos><map><entry>
            <key>PropertySubject</key>
            <value><stubs Size="1"><item Type="SubjectStub">
              <parentTag>AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA</parentTag>
              <uniqueTag>BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB</uniqueTag>
              <kidIndex>7</kidIndex><visualName>PORO</visualName><hasVisibleIcon>true</hasVisibleIcon>
            </item></stubs></value>
          </entry></map></class_infos>
        </node>
        """,
        encoding="utf-8",
    )
    stubs = read_project_stubs(xml_path)
    assert len(stubs) == 1
    stub = stubs[0]
    assert stub.class_name == "PropertySubject"
    assert stub.uuid == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert stub.parent_uuid == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert stub.visual_name == "PORO"
    assert stub.kid_index == 7
    assert stub.has_visible_icon is True
    assert stubs_by_uuid(stubs)[stub.uuid] == stub

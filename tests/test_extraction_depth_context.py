from __future__ import annotations

from core.property_extractor import _cell_center, _relative_depth
from core.resqml_reader import PropertyInfo
from core.property_extractor import PropertyExtractor


def test_relative_depth_helpers_use_port_tvdss() -> None:
    assert _cell_center(100.0, 110.0) == 105.0
    assert _relative_depth(110.0, 100.5) == 9.5
    assert _relative_depth("", 100.5) == ""
    assert _relative_depth(110.0, "") == ""


def test_property_output_columns_include_port_depth_context() -> None:
    prop = PropertyInfo(index=0, title="YME_STA", uuid="p1")

    columns = PropertyExtractor._output_columns([prop])

    assert columns[:14] == [
        "Well",
        "Port",
        "X",
        "Y",
        "TVDSS_PORT",
        "I",
        "J",
        "K",
        "IsActive",
        "TVD_top",
        "TVD_base",
        "TVD_center",
        "Rel_TVD_top",
        "Rel_TVD_base",
    ]
    assert "Rel_TVD_center" in columns
    assert columns[-1] == "YME_STA"

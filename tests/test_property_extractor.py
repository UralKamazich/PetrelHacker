from __future__ import annotations

from core.property_extractor import PERM_TO_MD_MULTIPLIER, transform_property_value
from core.resqml_reader import PropertyInfo


def _prop(title: str) -> PropertyInfo:
    return PropertyInfo(index=0, title=title, uuid=title.lower())


def test_transform_property_value_multiplies_perm_properties() -> None:
    assert transform_property_value(_prop("PERM"), 2) == 2 * PERM_TO_MD_MULTIPLIER
    assert transform_property_value(_prop("PermX"), 1.5) == 1.5 * PERM_TO_MD_MULTIPLIER
    assert transform_property_value(_prop("rock_perm_y"), 0.25) == 0.25 * PERM_TO_MD_MULTIPLIER


def test_transform_property_value_leaves_non_perm_properties() -> None:
    assert transform_property_value(_prop("PORO"), 2) == 2


def test_transform_property_value_keeps_int_nodata_blank_before_perm_scaling() -> None:
    assert transform_property_value(_prop("PERM"), 2147483647) == ""
    assert transform_property_value(_prop("PERM"), 2147483647.0) == ""
    assert transform_property_value(_prop("PERM"), -2147483648) == ""

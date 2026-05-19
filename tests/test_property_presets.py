from __future__ import annotations

from core.property_presets import default_property_titles, normalize_property_title, should_select_property
from core.resqml_reader import PropertyInfo


def _prop(title: str, uuid: str | None = None) -> PropertyInfo:
    return PropertyInfo(index=0, title=title, uuid=uuid or title.lower())


def test_normalize_property_title_ignores_case_and_separators() -> None:
    assert normalize_property_title("perm_x") == "PERMX"
    assert normalize_property_title(" Layers ") == "LAYERS"


def test_default_property_titles_selects_popular_exact_names() -> None:
    properties = [_prop("NTG"), _prop("Layers"), _prop("PORO"), _prop("PERM"), _prop("SW")]
    assert default_property_titles(properties) == {"NTG", "Layers", "PORO", "PERM"}


def test_should_select_saved_uuid_before_defaults() -> None:
    prop = _prop("SW", "uuid-sw")
    assert should_select_property(prop, {"uuid-sw"}, set(), use_defaults=False)


def test_should_select_saved_title_by_normalized_name() -> None:
    prop = _prop("Poro")
    assert should_select_property(prop, set(), {"PORO"}, use_defaults=False)


def test_should_select_default_only_when_enabled() -> None:
    prop = _prop("NTG")
    assert should_select_property(prop, set(), set(), use_defaults=True)
    assert not should_select_property(prop, set(), set(), use_defaults=False)

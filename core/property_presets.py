from __future__ import annotations

from core.resqml_reader import PropertyInfo


DEFAULT_PROPERTY_TITLES = ("NTG", "Layers", "PORO", "PERM")


def normalize_property_title(title: str) -> str:
    return "".join(char for char in title.upper() if char.isalnum())


def default_property_titles(properties: list[PropertyInfo]) -> set[str]:
    defaults = {normalize_property_title(title) for title in DEFAULT_PROPERTY_TITLES}
    return {
        prop.title
        for prop in properties
        if normalize_property_title(prop.title) in defaults
    }


def should_select_property(
    prop: PropertyInfo,
    saved_uuids: set[str],
    saved_titles: set[str],
    use_defaults: bool,
) -> bool:
    if prop.uuid in saved_uuids:
        return True
    if normalize_property_title(prop.title) in saved_titles:
        return True
    if use_defaults and prop.title in default_property_titles([prop]):
        return True
    return False

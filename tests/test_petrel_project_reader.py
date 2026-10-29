from __future__ import annotations

from core.petrel_model_metadata import PetrelProjectNode, resolve_petrel_property_paths
from core.petrel_project_reader import PetrelProjectReader
from core.resqml_reader import GridInfo, PropertyInfo


def _reader_with_selected_grid(properties: list[PropertyInfo], selected_uuid: str) -> PetrelProjectReader:
    reader = PetrelProjectReader.__new__(PetrelProjectReader)
    reader._properties = properties
    reader._selected_grid_uuid = selected_uuid
    reader._grids = [GridInfo(0, "Selected", selected_uuid, 10, 20, 30)]
    return reader


def test_selected_petrel_grid_does_not_fall_back_to_other_grid_properties() -> None:
    reader = _reader_with_selected_grid(
        [PropertyInfo(0, "PORO", "property-1", supporting_grid_uuid="grid-1")],
        "grid-empty",
    )

    assert reader.list_properties() == []


def test_unscoped_petrel_properties_remain_available_for_legacy_projects() -> None:
    prop = PropertyInfo(0, "PORO", "property-1")
    reader = _reader_with_selected_grid([prop], "grid-1")

    assert reader.list_properties() == [prop]


def test_resolves_petrel_property_folder_path_from_project_stubs() -> None:
    root_uuid = "00000000-0000-0000-0000-000000000001"
    grid_uuid = "00000000-0000-0000-0000-000000000002"
    folder_1_uuid = "00000000-0000-0000-0000-000000000003"
    folder_2_uuid = "00000000-0000-0000-0000-000000000004"
    folder_3_uuid = "00000000-0000-0000-0000-000000000005"
    property_uuid = "00000000-0000-0000-0000-000000000006"
    nodes = {
        grid_uuid: PetrelProjectNode(grid_uuid, root_uuid, "Grid"),
        folder_1_uuid: PetrelProjectNode(folder_1_uuid, grid_uuid, "Properties"),
        folder_2_uuid: PetrelProjectNode(folder_2_uuid, folder_1_uuid, "Geomechanical properties"),
        folder_3_uuid: PetrelProjectNode(folder_3_uuid, folder_2_uuid, "Elastic Isotropic"),
        property_uuid: PetrelProjectNode(property_uuid, folder_3_uuid, "YOUNGMOD"),
    }

    result = resolve_petrel_property_paths(nodes, [property_uuid], [grid_uuid])

    assert result[property_uuid].title == "YOUNGMOD"
    assert result[property_uuid].grid_uuid == grid_uuid
    assert result[property_uuid].folder_path == (
        "Geomechanical properties",
        "Elastic Isotropic",
    )

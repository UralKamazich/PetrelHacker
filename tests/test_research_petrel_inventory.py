from __future__ import annotations

import csv
from pathlib import Path

from research.petrel.project_metadata import PetrelProjectStub
from research.petrel.inspect_project import _write_model_inventory


def test_model_inventory_associates_properties_and_named_horizons(tmp_path: Path) -> None:
    stubs = [
        _stub("ModelSubject", "model", None, "Model"),
        _stub("PillarGridSubject", "geo", "model", "Geo"),
        _stub("PropertyFolder", "properties", "geo", "Properties"),
        _stub("PropertySubject", "poro", "properties", "PORO"),
        _stub("PropertySubject", "ntg", "properties", "NTG"),
        _stub("HorizonFolder", "geo_horizons", "geo", "Horizons"),
        _stub("HorizonSubject", "h1", "geo_horizons", "Horizon 1", kid_index=0),
        _stub("PillarGridSubject", "gmm", "model", "GMM"),
        _stub("HorizonFolder", "gmm_horizons", "gmm", "Horizons"),
        _stub("HorizonSubject", "top", "gmm_horizons", "Ach_5", kid_index=0),
        _stub("HorizonSubject", "base", "gmm_horizons", "Ach5_bot", kid_index=1),
    ]

    summaries = _write_model_inventory(tmp_path, stubs)

    geo = next(row for row in summaries if row["grid_uuid"] == "geo")
    assert geo["is_geological_candidate"] is True
    assert geo["geological_markers"] == "NTG | PORO"
    assert geo["named_horizon_count"] == 0

    gmm = next(row for row in summaries if row["grid_uuid"] == "gmm")
    assert gmm["is_geological_candidate"] is False
    assert gmm["named_horizons"] == "Ach_5 | Ach5_bot"

    with (tmp_path / "model_horizons.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        horizons = list(csv.DictReader(stream))
    assert next(row for row in horizons if row["member_name"] == "Horizon 1")["boundary_role_guess"] == "technical_k_interface"
    assert next(row for row in horizons if row["member_name"] == "Ach5_bot")["boundary_role_guess"] == "formation_base"


def _stub(
    class_name: str,
    uuid: str,
    parent_uuid: str | None,
    visual_name: str,
    *,
    kid_index: int = 0,
) -> PetrelProjectStub:
    return PetrelProjectStub(
        class_name=class_name,
        stub_type="SubjectStub",
        uuid=uuid,
        parent_uuid=parent_uuid,
        kid_index=kid_index,
        visual_name=visual_name,
        has_visible_icon=True,
    )

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import struct
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.petrel.bxml_bridge import (  # noqa: E402
    convert_bxml_to_xml,
    convert_bxml_batch,
    ensure_bxml_bridge,
    find_petrel_persistence_assembly,
    profile_bxml_to_tsv,
)
from research.petrel.project_metadata import read_project_stubs, stubs_by_uuid  # noqa: E402
from research.petrel.project_extractors import (  # noqa: E402
    read_well_shape_points,
    read_points3,
    read_xyz_trajectory_points,
    resolve_well_stub,
)
from research.petrel.project_inspector import (  # noqa: E402
    PetrelProjectReader,
    write_decoded_lz4_file,
)


def inspect_project(
    project_path: str,
    output_dir: str | None,
    *,
    deep: bool,
    metadata: bool,
    trajectories: bool,
    points: bool,
    arrays: bool,
    extras: bool,
    prefix_bytes: int,
) -> Path:
    source = Path(project_path).resolve()
    destination = Path(output_dir).resolve() if output_dir else source.parent / f"{source.stem}_inventory"
    destination.mkdir(parents=True, exist_ok=True)

    with PetrelProjectReader(source) as reader:
        objects = reader.list_objects()
        summary = {
            "source": str(reader.paths.source_path),
            "project_file": str(reader.paths.project_file) if reader.paths.project_file else None,
            "project_folder": str(reader.paths.project_folder),
            "data_path": str(reader.paths.data_path),
            "model_path": str(reader.paths.model_path) if reader.paths.model_path else None,
            "object_count": len(objects),
            "stored_bytes": sum(item.stored_bytes for item in objects),
            "object_types": reader.object_type_counts(),
        }
        _write_objects_csv(destination / "objects.csv", objects)

        if metadata or trajectories or points or arrays:
            summary["metadata"] = _extract_project_metadata(reader, objects, destination)

        if trajectories:
            summary["trajectory_extraction"] = _extract_trajectories(reader, objects, destination)

        if points:
            summary["points_extraction"] = _extract_points(reader, objects, destination)

        if arrays:
            summary["array_extraction"] = _extract_array_profiles(reader, objects, destination)

        if extras:
            summary["extra_extraction"] = _extract_extra_objects(reader, objects, destination)

        if deep:
            diagnostics = []
            for index, item in enumerate(objects, start=1):
                print(f"[{index}/{len(objects)}] {item.blob_type or '(untyped)'} {item.droid}", flush=True)
                diagnostics.append(
                    reader.inspect_object(item.data_pk, bxml_prefix_bytes=prefix_bytes).as_dict()
                )
            _write_json(destination / "object_diagnostics.json", diagnostics)

        _write_json(destination / "summary.json", summary)

    print(f"Inventory written to: {destination}")
    return destination


def _write_objects_csv(path: Path, objects: list[object]) -> None:
    _write_csv(path, [item.as_dict() for item in objects])


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _extract_project_metadata(reader, objects, destination: Path) -> dict[str, object]:
    assembly = find_petrel_persistence_assembly()
    if assembly is None:
        return {"status": "unavailable", "reason": "Petrel persistence assembly was not found"}
    if reader.paths.project_file is None:
        return {"status": "unavailable", "reason": "Project .pet file was not found"}

    bridge = ensure_bxml_bridge(ROOT / "build" / "PetrelBxmlBridge.exe")
    project_bxml = destination / "project.bxml"
    project_xml = destination / "project.xml"
    project_decoded_bytes = write_decoded_lz4_file(reader.paths.project_file, project_bxml)
    convert_bxml_to_xml(
        project_bxml,
        project_xml,
        bridge_path=bridge,
        persistence_assembly=assembly,
    )
    stubs = read_project_stubs(project_xml)
    stub_index = stubs_by_uuid(stubs)
    stub_rows = [stub.as_dict() for stub in stubs]
    _write_csv(destination / "project_stubs.csv", stub_rows)

    enriched_rows: list[dict[str, object]] = []
    matched = 0
    for item in objects:
        row = item.as_dict()
        stub = stub_index.get(item.uuid or "")
        if stub:
            matched += 1
            row.update({f"project_{key}": value for key, value in stub.as_dict().items()})
        else:
            row.update(
                {
                    "project_class_name": None,
                    "project_stub_type": None,
                    "project_uuid": None,
                    "project_parent_uuid": None,
                    "project_kid_index": None,
                    "project_visual_name": None,
                    "project_has_visible_icon": None,
                }
            )
        enriched_rows.append(row)
    _write_csv(destination / "objects_enriched.csv", enriched_rows)

    selections = {
        "wells.csv": {"WellTraceSubject"},
        "trajectories.csv": {"XYZTrajectoryProviderSubject"},
        "grids.csv": {"PillarGridSubject"},
        "properties.csv": {"PropertySubject"},
    }
    for filename, classes in selections.items():
        _write_csv(
            destination / filename,
            [row for row in stub_rows if str(row["class_name"]) in classes],
        )
    _write_csv(
        destination / "well_tops_objects.csv",
        [row for row in stub_rows if "WellTops" in str(row["class_name"])],
    )
    model_inventory = _write_model_inventory(destination, stubs)

    model_decoded_bytes = None
    if reader.paths.model_path:
        model_bxml = destination / "model.bxml"
        model_xml = destination / "model.xml"
        model_decoded_bytes = write_decoded_lz4_file(reader.paths.model_path, model_bxml)
        convert_bxml_to_xml(
            model_bxml,
            model_xml,
            bridge_path=bridge,
            persistence_assembly=assembly,
        )

    class_counts: dict[str, int] = {}
    for stub in stubs:
        class_counts[stub.class_name] = class_counts.get(stub.class_name, 0) + 1
    return {
        "status": "decoded",
        "persistence_assembly": str(assembly),
        "project_decoded_bytes": project_decoded_bytes,
        "model_decoded_bytes": model_decoded_bytes,
        "stub_count": len(stubs),
        "class_count": len(class_counts),
        "stored_objects_matched_by_uuid": matched,
        "key_classes": {
            key: class_counts.get(key, 0)
            for key in (
                "PillarGridSubject",
                "PropertySubject",
                "WellTraceSubject",
                "XYZTrajectoryProviderSubject",
                "WellTopsSubject",
                "WellTopsSurfaceSubject",
            )
        },
        "model_inventory": model_inventory,
    }


def _write_model_inventory(destination: Path, stubs: list[object]) -> list[dict[str, object]]:
    stub_index = stubs_by_uuid(stubs)
    grids = [stub for stub in stubs if stub.class_name == "PillarGridSubject"]
    member_groups = {
        "PropertySubject": [],
        "HorizonSubject": [],
        "ZoneSubject": [],
    }
    for stub in stubs:
        if stub.class_name not in member_groups:
            continue
        grid = _ancestor_of_class(stub, "PillarGridSubject", stub_index)
        if grid:
            member_groups[stub.class_name].append((grid, stub))

    property_rows = [_model_member_row(grid, item) for grid, item in member_groups["PropertySubject"]]
    horizon_rows = [
        {
            **_model_member_row(grid, item),
            "is_named_horizon": not _is_technical_horizon(item.visual_name),
            "boundary_role_guess": _boundary_role_guess(item.visual_name),
        }
        for grid, item in member_groups["HorizonSubject"]
    ]
    zone_rows = [_model_member_row(grid, item) for grid, item in member_groups["ZoneSubject"]]
    _write_csv(destination / "model_properties.csv", property_rows)
    _write_csv(destination / "model_horizons.csv", horizon_rows)
    _write_csv(destination / "model_zones.csv", zone_rows)

    summaries: list[dict[str, object]] = []
    for grid in grids:
        properties = [row["member_name"] for row in property_rows if row["grid_uuid"] == grid.uuid]
        horizons = [row for row in horizon_rows if row["grid_uuid"] == grid.uuid]
        zones = [row for row in zone_rows if row["grid_uuid"] == grid.uuid]
        named_horizons = [str(row["member_name"]) for row in horizons if row["is_named_horizon"]]
        geological_markers = sorted(
            name
            for name in properties
            if any(marker in str(name).upper() for marker in ("PORO", "PERM", "NTG"))
        )
        summaries.append(
            {
                "grid_uuid": grid.uuid,
                "grid_name": grid.visual_name,
                "model_uuid": (_ancestor_of_class(grid, "ModelSubject", stub_index) or grid).uuid,
                "model_name": (_ancestor_of_class(grid, "ModelSubject", stub_index) or grid).visual_name,
                "is_geological_candidate": bool(geological_markers),
                "geological_markers": " | ".join(geological_markers),
                "property_count": len(properties),
                "properties": " | ".join(str(name) for name in properties),
                "horizon_count": len(horizons),
                "named_horizon_count": len(named_horizons),
                "named_horizons": " | ".join(named_horizons),
                "zone_count": len(zones),
            }
        )
    _write_csv(destination / "model_summary.csv", summaries)
    return summaries


def _ancestor_of_class(stub, class_name: str, stub_index: dict[str, object]):
    current = stub
    visited: set[str] = set()
    while current.parent_uuid and current.parent_uuid not in visited:
        visited.add(current.parent_uuid)
        current = stub_index.get(current.parent_uuid)
        if current is None:
            return None
        if current.class_name == class_name:
            return current
    return None


def _model_member_row(grid, item) -> dict[str, object]:
    return {
        "grid_uuid": grid.uuid,
        "grid_name": grid.visual_name,
        "member_uuid": item.uuid,
        "member_name": item.visual_name,
        "member_class": item.class_name,
        "kid_index": item.kid_index,
        "parent_uuid": item.parent_uuid,
    }


def _is_technical_horizon(name: str | None) -> bool:
    return bool(name and re.fullmatch(r"Horizon\s+\d+", name, flags=re.IGNORECASE))


def _boundary_role_guess(name: str | None) -> str:
    value = (name or "").lower()
    if _is_technical_horizon(name):
        return "technical_k_interface"
    if value == "top_gmm":
        return "model_top"
    if value == "bot_gmm":
        return "model_base"
    if "bot" in value:
        return "formation_base"
    return "named_horizon"


def _extract_trajectories(reader, objects, destination: Path) -> dict[str, object]:
    assembly = find_petrel_persistence_assembly()
    project_xml = destination / "project.xml"
    if assembly is None or not project_xml.is_file():
        return {"status": "unavailable", "reason": "Decoded project metadata is required"}
    bridge = ensure_bxml_bridge(ROOT / "build" / "PetrelBxmlBridge.exe")
    stubs = stubs_by_uuid(read_project_stubs(project_xml))
    selected = [
        item
        for item in objects
        if item.blob_type in {"XYZTrajectoryProviderData", "DummyWellTraceSubjectShape"}
    ]
    shape_rows: list[dict[str, object]] = []
    xyz_rows: list[dict[str, object]] = []
    with TemporaryDirectory(prefix="petrel_trajectory_", dir=destination) as temporary:
        temporary_path = Path(temporary)
        files: list[tuple[Path, Path]] = []
        object_xml: dict[int, Path] = {}
        for index, item in enumerate(selected, start=1):
            print(f"[trajectory {index}/{len(selected)}] {item.blob_type} {item.uuid}", flush=True)
            bxml_path = temporary_path / f"{item.data_pk}.bxml"
            xml_path = temporary_path / f"{item.data_pk}.xml"
            reader.write_decoded_object(item.data_pk, bxml_path)
            files.append((bxml_path, xml_path))
            object_xml[item.data_pk] = xml_path
        convert_bxml_batch(
            files,
            manifest_path=temporary_path / "manifest.tsv",
            bridge_path=bridge,
            persistence_assembly=assembly,
        )

        for item in selected:
            well = resolve_well_stub(item.uuid, stubs)
            common = {
                "object_uuid": item.uuid or "",
                "well_uuid": well.uuid if well else None,
                "well_name": well.visual_name if well else None,
            }
            if item.blob_type == "DummyWellTraceSubjectShape":
                shape_rows.extend(read_well_shape_points(object_xml[item.data_pk], **common))
            else:
                xyz_rows.extend(read_xyz_trajectory_points(object_xml[item.data_pk], **common))

    _write_csv(destination / "well_trajectory_points.csv", shape_rows)
    _write_csv(destination / "xyz_trajectory_provider_points.csv", xyz_rows)
    return {
        "status": "decoded",
        "shape_object_count": sum(item.blob_type == "DummyWellTraceSubjectShape" for item in selected),
        "shape_point_count": len(shape_rows),
        "xyz_provider_count": sum(item.blob_type == "XYZTrajectoryProviderData" for item in selected),
        "xyz_point_count": len(xyz_rows),
        "shape_wells_resolved": len({row["well_uuid"] for row in shape_rows if row["well_uuid"]}),
        "xyz_wells_resolved": len({row["well_uuid"] for row in xyz_rows if row["well_uuid"]}),
    }


def _extract_points(reader, objects, destination: Path) -> dict[str, object]:
    assembly = find_petrel_persistence_assembly()
    project_xml = destination / "project.xml"
    if assembly is None or not project_xml.is_file():
        return {"status": "unavailable", "reason": "Decoded project metadata is required"}
    bridge = ensure_bxml_bridge(ROOT / "build" / "PetrelBxmlBridge.exe")
    stubs = read_project_stubs(project_xml)
    attribute_stubs = [stub for stub in stubs if stub.class_name == "PointsAttrSubject"]
    selected = [item for item in objects if item.blob_type == "Points3"]
    rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    with TemporaryDirectory(prefix="petrel_points_", dir=destination) as temporary:
        temporary_path = Path(temporary)
        files: list[tuple[Path, Path]] = []
        object_xml: dict[int, Path] = {}
        for item in selected:
            bxml_path = temporary_path / f"{item.data_pk}.bxml"
            xml_path = temporary_path / f"{item.data_pk}.xml"
            reader.write_decoded_object(item.data_pk, bxml_path)
            files.append((bxml_path, xml_path))
            object_xml[item.data_pk] = xml_path
        convert_bxml_batch(
            files,
            manifest_path=temporary_path / "manifest.tsv",
            bridge_path=bridge,
            persistence_assembly=assembly,
        )
        for item in selected:
            object_rows = read_points3(
                object_xml[item.data_pk],
                object_uuid=item.uuid or "",
                attribute_stubs=attribute_stubs,
            )
            rows.extend(object_rows)
            summaries.append(
                {
                    "object_uuid": item.uuid,
                    "point_count": len(object_rows),
                    "project_name": next(
                        (stub.visual_name for stub in stubs if stub.uuid == item.uuid),
                        None,
                    ),
                }
            )
    _write_csv(destination / "points3.csv", rows)
    _write_csv(destination / "points3_summary.csv", summaries)
    return {
        "status": "decoded",
        "object_count": len(selected),
        "point_count": len(rows),
        "attribute_count": max((len(row) - 6 for row in rows), default=0),
    }


def _extract_array_profiles(reader, objects, destination: Path) -> dict[str, object]:
    assembly = find_petrel_persistence_assembly()
    project_xml = destination / "project.xml"
    if assembly is None or not project_xml.is_file():
        return {"status": "unavailable", "reason": "Decoded project metadata is required"}

    bridge = ensure_bxml_bridge(ROOT / "build" / "PetrelBxmlBridge.exe")
    stub_index = stubs_by_uuid(read_project_stubs(project_xml))
    selected = [
        item
        for item in objects
        if item.blob_type in {"FloatProperty", "IntProperty", "PillarGrid2"}
    ]
    profile_rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    with TemporaryDirectory(prefix="petrel_arrays_", dir=destination) as temporary:
        temporary_path = Path(temporary)
        for index, item in enumerate(selected, start=1):
            stub = stub_index.get(item.uuid or "")
            display_name = stub.visual_name if stub else None
            print(
                f"[array {index}/{len(selected)}] {item.blob_type} "
                f"{display_name or item.uuid or item.data_pk}",
                flush=True,
            )
            bxml_path = temporary_path / f"{item.data_pk}.bxml"
            profile_path = temporary_path / f"{item.data_pk}.tsv"
            decoded_bytes = reader.write_decoded_object(item.data_pk, bxml_path)
            profile_bxml_to_tsv(
                bxml_path,
                profile_path,
                bridge_path=bridge,
                persistence_assembly=assembly,
            )
            object_profiles = _read_profile_rows(profile_path)
            common = {
                "data_pk": item.data_pk,
                "object_uuid": item.uuid,
                "blob_type": item.blob_type,
                "project_name": display_name,
                "project_class_name": stub.class_name if stub else None,
                "stored_bytes": item.stored_bytes,
                "decoded_bytes": decoded_bytes,
            }
            profile_rows.extend({**common, **row} for row in object_profiles)
            summaries.append(_summarize_array_profile(common, object_profiles))
            bxml_path.unlink(missing_ok=True)
            profile_path.unlink(missing_ok=True)

    _write_csv(destination / "array_profiles.csv", profile_rows)
    _write_csv(destination / "array_summary.csv", summaries)
    _write_csv(
        destination / "property_summary.csv",
        [row for row in summaries if row["blob_type"] in {"FloatProperty", "IntProperty"}],
    )
    _write_csv(
        destination / "grid_summary.csv",
        [row for row in summaries if row["blob_type"] == "PillarGrid2"],
    )
    return {
        "status": "profiled",
        "object_count": len(selected),
        "property_count": sum(
            item.blob_type in {"FloatProperty", "IntProperty"} for item in selected
        ),
        "grid_count": sum(item.blob_type == "PillarGrid2" for item in selected),
        "profile_path_count": len(profile_rows),
        "decoded_bytes": sum(int(row["decoded_bytes"]) for row in summaries),
    }


def _read_profile_rows(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    integer_fields = {
        "elements",
        "text_values",
        "text_characters",
        "numeric_values",
        "bounded_numeric_values",
        "binary_bytes",
        "binary_zero_bytes",
        "binary_minimum",
        "binary_maximum",
        "component_width",
    }
    float_fields = {
        "minimum",
        "maximum",
        "mean",
        "bounded_minimum",
        "bounded_maximum",
        "bounded_mean",
        "binary_mean",
    }
    for row in rows:
        for field in integer_fields:
            row[field] = int(row[field] or 0)
        for field in float_fields:
            row[field] = float(row[field]) if row[field] else None
    return rows


def _summarize_array_profile(
    common: dict[str, object],
    profile_rows: list[dict[str, object]],
) -> dict[str, object]:
    by_path = {str(row["path"]): row for row in profile_rows}

    def values_for_path(suffix: str) -> list[str]:
        match = next((row for path, row in by_path.items() if path.endswith(suffix)), None)
        return str(match.get("samples") or "").split(" | ") if match else []

    if common["blob_type"] == "PillarGrid2":
        value_row = next(
            (row for path, row in by_path.items() if path.endswith("/sequence/zvalues/float")),
            None,
        )
    else:
        candidates = [
            row
            for path, row in by_path.items()
            if "/values/" in path
            and (int(row["numeric_values"]) > 0 or int(row["binary_bytes"]) > 0)
        ]
        value_row = max(
            candidates,
            key=lambda row: max(int(row["numeric_values"]), int(row["binary_bytes"])),
            default=None,
        )
    value_count = (
        max(int(value_row["numeric_values"]), int(value_row["binary_bytes"]))
        if value_row
        else 0
    )
    value_minimum = None
    value_maximum = None
    value_mean = None
    bounded_count = 0
    bounded_minimum = None
    bounded_maximum = None
    bounded_mean = None
    if value_row:
        if int(value_row["binary_bytes"]) > 0:
            value_minimum = value_row["binary_minimum"]
            value_maximum = value_row["binary_maximum"]
            value_mean = value_row["binary_mean"]
            bounded_count = int(value_row["binary_bytes"])
            bounded_minimum = value_minimum
            bounded_maximum = value_maximum
            bounded_mean = value_mean
        else:
            value_minimum = value_row["minimum"]
            value_maximum = value_row["maximum"]
            value_mean = value_row["mean"]
            bounded_count = int(value_row["bounded_numeric_values"])
            bounded_minimum = value_row["bounded_minimum"]
            bounded_maximum = value_row["bounded_maximum"]
            bounded_mean = value_row["bounded_mean"]
    node_values = values_for_path("/node_size/int")
    pillar_row = next(
        (row for path, row in by_path.items() if path.endswith("/pillars/pillar/degree")),
        None,
    )
    vertical_nodes = None
    if common["blob_type"] == "PillarGrid2" and value_row and pillar_row:
        pillar_count = int(pillar_row["numeric_values"])
        if pillar_count and value_count % pillar_count == 0:
            vertical_nodes = value_count // pillar_count
            node_values.append(str(vertical_nodes))
    component_minimum = _component_values(value_row, "component_minimum")
    component_maximum = _component_values(value_row, "component_maximum")
    coordinate_row = next(
        (
            row
            for path, row in by_path.items()
            if path.endswith("/position/double") or path.endswith("/vertices/double")
        ),
        None,
    )
    coordinate_minimum = _component_values(coordinate_row, "component_minimum")
    coordinate_maximum = _component_values(coordinate_row, "component_maximum")
    cell_values = values_for_path("/cell_size/int")
    if common["blob_type"] == "PillarGrid2" and len(node_values) == 3:
        cell_values = [str(int(value) - 1) for value in node_values]
    return {
        **common,
        "cell_size": " x ".join(cell_values),
        "node_size": " x ".join(node_values),
        "bool_count": _first_sample(values_for_path("/bool_count")),
        "no_elements": _first_sample(values_for_path("/no_elements")),
        "value_path": value_row["path"] if value_row else None,
        "value_count": value_count,
        "value_minimum": value_minimum,
        "value_maximum": value_maximum,
        "value_mean": value_mean,
        "bounded_value_count": bounded_count,
        "bounded_value_minimum": bounded_minimum,
        "bounded_value_maximum": bounded_maximum,
        "bounded_value_mean": bounded_mean,
        "x_minimum": coordinate_minimum[0] if len(coordinate_minimum) > 0 else None,
        "x_maximum": coordinate_maximum[0] if len(coordinate_maximum) > 0 else None,
        "y_minimum": coordinate_minimum[1] if len(coordinate_minimum) > 1 else None,
        "y_maximum": coordinate_maximum[1] if len(coordinate_maximum) > 1 else None,
        "z_minimum": component_minimum[2] if len(component_minimum) > 2 else value_minimum,
        "z_maximum": component_maximum[2] if len(component_maximum) > 2 else value_maximum,
        "path_count": len(profile_rows),
    }


def _first_sample(values: list[str]) -> str | None:
    return values[0] if values and values[0] else None


def _component_values(row: dict[str, object] | None, field: str) -> list[float]:
    if not row or not row.get(field):
        return []
    return [float(value) for value in str(row[field]).split(" | ") if value]


def _extract_extra_objects(reader, objects, destination: Path) -> dict[str, object]:
    covered_types = {
        "FloatProperty",
        "IntProperty",
        "PillarGrid2",
        "XYZTrajectoryProviderData",
        "DummyWellTraceSubjectShape",
        "Points3",
    }
    selected = [item for item in objects if item.blob_type not in covered_types]
    assembly = find_petrel_persistence_assembly()
    bridge = ensure_bxml_bridge(ROOT / "build" / "PetrelBxmlBridge.exe") if assembly else None
    output = destination / "extra_objects"
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    bxml_count = 0
    raw_count = 0
    for item in selected:
        stored = reader.read_stored_object(item.data_pk)
        common = item.as_dict()
        if stored.startswith(b"LZ4\x01"):
            bxml_count += 1
            bxml_path = output / f"{item.data_pk}_{item.blob_type or 'object'}.bxml"
            xml_path = output / f"{item.data_pk}_{item.blob_type or 'object'}.xml"
            decoded_bytes = reader.write_decoded_object(item.data_pk, bxml_path)
            if bridge and assembly:
                convert_bxml_to_xml(
                    bxml_path,
                    xml_path,
                    bridge_path=bridge,
                    persistence_assembly=assembly,
                )
            rows.append(
                {
                    **common,
                    "storage_encoding": "petrel-lz4-bxml",
                    "decoded_bytes": decoded_bytes,
                    "output_file": str(xml_path.relative_to(destination)) if xml_path.is_file() else str(bxml_path.relative_to(destination)),
                    "prefix_hex": stored[:64].hex(" "),
                    "uint32_le": None,
                    "int32_le": None,
                    "float32_le": None,
                    "float64_le": None,
                }
            )
        else:
            raw_count += 1
            raw_path = output / f"{item.data_pk}_{_safe_filename(item.droid)}.bin"
            raw_path.write_bytes(stored)
            rows.append(
                {
                    **common,
                    "storage_encoding": "raw",
                    "decoded_bytes": None,
                    "output_file": str(raw_path.relative_to(destination)),
                    "prefix_hex": stored[:64].hex(" "),
                    "uint32_le": _unpack_values(stored, "I"),
                    "int32_le": _unpack_values(stored, "i"),
                    "float32_le": _unpack_values(stored, "f"),
                    "float64_le": _unpack_values(stored, "d"),
                }
            )
    _write_csv(destination / "extra_objects.csv", rows)
    return {
        "status": "decoded",
        "object_count": len(selected),
        "bxml_object_count": bxml_count,
        "raw_object_count": raw_count,
    }


def _safe_filename(value: str) -> str:
    name = value.rsplit("/", 1)[-1] or "object"
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in name)


def _unpack_values(data: bytes, code: str) -> str:
    size = struct.calcsize("<" + code)
    count = len(data) // size
    if count == 0:
        return ""
    values = struct.unpack("<" + code * count, data[: count * size])
    return " | ".join(str(value) for value in values)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory a native Petrel .pet/.ptd project read-only.")
    parser.add_argument("project_path", help="Path to .pet, .ptd folder, Data.ptd, or containing folder")
    parser.add_argument("--output-dir", help="Output directory for JSON/CSV reports")
    parser.add_argument("--deep", action="store_true", help="Decode every LZ4 stream and profile Petrel BXML")
    parser.add_argument(
        "--metadata",
        action="store_true",
        help="Decode .pet/Model.ptd metadata using the installed Petrel persistence assembly",
    )
    parser.add_argument(
        "--trajectories",
        action="store_true",
        help="Extract all native well trajectory coordinates and MD values",
    )
    parser.add_argument(
        "--points",
        action="store_true",
        help="Extract all Points3 vertices and typed attributes, including Well Tops",
    )
    parser.add_argument(
        "--arrays",
        action="store_true",
        help="Profile every native property and PillarGrid2 array without expanding full XML",
    )
    parser.add_argument(
        "--extras",
        action="store_true",
        help="Decode service BXML and dump untyped raw project objects",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Extract metadata, trajectories, Points3, array profiles, and extra objects",
    )
    parser.add_argument(
        "--prefix-bytes",
        type=int,
        default=1_048_576,
        help="Decoded prefix retained for each BXML profile (default: 1 MiB)",
    )
    args = parser.parse_args()
    inspect_project(
        args.project_path,
        args.output_dir,
        deep=args.deep,
        metadata=args.metadata or args.all,
        trajectories=args.trajectories or args.all,
        points=args.points or args.all,
        arrays=args.arrays or args.all,
        extras=args.extras or args.all,
        prefix_bytes=args.prefix_bytes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

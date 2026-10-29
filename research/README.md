# Research tools

Tools for reverse-engineering native Petrel project storage. They are not used
by the application; keep them for decoding new Petrel object types.

## Petrel project inspector

Read-only inventory of a `.pet` / `.ptd` project: stored objects, types, sizes,
BXML profiles. Writes JSON/CSV reports.

```bash
python -m research.petrel.inspect_project <project.pet> --output-dir <dir>
python -m research.petrel.inspect_project <project.pet> --all   # metadata, trajectories, points, arrays, extras
python -m research.petrel.inspect_project <project.pet> --deep  # decode every LZ4 stream and profile BXML
```

## BXML bridge (Windows + installed Petrel)

`petrel/PetrelBxmlBridge.cs` uses Petrel's own
`Slb.Ocean.Petrel.Data.Persistence.dll` to convert binary BXML streams to XML.
`petrel/bxml_bridge.py` finds the installed Petrel and compiles/runs the bridge.
Only works on Windows with Petrel installed.

Modules:

- `petrel/project_inspector.py` — project catalogue, LZ4/BXML decoding.
- `petrel/project_metadata.py` — project stubs (names, hierarchy) from XML.
- `petrel/project_extractors.py` — well shapes, XYZ trajectories, point sets.
- `petrel/bxml_bridge.py`, `petrel/PetrelBxmlBridge.cs` — Petrel BXML→XML bridge.

Tests: `tests/test_research_petrel_*.py`.

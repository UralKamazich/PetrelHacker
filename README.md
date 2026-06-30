# PetrelHacker

Desktop extractor for Petrel geological/geomechanical grids. The application maps frac sleeves/ports to model XY columns, extracts selected property cubes along depth, writes XLSX/CSV tables, calculates interval metrics, and provides a curve QC view.

The code supports two Petrel export families:

- RESQML/EPC: an `.epc` ZIP package with XML metadata plus a sibling `.h5` file with arrays.
- Petrel Rescue: a folder or main `.bin` model file with many sidecar `*.bin.<id>` binary files.

This README is intentionally explicit about indexing and storage rules so another engineer or LLM can reason about the files without rediscovering them from scratch.

## Setup

Use the repository virtual environment from the shared work directory when available:

```powershell
& 'D:\Yandex.Disk\!!!!DataAnalizePython Work\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& 'D:\Yandex.Disk\!!!!DataAnalizePython Work\.venv\Scripts\python.exe' main.py
```

Or create a local one:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## GUI Workflow

1. Open `Model`.
2. Select up to three models. Each model can be `.epc`, a Rescue main `.bin`, or a Rescue folder.
3. Set optional depth offsets in meters for each model.
4. Click `Load models`.
5. Check properties on the `Properties` tab.
6. Load the sleeves table on `Sleeves`.
7. Map frac-list columns in the dialog. The dialog is shown every time a sleeves table is loaded, even when column names are already recognized.
8. Click `Выбор скважин` to choose wells in a checkbox dialog. All wells are selected by default and the selected names are shown in the long field on `Sleeves`.
9. Run extraction on `Run`.
10. Use `Preview`, `Curves`, and `Metrics` for QC and interval calculations.

`Curves / QC` can draw channels in two depth modes. `Common grid` uses the
shared output grid depth (`TVD_top`) for every channel. `Individual cell` uses
the channel diagnostic depth (`<channel>_TVD_center`) when available, which is
better for checking whether the original RESQML and Rescue cells match.

`Run` has two performance controls for multi-model extraction:

- `Write property diagnostics` writes `<channel>_Model`, `<channel>_I/J/K`,
  `<channel>_TVD_center`, and `<channel>_Depth_KB`. Disable it for faster and
  narrower production exports after QC is complete.
- `Parallel workers` parallelizes sleeve/port row calculation. Final XLSX/CSV
  writing remains single-threaded to keep output order stable and avoid writer
  contention.

The model loader now prints and displays a summary for each model: backend, grid shape, estimated cell sizes, well datum count, and available property cubes.

## Sleeve Input Contract

The sleeves table must contain columns that can be mapped to:

- `Well`
- `Port`
- `X`
- `Y`
- `TVDSS_PORT` or compatible depth column

Coordinates are used to select the nearest model XY column. `TVDSS_PORT` is used for relative depth calculations. If RESQML well datums are present, output also includes KB-depth columns:

- `Datum_Z`
- `Depth_KB_PORT`
- `Depth_KB_top`
- `Depth_KB_base`
- `Depth_KB_center`

The app normalizes some well aliases, including Cyrillic/Latin lookalikes such as `6А031` vs `6A031`.

The `Sleeves` tab always asks how source columns should map to the required
fields. This handles frac lists where `Well`, `Port`, `X`, `Y`, or `TVDSS_PORT`
are named differently. After loading, the `Выбор скважин` button opens a
checkbox dialog populated from the normalized `Well` column. The selected wells
are displayed in the long field on the tab, and the extraction worker filters
the frac list to those wells before building the output plan and progress
counters. Leaving all wells checked keeps the historical behavior.

## RESQML / EPC Storage

RESQML input is opened by `core.resqml_reader.ResqmlReader`.

Expected file layout:

- `.epc`: ZIP archive with XML objects.
- `.h5`: HDF5 file next to the `.epc`, same basename.

Important XML objects:

- `IjkGridRepresentation`: grid title, UUID, `Ni`, `Nj`, `Nk`, and HDF paths.
- `ContinuousProperty` / `DiscreteProperty`: property title, UUID, property kind, UOM, and HDF path.
- `MdDatum`: well datum, usually Kelly Bushing, used to convert TVDSS-like depth to KB depth.

Array conventions observed in current Petrel exports:

- Grid shape is `NI x NJ x NK`.
- RESQML property HDF arrays are usually stored as `NK x NJ x NI`.
- Property value lookup is `dataset[k, j, i]`.
- Vertical geometry comes from the HDF `Points` dataset.
- Cell interface Z is averaged across the four cell pillars.
- If HDF Z values are negative, depth is interpreted as `-Z`.
- Cell top/base are `min(interface_depth[k], interface_depth[k+1])` and `max(...)`.

Encoding note:

- Some Petrel exports declare UTF-8 XML but contain CP1251 Cyrillic titles.
- `ResqmlReader` first parses raw XML bytes, then falls back to CP1251/Latin1 before using replacement characters.
- If UI shows `����` or `�`, suspect a new encoding edge case in EPC XML text fields.

## Petrel Rescue Storage

Rescue input is opened by `core.rescue_reader.RescueReader`.

Expected folder layout:

- Main model file: `*.bin`, starts with `%Rescue Model File`.
- Geometry file: one sidecar `*.bin.<id>`, header contains `Rescue Geometry File`.
- Property files: many sidecar `*.bin.<id>`, header contains `Rescue Property File`.
- CRS metadata: usually `*.crsmeta.xml`.

Rescue grid dimensions:

- Geometry file stores raw node/interface dimensions.
- Public cell dimensions are `raw_ni - 1`, `raw_nj - 1`, `raw_nk - 1`.
- Example: raw `98 x 212 x 622` means cell grid `97 x 211 x 621`.

Rescue property stream rules:

- Values are big-endian float32.
- Compact streams contain run/skip commands.
- Logical property indexing is cell-based, not node-based.
- Current validated flat index:

```python
flat_index = (nk - 1 - k) * nj * ni + j * ni + i
```

This means Rescue property K is reversed relative to public `k` indexing.

Rescue geometry stream rules:

- Geometry sidecar contains one Z-interface block per raw pillar.
- Pillar block order is `i * raw_nj + j`.
- This is deliberately different from the property flat indexing.
- Four neighboring pillars are averaged to get one cell column interface depth.
- Public cell geometry is built from reversed Rescue Z interfaces.

Important fixed bug:

- Older code read geometry blocks as `j * raw_ni + i`.
- That made property values look correct but assigned depths from the wrong XY pillar.
- The validated order is `i * raw_nj + j`.

Rescue limitations:

- Rescue CRS metadata used here gives horizontal XY bounds, not well KB datums.
- If KB-depth output is needed, load a RESQML model with `MdDatum` in the same run, or use the `TVDSS_*` columns.
- XY indexing for Rescue is regular-grid based from CRS bounds. RESQML can use real top-pillar XY geometry.

## Multi-Model Extraction

The extractor accepts up to three models.

For every sleeve:

1. Each model maps `X/Y` to its nearest grid column.
2. Each model loads that column geometry and selected property columns.
3. Depth boundaries from all loaded columns are merged.
4. Output rows are created over the union of depth intervals.
5. Each property is sampled/aggregated over each interval.

Depth boundary merge:

- RESQML and Rescue can represent the same boundary with tiny float differences.
- Boundaries within `0.001 m` are merged.
- This prevents false micro-intervals such as `0.000015 m` rows when comparing the same model in two formats.

When property names repeat across models, output columns are prefixed:

- `YME_STA` if selected once.
- `M2_YME_STA`, `M3_YME_STA` if selected from multiple models.

Diagnostic columns are written for every property:

- `{property}_Model`
- `{property}_I`
- `{property}_J`
- `{property}_K`
- `{property}_TVD_center`
- `{property}_Depth_KB`

Use these diagnostics for validation. If two model formats represent the same model, compare by `{property}_I/J/K`, not only by output row number.

## Units And Property Handling

Known transforms:

- Permeability-like properties containing `perm` in the title are converted to mD by `1013250000000000`.
- Rescue density-like properties are scaled by `1000` on output, because current Rescue exports store density around `2.5`, while RESQML stores around `2500`.
- Integer NoData markers `2147483647` and `-2147483648` are exported as blank cells.

Known caveats:

- Some Rescue property files have fewer stored valid values than RESQML for the same property.
- `YME_STA`, `YME_DYN`, `UCS`, `TSTR`, and `FANG` matched RESQML exactly in the current validation pair.
- `PR_STA` and `PR_DYN` matched only partially in the current validation pair and require separate investigation before using them as a format-equivalence benchmark.
- `FBID` Rescue decoding currently returns no finite values for the current validation pair.

## Current Validation Pair

Local validation data:

- `GeolModel/UR_stat_RESQML/6A_GMM_STAT.epc`
- `GeolModel/UR_stat_RESQML/6A_GMM_STAT.h5`
- `GeolModel/UR_stat_RESCUE/`

These are the same Petrel model exported in two formats.

RESQML summary:

- Backend: `xml` or `resqpy+xml` depending on installed packages.
- Grid title: `Кубы свойств.bin`
- Grid type: `IjkGridRepresentation`
- Shape: `97 x 211 x 621`
- Cells: `12,710,007`
- Cell sizes near center column: `I~100 m`, `J~100 m`, `K median~1.82245 m`, `K min/max~0.427551/30.3423 m`
- Well datums: 6 objects, 6 unique aliases:
  - `6A011GS_NEW`
  - `6A031GS_NEW`
  - `6A032GS_NEW`
  - `6A033GS_NEW`
  - `6A034GS_NEW`
  - `6A035GS_NEW`
- Property cubes:
  - `YME_DYN`
  - `FBID`
  - `PR_STA`
  - `DENSITY`
  - `PR_DYN`
  - `YME_STA`
  - `UCS`
  - `TSTR`
  - `FANG`

Rescue summary:

- Backend: `rescue`
- Grid title: `Кубы свойств`
- Grid type: `RescueGrid`
- Shape: `97 x 211 x 621`
- Cells: `12,710,007`
- Cell sizes near center column: `I~100 m`, `J~100 m`, `K median~1.82251 m`, `K min/max~0.427246/30.3424 m`
- Well datums: not present in Rescue files.
- Property cubes:
  - `FBID` (`SegmentID`)
  - `DENSITY` (`Density`)
  - `YME_DYN` (`General`)
  - `PR_DYN` (`General`)
  - `YME_STA` (`Young's modulus`)
  - `PR_STA` (`Poissons ratio`)
  - `UCS` (`Rock strength`)
  - `TSTR` (`Rock strength`)
  - `FANG` (`Friction angle`)

Validation results after the Rescue geometry fix:

- Rescue and RESQML geometry differ by less than about `0.0003 m` for sampled columns.
- `YME_STA` values match exactly by `I/J/K`.
- False micro-intervals are removed by the `0.001 m` boundary merge.

## Metrics

Metrics are calculated from extracted XLSX/CSV and an interval table.

Interval table columns:

- `Well`
- `Port`
- `TVDSS_TOP_TOTAL`
- `TVDSS_BOT_TOTAL`
- `TVDSS_TOP_LOCAL`
- `TVDSS_BOT_LOCAL`

Supported interval families include:

- Global
- Local
- Total +/- 15 m
- TopTotal - 15 m to TopTotal
- BotTotal to BotTotal + 15 m

Metrics can be calculated for reservoir/net, non-reservoir, and full ranges depending on configured channels and suffixes.

## Useful Commands

Inspect RESQML:

```powershell
& 'D:\Yandex.Disk\!!!!DataAnalizePython Work\.venv\Scripts\python.exe' scripts\inspect_resqml.py GeolModel\UR_stat_RESQML\6A_GMM_STAT.epc
```

Run tests:

```powershell
& 'D:\Yandex.Disk\!!!!DataAnalizePython Work\.venv\Scripts\python.exe' -m pytest
```

Compile check:

```powershell
& 'D:\Yandex.Disk\!!!!DataAnalizePython Work\.venv\Scripts\python.exe' -m compileall core app tests
```

## Git Hygiene

Large local model/export files are not meant to be committed. Keep source changes scoped to:

- `app/`
- `core/`
- `tests/`
- scripts and docs

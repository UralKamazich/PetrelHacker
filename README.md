# PetrelHacker

Desktop application for extracting Petrel model properties along frac sleeves.
It maps frac-list sleeves to model grid columns, extracts selected property
cubes along depth, places reservoir boundaries on well sections, calculates
interval metrics and provides curve QC.

- UI: Electron (`electron/`), plain HTML/CSS/JS renderer with Plotly.
- Backend: Python (`web_backend/cli.py` + `core/`), one process per command,
  JSON events over stdout. Packaged builds ship it as a PyInstaller executable.
- Model sources: native Petrel projects (`.pet`), RESQML (`.epc` + `.h5`),
  Petrel Rescue (`.bin` folder). Up to three models at once.

## Branches

- `mac` — main branch, macOS desktop build.
- `win` — same application plus Windows packaging (`electron/build-desktop-win.ps1`).
  Merge `mac` into `win` before building a new Windows release.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install
bash electron/run-electron.sh          # macOS dev run
```

The renderer picks the backend Python from `.venv`. In VS Code terminals
`ELECTRON_RUN_AS_NODE=1` is set; unset it when launching Electron
(`env -u ELECTRON_RUN_AS_NODE bash electron/run-electron.sh`).

Run tests:

```bash
.venv/bin/python -m pytest
```

## Building

macOS (Apple Silicon):

```bash
bash electron/build-web.sh
# -> dist-electron-web/mac-arm64/PetrelHacker Web.app
```

Windows x64 portable exe (on the `win` branch, on Windows):

```powershell
$env:PETRELHACKER_PYTHON = "<path to .venv>\Scripts\python.exe"   # Python 3.12 x64 + requirements + pyinstaller
$env:PETRELHACKER_NODE = "<path to node.exe>"                       # Node >= 22.12 x64
powershell -ExecutionPolicy Bypass -File electron\build-desktop-win.ps1
# -> dist-electron-web\PetrelHacker-<version>-x64-portable.exe
```

The x64 build also runs on Windows on ARM (emulation).

## Workflow

Every panel has a `?` button with a detailed guide (`electron/renderer/help.js`).

1. **Models** — select up to three sources (M1–M3), pick the internal Petrel
   model, optional depth shift `Δz`, press **Load models**. Only new or changed
   models are loaded; with nothing changed all models are reloaded. Select
   properties in the per-model blocks.
2. **Wells** — load the frac-list, map columns (`Well`, `Port`, `X`, `Y`,
   `TVDSS_PORT`, `MD`), select wells, assign model trajectories. X/Y can be
   calculated from MD along the trajectory.
3. **Sections** — draw a property section along a trajectory, place interval
   boundaries (auto or manual) and save them to `<frac-list>_boundaries.xlsx`
   (also stores the section workspace).
4. **Extraction** — export model cells under every sleeve to XLSX/CSV.
   Model coverage (sleeves inside each model footprint) is checked before
   extraction; sleeves outside a model get empty values for its properties.
5. **Curves / QC** — overlay up to four channels for one stage; step through
   stages with ◀ ▶ or the arrow keys (neighbouring stages are prefetched).
6. **Metrics** — interval metrics per sleeve. Fixed channels (NTG, PORO, PERM,
   lithology, Density, Shmin) always produce the same column names so metric
   files from different models can be combined; additional channels follow on
   the right. Only channels selected on the page are calculated.

## Metrics

Intervals per sleeve (from the boundaries table): `Global`, `Local`,
`Total_pm15m`, `TopTotal_m15m`, `BotTotal_p15m`, and barrier intervals
`LocalBarriers`, `TopBarrier`, `BotBarrier` built from the TB/BB points
(barrier thickness capped at 15 m; zero/negative or missing barrier → empty
metrics); each also as `_Net` and
`_NonNet` (net by lithology codes, else NTG > 0, else PORO > 0). Column names:
`<Channel>_<metric>_<interval>[_Net|_NonNet]`. Formulas are listed in the
in-app help of the Metric set panel and in the `.txt` written next to every
metrics file. Empty `_Net` values mean the interval has no reservoir cells.

## Sleeve Input Contract

The frac-list must contain columns that can be mapped to `Well`, `Port` and
either `X`/`Y` or `MD` (X/Y are then calculated from the trajectory).
`TVDSS_PORT` is used for relative depths. If RESQML well datums are present,
output also includes KB-depth columns (`Datum_Z`, `Depth_KB_PORT`,
`Depth_KB_top`, `Depth_KB_base`, `Depth_KB_center`). Well names are
normalized, including Cyrillic/Latin lookalikes such as `6А031` vs `6A031`.

## Native Petrel Projects

`core.petrel_project_reader.PetrelProjectReader` reads `.pet` / `.ptd`
projects directly (no RESQML export needed):

- `Data.ptd` is SQLite; object blobs are LZ4-compressed BXML streams.
- Grids are `PillarGrid2` objects. Pillar record markers are derived from the
  file's BXML dictionary (tag numbers shift when a grid stores extra sections
  such as `connections`).
- Faulted pillars (types 4/5) are read using their first z-sequence; cells next
  to a fault may be offset by the fault throw.
- Grids larger than 256 MB are indexed in a streaming pass over de-framed BXML
  pages. Pillar indexes are cached in `~/Library/Caches/PetrelHacker/grid-index`.
- Decode failures name the actual cause (grid or property and the reason).

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

## Caches

macOS paths (Windows: `%LOCALAPPDATA%\PetrelHacker\...`):

- `~/Library/Caches/PetrelHacker/grid-index` — Petrel pillar indexes.
- `~/Library/Caches/PetrelHacker/curve-cache` — parquet copies of extracted
  tables (Curves and Metrics read through them; rebuilt when the file changes).
- `~/Library/Caches/PetrelHacker/section-cache` — drawn sections (+ `.meta.json`).

## Project Layout

- `electron/` — main process, preload, renderer (`renderer/app.js`, `help.js`).
- `web_backend/cli.py` — backend commands called by the UI.
- `core/` — readers (Petrel, RESQML, Rescue), extraction, metrics, sections.
- `scripts/` — command-line utilities (RESQML/Rescue inspection, batch extraction, metrics).
- `research/` — Petrel format research tools, not used by the app (see `research/README.md`).
- `tests/` — pytest suite.

Large local model/export files are not committed (see `.gitignore`).

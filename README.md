# PetrelHacker

RESQML Sleeve Property Extractor MVP for Petrel exports.

## Current state

- Console RESQML diagnostics via `scripts/inspect_resqml.py`.
- EPC XML metadata reader in `core/resqml_reader.py`.
- Minimal PySide6 GUI with tabs from the project plan.
- Model loading runs in a worker thread.
- Local RESQML data is ignored by Git.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Inspect RESQML

```powershell
python scripts/inspect_resqml.py RESQML/Urengoy.epc
```

The inspector prints grids and properties without loading full HDF5 arrays.

## Read One Property Cell

```powershell
python scripts/test_single_cell_read.py RESQML/Urengoy.epc NTG 10 20 30
```

RESQML property arrays in the current Petrel export are stored as `NK x NJ x NI`,
so core reads property values as `dataset[k, j, i]`.

## Map Sleeves To Grid Columns

```powershell
python scripts/test_sleeves_index.py RESQML/Urengoy.epc Sleeves_coord.xlsx
```

The current fast indexer uses top XY pillar geometry and nearest column centers.

## Run Fast Extraction

```powershell
python scripts/run_fast_extraction.py RESQML/Urengoy.epc Sleeves_coord.xlsx --properties NTG Layers
```

The extractor reads vertical property slices as `dataset[:, j, i]` for the
current `NK x NJ x NI` HDF5 layout, then streams rows to an XLSX file generated
next to the sleeves file.

Properties with `Perm` in the title are multiplied by `1013250000000000` during
export to convert them to mD. Integer NoData markers (`2147483647`,
`-2147483648`) are exported as blank cells.

If the estimated extraction size exceeds the Excel row limit, the GUI writes a
CSV file instead and notifies the user.

## Calculate Interval Metrics

```powershell
python scripts/calculate_interval_metrics.py Sleeves_coord_extracted.xlsx intervals.xlsx interval_metrics.xlsx --ntg-column NTG --poro-column PORO --perm-column Perm_1A --lithology-column Layers --reservoir-values 1 2 --properties NTG PORO Perm_1A
```

The interval file must contain `Well`, `Port`, `TVDSS_TOP_TOTAL`,
`TVDSS_BOT_TOTAL`, `TVDSS_TOP_LOCAL`, and `TVDSS_BOT_LOCAL`. Cells are assigned
to Global and Local intervals by cell-center TVD. The script writes Global,
Local, Global_Net, and Local_Net metrics.

## Run GUI

```powershell
python main.py
```

GUI MVP workflow:

1. Open `Model`, select `.epc`, click `Load model`.
2. Open `Sleeves`, select CSV/XLSX coordinates.
3. Open `Properties`, check 1-3 properties. The GUI auto-checks common properties
   (`NTG`, `Layers`, `PORO`, `PERM`) on first use and restores the last selection after that.
4. Open `Run` and click `Run extraction`; the output XLSX path is generated next to the sleeves file.
5. Open `Metrics`, select an interval table, configure column names and reservoir indicators,
   then calculate interval metrics from the extracted file.

The GUI also remembers the last EPC path and sleeves table path between launches.

## Notes

The next implementation step is the fast extraction path:

1. Load sleeves CSV/XLSX.
2. Map `Well`, `Port`, `X`, `Y`.
3. Stream selected property values to XLSX and write `extraction_log.txt`.
